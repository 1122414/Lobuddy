# Lobuddy 5.5 危险命令 HITL 确认执行计划

制定时间：2026-05-05  
目标版本：5.5.x  
交付对象：opencode  
涉及范围：`core/tools/`、`core/safety/`、`core/agent/`、`core/storage/`、`core/config/`、`ui/`、`app/main.py`、`tests/`

## 1. 背景与目标

当前系统已经有两层安全能力：

1. `core/tools/tool_policy.py` 用 `ToolPolicy` 做命令 allowlist、危险命令识别、链式 shell 拦截。
2. `core/safety/guardrails.py` 用 `SafetyGuardrails.validate_shell_command()` 在工具执行前把危险命令直接阻断。

这导致 `rm`、`del /q`、`rmdir /s` 这类高风险但用户可能明确需要的操作只有“阻断”一种结果。5.5 要新增 HITL（Human In The Loop）确认链路：当 agent 准备执行可人工放行的危险命令时，系统必须弹出确认框；只有用户点击确认后，该次工具调用才能继续执行。用户取消、关闭弹框、超时或无 UI 审批通道时，命令不得执行。

本计划只设计和落地“危险 shell 命令执行前人工确认”。不要扩展到通用权限系统、长期授权、远程审批、沙箱执行器或重写 nanobot。

## 2. 最终目标行为

### 2.1 普通安全命令

示例：

```bash
ls -la
cat README.md
git status
python script.py
```

期望：保持现状，不弹框，仍通过 `ToolPolicy` 和 `SafetyGuardrails` 校验。

### 2.2 可 HITL 放行的危险命令

示例：

```bash
rm workspace/tmp.txt
rm -r workspace/generated_cache
del /q E:\GitHub\Repositories\Lobuddy\temp\old.txt
rmdir /s E:\GitHub\Repositories\Lobuddy\temp\old_dir
powershell -NoProfile -Command Remove-Item -LiteralPath "E:\GitHub\Repositories\Lobuddy\temp\a.txt" -Force
```

前提：

- 目标路径必须能被 `SafetyGuardrails.validate_path()` 判定为允许范围内。
- 目标必须是具体路径，不允许裸根目录、盘符根、用户目录根、通配符批量删除。
- 命令必须能被结构化解析出“这是删除/移除操作”和“影响路径”。

期望：

1. agent 生成工具调用。
2. hook 在真正执行前识别为 `HITL_REQUIRED`。
3. 主 UI 线程弹出确认框。
4. 用户点击“确认执行”后，仅当前这一次工具调用继续执行。
5. 用户取消、关闭或超时，命令不执行，任务返回清晰的取消说明。

### 2.3 永久阻断的命令

示例：

```bash
rm -rf /
rm -rf C:\
rm -rf %USERPROFILE%
del /s /q C:\*
format C:
mkfs.ext4 /dev/sda
shutdown -h now
reboot
powershell -enc ...
cmd /c "echo ok && rm -rf /"
python -c "..."
node -e "..."
```

期望：继续阻断，不弹 HITL，不给用户“确认后执行”的机会。

## 3. 任务边界

### 3.1 必须做

- 新增三态命令安全判定：`ALLOW`、`HITL_REQUIRED`、`DENY`。
- 保留现有 `ToolPolicy.is_command_dangerous()` 和 `ToolPolicy.validate_command()` 的兼容行为，避免破坏已有测试。
- 在 `_ToolTracker.before_execute_tools()` 中接入 HITL 判定和审批。
- UI 模式下从 worker 线程安全地请求主线程弹出确认框。
- 无审批 provider、用户拒绝、弹框超时、弹框关闭时，一律不执行命令。
- 将用户确认/拒绝结果写入审计日志或 SQLite 表，至少记录：时间、session/task、命令摘要、风险原因、影响路径、决策结果。
- 新增单元测试覆盖分类、guardrails、hook 审批通过/拒绝/无 provider。
- 保持所有危险命令日志的敏感信息脱敏，不保存 API key、bearer token、邮箱等敏感数据。

### 3.2 严禁做

- 严禁把 `rm -rf` 等危险命令简单从 `BLOCKED_COMMANDS` 中移除。
- 严禁让 `is_command_dangerous("rm -rf /")` 变成 `False`。
- 严禁允许命令链、重定向、管道、换行、多命令批处理通过 HITL。
- 严禁为 `format`、`mkfs`、`shutdown`、`reboot`、`poweroff`、fork bomb、encoded powershell 提供确认放行。
- 严禁加入“记住本次选择”“以后不再提示”“自动批准”。
- 严禁在 worker 线程直接创建或执行 Qt dialog。
- 严禁在 `app/` 中写业务判断逻辑；风险分类和审批协议必须放在 `core/`。
- 严禁绕过 `SafetyGuardrails.validate_path()` 做路径放行。
- 严禁在 UI 弹框中隐藏真实命令或只展示摘要，用户必须能看到将要执行的完整命令。
- 严禁把用户取消当作模型错误后继续重试同一个危险命令。

## 4. 建议架构

### 4.1 新增核心模型

新增文件：`core/safety/command_risk.py`

建议定义：

```python
from dataclasses import dataclass, field
from enum import Enum


class CommandRiskAction(str, Enum):
    ALLOW = "allow"
    HITL_REQUIRED = "hitl_required"
    DENY = "deny"


@dataclass(frozen=True)
class CommandRiskAssessment:
    action: CommandRiskAction
    command: str
    normalized_command: str
    command_name: str
    reason: str
    affected_paths: tuple[str, ...] = ()
    risk_tags: tuple[str, ...] = ()
```

职责：

- 只负责表达判定结果，不负责 UI。
- 不保存 provider、future、Qt 对象。
- 不直接执行命令。

### 4.2 扩展 ToolPolicy，但保持旧接口兼容

修改文件：`core/tools/tool_policy.py`

新增方法：

```python
def assess_command_risk(self, command: str) -> CommandRiskAssessment:
    ...
```

兼容要求：

- `is_command_dangerous()` 继续返回 bool。
- `validate_command()` 继续返回 `(bool, reason)`。
- 旧测试中断言危险命令为危险的用例不得改弱。

建议判定顺序：

1. 空命令、换行、多命令链、管道、重定向：`DENY`。
2. fork bomb、encoded powershell、inline interpreter：`DENY`。
3. `format`、`mkfs`、`shutdown`、`reboot`、`poweroff`：`DENY`。
4. unknown command：`DENY`。
5. 安全 allowlist 命令：`ALLOW`。
6. 删除类命令进入 `HITL_REQUIRED` 候选，但只做语法级候选，不在 `ToolPolicy` 里做路径最终放行。

删除类命令候选范围：

- POSIX：`rm`，支持 `-r`、`-R`、`-f`、`--recursive`、`--force`。
- Windows cmd：`del`、`erase`、`rd`、`rmdir`，支持 `/q`、`/s`、`/f`。
- PowerShell：`Remove-Item` 及常见别名 `rm`、`del`、`erase`、`rd`、`rmdir`，仅在能明确解析为 `powershell -Command ...` 或 `pwsh -Command ...` 时处理。

P0 不要求支持复杂 shell 语法。遇到 `&&`、`;`、`|`、`>`、`<`、换行、`$(...)`、反引号，一律 `DENY`。

### 4.3 在 SafetyGuardrails 中做路径级最终判定

修改文件：`core/safety/guardrails.py`

新增方法：

```python
def assess_shell_command(self, command: str, working_dir: str = "") -> CommandRiskAssessment:
    ...
```

职责：

- 调用 `ToolPolicy.assess_command_risk()`。
- 对 `HITL_REQUIRED` 的 `affected_paths` 逐个调用 `validate_path()`。
- 拒绝裸根目录、盘符根、home 根、workspace 根本身、通配符路径。
- 如存在 `working_dir`，继续调用 `validate_working_dir()`。

兼容要求：

- 保留 `validate_shell_command()`。
- `validate_shell_command()` 可以继续把 `HITL_REQUIRED` 当作 blocked 返回，用于旧调用方；新 `_ToolTracker` 必须改用 `assess_shell_command()`。

建议新增保护函数：

```python
def _is_protected_delete_target(path: Path) -> bool:
    ...
```

必须保护：

- `/`
- `C:\`、`D:\` 等盘符根。
- `Path.home()`。
- `workspace_path` 本身。
- `Desktop`、`Downloads`、`Documents` 等 extra allowed dir 本身。
- 带 `*`、`?`、`[`、`]` 的通配符路径。

## 5. HITL 审批协议

新增文件：`core/safety/hitl_approval.py`

建议定义：

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class HitlApprovalRequest:
    request_id: str
    session_id: str
    tool_name: str
    command: str
    working_dir: str
    reason: str
    affected_paths: tuple[str, ...]
    risk_tags: tuple[str, ...]
    created_at: datetime
    timeout_seconds: int


@dataclass(frozen=True)
class HitlApprovalDecision:
    request_id: str
    approved: bool
    decided_at: datetime
    reason: str = ""


class HitlApprovalProvider(Protocol):
    async def request_approval(self, request: HitlApprovalRequest) -> HitlApprovalDecision:
        ...
```

默认 provider：

- `DenyAllHitlApprovalProvider`：无 UI 或测试未注入 provider 时使用。
- 行为：直接返回 rejected，reason 为 `HITL approval provider is not available`。

## 6. UI 弹框设计

新增文件：`ui/hitl_confirmation_dialog.py`

弹框内容：

- 标题：`需要确认危险命令`
- 风险说明：例如 `该命令会删除文件或目录，执行后可能无法恢复。`
- 完整命令：等宽字体、多行、可选中复制。
- 工作目录：如有则展示。
- 影响路径列表：最多展示 10 条，超出显示 `...`。
- 按钮：
  - 默认按钮：`取消执行`
  - 危险按钮：`确认执行`

交互要求：

- `Esc`、关闭窗口、超时都等价于取消。
- `确认执行` 不得是默认按钮，用户按 Enter 不应误确认。
- 弹框必须在主 UI 线程显示。
- 弹框应设置父窗口，优先挂在 `TaskPanel` 或主宠物窗口上。
- P0 不加“输入确认文本”，只要求用户点击确认；P1 可再加二次输入。

## 7. 线程桥接设计

新增文件：`ui/hitl_approval_provider.py`

由于 `TaskQueue` 和 nanobot hook 在 `AsyncWorker` 的 asyncio loop 中运行，Qt dialog 必须通过 signal 切回主线程。

建议实现：

```python
class QtHitlApprovalProvider(QObject):
    approval_requested = Signal(object)

    async def request_approval(self, request: HitlApprovalRequest) -> HitlApprovalDecision:
        future = concurrent.futures.Future()
        self._pending[request.request_id] = future
        self.approval_requested.emit(request)
        try:
            return await asyncio.wrap_future(future)
        finally:
            self._pending.pop(request.request_id, None)

    @Slot(object)
    def _show_dialog(self, request: HitlApprovalRequest) -> None:
        ...
```

注意：

- provider 对象必须在主线程创建，且生命周期覆盖整个 app。
- `approval_requested` 连接到 `_show_dialog`，跨线程时 Qt 会自动 queued delivery。
- 不要在 worker 线程直接 `QMessageBox.exec()`。
- `request_approval()` 要支持 timeout；超时后设置 rejected，且 UI 如果稍后返回不得覆盖已完成 future。

## 8. 接入 NanobotAdapter

修改文件：`core/agent/nanobot_adapter.py`

### 8.1 NanobotAdapter 新增 setter

```python
def set_hitl_approval_provider(self, provider: HitlApprovalProvider | None) -> None:
    self._hitl_approval_provider = provider
```

初始化默认值：

```python
self._hitl_approval_provider = None
```

### 8.2 _ToolTracker 注入 provider

`_ToolTracker.__init__()` 新增：

```python
hitl_approval_provider: HitlApprovalProvider | None = None
session_id: str = ""
hitl_timeout_seconds: int = 120
```

在创建 tracker 时传入：

```python
tracker = _ToolTracker(
    guardrails=self.guardrails,
    guardrails_enabled=self.settings.guardrails_enabled,
    block_dream_commands=self.settings.memory_block_dream_commands,
    hitl_approval_provider=self._hitl_approval_provider,
    session_id=session_key,
    hitl_timeout_seconds=self.settings.hitl_approval_timeout_seconds,
)
```

### 8.3 before_execute_tools 改造

当前逻辑会遍历参数字段：

```python
("command", self.guardrails.validate_shell_command)
```

需要对 `command` 单独处理：

1. 如果 `guardrails_enabled=False`，保持当前设置语义，但 HITL 仍建议生效。P0 推荐：危险命令 HITL 不受 `guardrails_enabled` 关闭影响，只要是 `exec/shell` 的 `command` 字段就必须评估。
2. 调用 `self.guardrails.assess_shell_command(command, working_dir=args.get("working_dir", ""))`。
3. `ALLOW`：继续。
4. `DENY`：raise `RuntimeError("Dangerous command blocked: ...")`。
5. `HITL_REQUIRED`：构造 `HitlApprovalRequest`，调用 provider。
6. provider 批准：继续。
7. provider 拒绝/超时/异常：raise `HumanApprovalDenied` 或 `RuntimeError("Dangerous command cancelled by human approval")`。

建议新增异常：

```python
class HumanApprovalDenied(RuntimeError):
    pass
```

在 `_handle_error()` 中识别该异常，返回用户友好的 summary：

```text
已取消执行危险命令。命令没有运行。
```

### 8.4 一次只允许一个 HITL 命令

P0 建议：如果同一轮 `context.tool_calls` 中出现多个 `HITL_REQUIRED` 命令，全部阻断，并提示模型一次只能提交一个危险命令。原因是多命令批量确认容易误操作。

## 9. app/main.py 接线

修改文件：`app/main.py`

在创建 `TaskManager(settings)` 后、任务开始前：

```python
from ui.hitl_approval_provider import QtHitlApprovalProvider

hitl_provider = QtHitlApprovalProvider(parent_window=task_panel)
task_manager.adapter.set_hitl_approval_provider(hitl_provider)
```

设置保存后无需重建 provider，但如果 settings 中的 timeout 改变，tracker 每次创建时读取最新 settings 即可。

如果存在 CLI/health 模式，不接 provider；默认 DenyAll 行为保证危险命令不会在无 UI 时执行。

## 10. 配置项

修改文件：

- `core/config/settings.py`
- `app/config.py`
- `.env.example`

新增配置：

```python
hitl_approval_timeout_seconds: int = Field(
    default=120,
    ge=10,
    le=600,
    description="Timeout for human approval dialog before rejecting dangerous commands",
)
```

P0 不新增 `hitl_enabled` 开关。危险命令确认是安全基线，不应能在 UI 中一键关闭。

## 11. 审计记录

新增文件：`core/storage/hitl_approval_repo.py`

修改文件：`core/storage/db.py`

新增表：

```sql
CREATE TABLE IF NOT EXISTS hitl_approval_log (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    command_hash TEXT NOT NULL,
    command_preview TEXT NOT NULL,
    working_dir TEXT,
    affected_paths_json TEXT NOT NULL,
    risk_tags_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    decision TEXT NOT NULL,
    decision_reason TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
```

记录原则：

- `command_preview` 最多 500 字符，并经过现有敏感信息脱敏。
- 完整命令不入库，避免泄露 token 或私密路径过多；可用 `command_hash` 做关联。
- `affected_paths_json` 最多保存前 10 条。
- 审计失败不得导致已批准命令被跳过，但必须写 debug/security log。

## 12. 测试计划

### 12.1 ToolPolicy 分类测试

新增：`tests/test_hitl_command_risk.py`

必须覆盖：

- `ls -la` => `ALLOW`
- `rm temp.txt` => `HITL_REQUIRED`
- `rm -r temp_dir` => `HITL_REQUIRED`
- `rm -rf /` => `DENY`
- `rm -rf C:\` => `DENY`
- `rm *.tmp` => `DENY`
- `del /q temp.txt` => `HITL_REQUIRED`
- `rmdir /s temp_dir` => `HITL_REQUIRED`
- `powershell -NoProfile -Command Remove-Item -LiteralPath temp.txt -Force` => `HITL_REQUIRED`
- `powershell -enc abc` => `DENY`
- `echo ok && rm temp.txt` => `DENY`
- `python -c "print(1)"` => `DENY`

### 12.2 SafetyGuardrails 路径测试

新增或扩展：`tests/test_tool_policy.py`

必须覆盖：

- workspace 内具体文件删除 => `HITL_REQUIRED`
- workspace 外路径删除 => `DENY`
- workspace 根目录本身 => `DENY`
- home 根目录本身 => `DENY`
- allowed extra dir 中具体文件 => `HITL_REQUIRED`
- 通配符路径 => `DENY`
- UNC、ADS、drive-relative 路径继续 `DENY`

### 12.3 _ToolTracker 审批测试

新增：`tests/test_hitl_tool_tracker.py`

使用 fake provider：

- provider approve：`before_execute_tools()` 不抛错，工具留在队列中。
- provider reject：抛 `HumanApprovalDenied`，命令未执行。
- provider timeout/异常：抛 `HumanApprovalDenied` 或安全错误。
- 无 provider：拒绝。
- 同一轮两个 HITL 命令：拒绝。
- `guardrails_enabled=False` 时，危险命令仍然触发 HITL。

### 12.4 UI provider 测试

如果当前测试环境没有 `pytest-qt`，P0 不强制做真实 dialog 自动化。至少增加轻量测试：

- provider timeout 返回 rejected。
- late decision 不覆盖已超时 future。
- `QtHitlApprovalProvider` 可以 import，不依赖 nanobot。

### 12.5 回归测试

必须跑：

```bash
pytest tests/test_tool_policy.py tests/test_integration_phase1.py tests/test_tool_policy_54.py -q
pytest tests/test_execution_governance_hook.py tests/test_nanobot_adapter_execution_governance.py -q
pytest tests/test_hitl_command_risk.py tests/test_hitl_tool_tracker.py -q
```

如果时间允许，再跑：

```bash
pytest tests/ -q
```

## 13. 实施步骤

### P0-1：新增命令风险模型与分类

改动：

- 新增 `core/safety/command_risk.py`
- 修改 `core/tools/tool_policy.py`
- 新增 `tests/test_hitl_command_risk.py`

验收：

- 新增分类测试通过。
- 旧 `test_tool_policy.py`、`test_tool_policy_54.py` 不需要改弱。

### P0-2：Guardrails 接入路径级 HITL 判定

改动：

- 修改 `core/safety/guardrails.py`
- 扩展安全测试。

验收：

- workspace 内具体删除命令进入 `HITL_REQUIRED`。
- 根目录、workspace 根、通配符、workspace 外路径全部 `DENY`。
- 旧 `validate_shell_command()` 对危险命令仍返回 blocked 字符串。

### P0-3：新增 HITL 审批协议与默认拒绝 provider

改动：

- 新增 `core/safety/hitl_approval.py`

验收：

- 无 UI 注入时危险命令默认拒绝。
- provider 接口为 async，不能依赖 Qt。

### P0-4：改造 _ToolTracker

改动：

- 修改 `core/agent/nanobot_adapter.py`
- 注入 provider、session_id、timeout。
- 新增或扩展测试。

验收：

- approve 后放行当前工具调用。
- reject/timeout/无 provider 不执行。
- 普通安全命令不弹框。
- 永久阻断命令不弹框。

### P0-5：实现 Qt 弹框与主线程 provider

改动：

- 新增 `ui/hitl_confirmation_dialog.py`
- 新增 `ui/hitl_approval_provider.py`
- 修改 `app/main.py` 接线。

验收：

- 从真实 UI 发起 `rm temp.txt` 类任务时，弹框出现在主线程。
- 点击取消：命令不执行，聊天区显示已取消。
- 点击确认：命令执行一次。
- 关闭弹框：命令不执行。

### P0-6：审计记录

改动：

- 修改 `core/storage/db.py`
- 新增 `core/storage/hitl_approval_repo.py`
- 在 provider 或 `_ToolTracker` 中记录审批结果。

验收：

- 批准、拒绝、超时都有记录。
- command preview 脱敏且截断。
- DB 写失败不导致 UI 卡死。

### P0-7：配置与文档

改动：

- `core/config/settings.py`
- `app/config.py`
- `.env.example`

验收：

- `hitl_approval_timeout_seconds` 可从环境变量和 DB override 读取。
- 默认值 120 秒。
- 不新增关闭 HITL 的 UI 开关。

## 14. 验收清单

- `rm -rf /`：直接阻断，不弹框。
- `format C:`：直接阻断，不弹框。
- `powershell -enc ...`：直接阻断，不弹框。
- `rm E:\GitHub\Repositories\Lobuddy\temp\a.txt`：弹框。
- 点击确认后：文件被删除，审计记录为 approved。
- 点击取消后：文件仍存在，审计记录为 rejected/cancelled。
- 弹框超时后：文件仍存在，审计记录为 timeout。
- `guardrails_enabled=False` 时：危险删除命令仍然需要 HITL。
- shell disabled 时：`exec/shell` 仍不可用，HITL 不应绕过 shell 总开关。
- 旧安全测试不降级，不允许为了通过测试删除旧断言。

## 15. 非目标范围

以下内容不要在本次实现：

- 不实现长期授权、按目录记忆授权、自动批准。
- 不实现远程审批、手机审批、多人审批。
- 不重写 nanobot 工具执行器。
- 不实现文件回收站/撤销删除。P1 可以考虑“删除改走回收站”，但 P0 不做。
- 不扩展到所有文件写入工具，只处理 shell/exec command。
- 不做完整 shell AST 解释器；复杂语法默认拒绝。
- 不修改 `lib/nanobot/` 子模块。

## 16. 给 opencode 的执行提示

请按 P0-1 到 P0-7 顺序实施。每完成一个 P0 阶段先跑对应最小测试，再进入下一阶段。不要先做 UI，再补安全分类；安全分类是整条链路的基础。

实现时遵守 Lobuddy 现有约定：

- 绝对导入。
- line length 100。
- 业务逻辑放 `core/`，UI 只负责展示和用户输入。
- 不绕过 `nanobot_adapter.py`。
- 不把 Qt dialog 放进 `core/safety/` 或 `core/tools/`。
- 不保存完整敏感命令。

最终提交前，请至少提供：

1. 修改文件列表。
2. 已跑测试命令和结果。
3. 三个手工验证结果：确认执行、取消执行、永久阻断。
