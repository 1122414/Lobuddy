# Lobuddy 5.4 执行能力升级方案：从“会调用工具”到“会收敛执行”

制定时间：2026-05-04  
目标版本：5.4.x  
涉及范围：`core/agent/`、`core/agent/tools/`、`core/safety/`、`core/tools/`、`core/config/`、`tests/`

## 1. 触发问题

用户请求：

> 帮我打开桌面的洛克王国：世界

实际日志显示，agent 先 `dir "%USERPROFILE%\Desktop" /b`，随后不断扩大搜索：

- 桌面递归搜索：`where /R "%USERPROFILE%\Desktop" 洛克* ...`
- 开始菜单递归搜索：`dir /s /b "%USERPROFILE%\AppData\Roaming\Microsoft\Windows\Start Menu\*洛克*"...`
- 全量 `Program Files` 搜索：`where /R "C:\Program Files" 洛克* ...`
- AppData/Tencent 多目录递归搜索

这说明当前执行系统的问题不是“没有工具”，而是缺少任务级执行治理：

1. 没有把“打开桌面上的应用/快捷方式”识别为一个受限本地动作。
2. 没有先构造候选对象，再执行打开；而是把查找交给模型自由写 shell。
3. 没有工具预算、目录预算、递归预算和失败停止规则。
4. 没有把 Windows 快捷方式、开始菜单、桌面文件这类高频动作封装为安全工具。
5. 当前 guardrails 主要挡危险命令，不负责判断“这个命令是否适合当前任务”。
6. token 统计偏事后记录，不能在执行中阻止长链路试错。

5.4 的目标是让 Lobuddy 对常见桌面执行任务具备确定性、可审计、可停止的能力。

## 2. 设计原则

### 2.1 执行优先级

执行请求按以下顺序处理：

1. 确定性专用工具。
2. 受限目录枚举。
3. 用户确认或澄清。
4. 通用 shell fallback。

只要存在专用工具，就不允许模型直接写通用 shell 去全盘搜索。

### 2.2 失败要早停

对本地查找类任务，必须有明确边界：

- 最多搜索 3 个来源：桌面、OneDrive 桌面、开始菜单。
- 默认不递归 `Program Files`、`AppData`、整盘目录。
- 单次本地动作最多 3 轮工具调用。
- 找到 2 个以上高置信候选时，不继续搜索，向用户确认。
- 找不到时返回“没找到桌面/开始菜单候选”，而不是继续扩大搜索。

### 2.3 工具输出必须小

专用工具返回结构化候选，不返回大段 `dir /s` 输出。

候选字段：

- `display_name`
- `path`
- `kind`: `shortcut | url | executable | folder | document`
- `source`: `desktop | onedrive_desktop | start_menu_user | start_menu_global`
- `confidence`
- `openable`
- `reason`

默认最多返回 10 个候选，单项路径和说明截断。

### 2.4 shell 是最后手段

`exec` 仍可存在，但本地动作必须优先经过更窄的工具：

- `local_app_resolve`
- `local_open`
- `local_list_desktop`
- 后续可扩展 `local_file_search`

通用 shell 不应成为“打开桌面应用”的第一选择。

## 3. 当前系统可复用基础

### 3.1 已有基础

- `NanobotAdapter.run_task()` 已经是 Lobuddy 到 nanobot 的唯一边界。
- `_ToolTracker.before_execute_tools()` 已能检查 tool 参数类型和调用 guardrails。
- `SafetyGuardrails.validate_shell_command()` 已接入 `ToolPolicy`。
- `AgentHookContext` 已暴露：
  - `iteration`
  - `tool_calls`
  - `tool_results`
  - `tool_events`
  - `usage`
  - `stop_reason`
- `NanobotGateway` 已封装工具注册/注销。
- `Settings` 已有 `nanobot_max_iterations`、`task_timeout`、`guardrails_enabled`。

### 3.2 缺口

- `_ToolTracker` 只做安全校验，不做任务适配和预算治理。
- `ToolPolicy` 校验单条命令，不知道用户原始意图。
- `ExecTool` 输出最多 10,000 字符，对递归搜索仍然过大。
- 缺少本地 Windows 桌面/开始菜单专用工具。
- 缺少工具调用轨迹持久化，复盘只能看日志。
- 缺少“相同目的重复搜索”的阻断规则。

## 4. 目标行为示例

### 4.1 “打开桌面的洛克王国：世界”

期望流程：

1. `ExecutionIntentRouter` 识别为 `LOCAL_OPEN_TARGET`。
2. 注入短系统提示：这是打开本地桌面对象任务，必须优先用 `local_app_resolve`。
3. 注册 `local_app_resolve` 和 `local_open`。
4. 模型调用：

```json
{"target": "洛克王国：世界", "sources": ["desktop", "onedrive_desktop", "start_menu"], "limit": 5}
```

5. 工具只检查：
   - `~/Desktop`
   - `~/OneDrive/Desktop`
   - 用户开始菜单
   - 全局开始菜单
6. 若找到唯一高置信候选：

```json
{"path": "...\\洛克王国：世界.lnk", "mode": "open"}
```

7. 若找不到，直接回复：

> 我在桌面和开始菜单里没找到“洛克王国：世界”的快捷方式。你可以把快捷方式拖到桌面，或告诉我安装目录，我再帮你打开。

禁止行为：

- 禁止递归搜索 `C:\Program Files`。
- 禁止递归搜索整个 `AppData`。
- 禁止用 `where /R` 查中文通配符。
- 禁止把多个命令用 `&` 拼接。

## 5. 方案总览

新增 6 个组件：

| 组件 | 文件 | 作用 |
| --- | --- | --- |
| `ExecutionIntentRouter` | `core/agent/execution_intent.py` | 从用户原文识别高频执行意图 |
| `ExecutionBudget` | `core/agent/execution_budget.py` | 限制工具轮数、递归搜索、目录范围、输出预算 |
| `ExecutionGovernanceHook` | `core/agent/execution_hook.py` | 在 nanobot hook 层拦截不合适的工具调用 |
| `LocalAppResolveTool` | `core/agent/tools/local_app_resolve_tool.py` | 受控查找桌面/开始菜单候选 |
| `LocalOpenTool` | `core/agent/tools/local_open_tool.py` | 打开已验证的本地候选 |
| `ExecutionTraceRepository` | `core/storage/execution_trace_repository.py` | 保存执行轨迹，用于复盘和测试 |

不直接改 nanobot 核心循环，先在 Lobuddy adapter 层完成治理。

## 6. 模块设计

### 6.1 ExecutionIntentRouter

职责：把用户原始 prompt 映射为执行意图。

文件：`core/agent/execution_intent.py`

数据结构：

```python
from enum import StrEnum
from pydantic import BaseModel


class ExecutionIntent(StrEnum):
    GENERAL_CHAT = "general_chat"
    LOCAL_OPEN_TARGET = "local_open_target"
    LOCAL_FIND_FILE = "local_find_file"
    LOCAL_SYSTEM_ACTION = "local_system_action"
    MEMORY_QUESTION = "memory_question"


class ExecutionRoute(BaseModel):
    intent: ExecutionIntent
    target: str = ""
    confidence: float = 0.0
    requires_tools: bool = False
    preferred_tools: list[str] = []
    forbidden_tools: list[str] = []
    reason: str = ""
```

首批规则：

- `打开|启动|运行|帮我开` + `桌面|快捷方式|应用|游戏` -> `LOCAL_OPEN_TARGET`
- `在哪|找一下|搜索文件` -> `LOCAL_FIND_FILE`
- `我喜欢|我是谁|我之前说过` 问句 -> `MEMORY_QUESTION`

针对本次问题：

```python
route = ExecutionRoute(
    intent=ExecutionIntent.LOCAL_OPEN_TARGET,
    target="洛克王国：世界",
    confidence=0.9,
    requires_tools=True,
    preferred_tools=["local_app_resolve", "local_open"],
    forbidden_tools=["exec"],
    reason="User wants to open a desktop game shortcut",
)
```

注意：`forbidden_tools=["exec"]` 不是永久禁用，而是在有专用工具可用时禁止第一阶段使用。

### 6.2 LocalAppResolveTool

职责：用 Python 结构化枚举固定目录，不让模型写 shell 搜索。

文件：`core/agent/tools/local_app_resolve_tool.py`

参数：

```json
{
  "target": "洛克王国：世界",
  "sources": ["desktop", "onedrive_desktop", "start_menu"],
  "limit": 5
}
```

搜索来源：

| source | 路径 |
| --- | --- |
| `desktop` | `Path.home() / "Desktop"` |
| `onedrive_desktop` | `Path.home() / "OneDrive" / "Desktop"` |
| `start_menu_user` | `AppData/Roaming/Microsoft/Windows/Start Menu/Programs` |
| `start_menu_global` | `C:/ProgramData/Microsoft/Windows/Start Menu/Programs` |

默认匹配扩展名：

- `.lnk`
- `.url`
- `.exe`
- `.bat` 禁用打开，仅返回不可直接打开
- 目录可返回，但默认不自动打开

匹配策略：

1. 标准化中文全角冒号、空格、大小写。
2. exact name > startswith > contains > pinyin 暂不做。
3. `洛克王国：世界` 可匹配：
   - `洛克王国：世界.lnk`
   - `洛克王国世界.lnk`
   - `洛克王国.lnk`
4. 每个 source 最多枚举 200 个文件。
5. 开始菜单最多递归深度 3。
6. 不枚举 `Program Files`、`AppData/Local`、整盘。

返回示例：

```json
{
  "query": "洛克王国：世界",
  "candidates": [
    {
      "display_name": "洛克王国：世界",
      "path": "C:\\Users\\Lenovo\\Desktop\\洛克王国：世界.lnk",
      "kind": "shortcut",
      "source": "desktop",
      "confidence": 0.98,
      "openable": true,
      "reason": "exact normalized filename match"
    }
  ],
  "searched_sources": ["desktop", "onedrive_desktop", "start_menu_user", "start_menu_global"],
  "truncated": false
}
```

安全要求：

- 所有候选 path 必须通过 `SafetyGuardrails.validate_path()`。
- 允许读取桌面和开始菜单，但不读取文件内容。
- 不解析 `.lnk` 目标路径，先只打开快捷方式本身。
- 返回结果前做敏感信息截断。

### 6.3 LocalOpenTool

职责：打开一个已由 resolver 返回、且 guardrails 通过的本地对象。

文件：`core/agent/tools/local_open_tool.py`

参数：

```json
{
  "path": "C:\\Users\\Lenovo\\Desktop\\洛克王国：世界.lnk",
  "source": "local_app_resolve"
}
```

实现策略：

- Windows：`os.startfile(path)`。
- macOS/Linux：后续版本再接 `open` / `xdg-open`。
- 初版只支持 Windows，因为当前用户环境是 Windows。

安全要求：

- `path` 必须来自本轮 `LocalAppResolveTool` 的候选缓存，不能让模型手写任意 path。
- 再次调用 `SafetyGuardrails.validate_path(path)`。
- 默认只打开 `.lnk`、`.url`、`.exe`、常见文档。
- `.bat`、`.cmd`、`.ps1` 不自动打开。

返回：

```json
{"opened": true, "path": "...", "message": "opened"}
```

失败返回：

```json
{"opened": false, "reason": "path_not_from_resolver_candidates"}
```

### 6.4 ExecutionBudget

职责：让工具调用有任务级预算。

文件：`core/agent/execution_budget.py`

配置项：

```python
execution_governance_enabled: bool = True
execution_max_tool_calls_per_task: int = 6
execution_max_local_lookup_calls: int = 2
execution_max_shell_calls_per_task: int = 2
execution_block_shell_for_local_open: bool = True
execution_max_tool_result_chars: int = 3000
execution_trace_enabled: bool = True
```

本地打开任务默认预算：

| 项 | 限制 |
| --- | --- |
| 总工具调用 | 3 |
| resolver 调用 | 1 |
| open 调用 | 1 |
| exec 调用 | 0，除非专用工具不可用 |
| 单次工具输出 | 1500 chars |
| 总任务超时 | 沿用 `task_timeout` |

本地查找文件任务默认预算：

| 项 | 限制 |
| --- | --- |
| 总工具调用 | 5 |
| 搜索目录 | 用户指定目录或常见用户目录 |
| 递归深度 | 默认 2 |
| exec 调用 | 0，后续由 `local_file_search` 承担 |

### 6.5 ExecutionGovernanceHook

职责：在 `_ToolTracker` 之外，按执行意图治理工具调用。

文件：`core/agent/execution_hook.py`

接入点：

```python
tracker = _ToolTracker(...)
execution_hook = ExecutionGovernanceHook(route, budget, trace_repo, guardrails)
result = await bot.run(prompt, session_key=session_key, hooks=[tracker, execution_hook])
```

首批规则：

1. `LOCAL_OPEN_TARGET` 的第 0 轮禁止 `exec`。
2. 如果调用 `exec` 且 command 包含以下模式，直接阻断：
   - `where /R`
   - `dir /s`
   - `Get-ChildItem -Recurse`
   - `C:\Program Files`
   - `C:\Users\*\AppData`
3. 如果连续 2 次调用同类搜索工具且无结果，停止并要求模型总结失败。
4. 如果工具调用数超过预算，抛出可恢复错误：

```text
Execution budget exceeded. Stop searching and provide a concise result to the user.
```

5. 如果 `local_app_resolve` 返回唯一高置信候选，而模型继续搜索，阻断下一次搜索并提示使用 `local_open`。

### 6.6 Prompt 注入

只对执行任务注入极短系统提示，避免继续烧 token。

示例：

```text
Lobuddy execution route: LOCAL_OPEN_TARGET.
Use local_app_resolve first. If one high-confidence openable candidate is found, use local_open.
Do not use exec for recursive search. Do not search Program Files or AppData unless the user provides an install path.
If no candidate is found in desktop/start menu, stop and report that.
```

接入位置：`NanobotAdapter.run_task()` 中 memory injection 之后、guardrail preflight 之前。

### 6.7 ExecutionTraceRepository

职责：保存轻量执行轨迹，便于定位“为什么又乱搜了”。

文件：`core/storage/execution_trace_repository.py`

SQLite 表：

```sql
CREATE TABLE IF NOT EXISTS execution_traces (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    intent TEXT NOT NULL,
    target TEXT,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_summary TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0
);
```

记录策略：

- 不保存完整工具输出。
- path 可保存，但要走敏感信息过滤。
- command 保存前做截断，最大 500 chars。
- token 使用从 `AgentHookContext.usage` 聚合。

UI 初版不展示，只用于日志和测试。

## 7. ToolPolicy 与 Guardrails 调整

### 7.1 修复命令链检测盲区

当前日志中出现：

```cmd
where /R "...Desktop" 洛克* 2>nul & dir /s /b "...Desktop\*洛克*" 2>nul
```

5.4 需要新增 regression test，确保它被阻断。

测试：

```python
def test_blocks_windows_ampersand_chaining_with_redirection():
    policy = ToolPolicy()
    command = 'where /R "%USERPROFILE%\\Desktop" 洛克* 2>nul & dir /s /b "%USERPROFILE%\\Desktop\\*洛克*" 2>nul'
    allowed, reason = policy.validate_command(command)
    assert allowed is False
```

如果现有 `_CHAINING_PATTERN` 已能挡住，则测试锁定行为；如果挡不住，修正 pattern。

### 7.2 增加“不适合任务”的阻断

`ToolPolicy` 不直接持有用户意图，因此不要把任务级规则塞进 `ToolPolicy`。

任务级规则放到 `ExecutionGovernanceHook`：

- `where /R`：安全上未必危险，但对本地打开任务不合适。
- `dir /s`：安全上未必危险，但会烧 token 和时间。
- `Program Files`：除非用户明确给安装路径，否则不适合默认搜索。

## 8. Adapter 接入步骤

### Phase 1：只加治理，不改 nanobot

1. 新增 `ExecutionIntentRouter`。
2. 新增 `ExecutionBudget`。
3. 新增 `ExecutionGovernanceHook`。
4. 在 `NanobotAdapter.run_task()` 中：
   - 计算 `route = ExecutionIntentRouter().route(original_prompt)`
   - 若 `route.intent == LOCAL_OPEN_TARGET`，注册 `LocalAppResolveTool` 和 `LocalOpenTool`
   - 注入短 execution prompt
   - hooks 从 `[tracker]` 改为 `[tracker, execution_hook]`
5. cleanup 中注销新增工具。

### Phase 2：专用工具落地

1. 实现 `LocalAppResolveTool`。
2. 实现 `LocalOpenTool`。
3. 为 `LocalOpenTool` 增加本轮候选缓存。
4. 将 resolver/open 的返回结构固定为 JSON 字符串。

### Phase 3：轨迹与测试

1. 新增 `ExecutionTraceRepository`。
2. `ExecutionGovernanceHook.after_iteration()` 记录工具名、参数摘要、状态、usage。
3. 增加 functional smoke：

```bash
python tests/run_54_execution_tests.py
```

### Phase 4：灰度启用

默认配置：

```env
EXECUTION_GOVERNANCE_ENABLED=true
EXECUTION_LOCAL_TOOLS_ENABLED=true
EXECUTION_TRACE_ENABLED=true
EXECUTION_BLOCK_SHELL_FOR_LOCAL_OPEN=true
```

如果线上发现误伤，可只关闭 `EXECUTION_BLOCK_SHELL_FOR_LOCAL_OPEN`，保留 trace。

## 9. 测试计划

### 9.1 Intent Router

文件：`tests/test_execution_intent.py`

用例：

- `帮我打开桌面的洛克王国：世界` -> `LOCAL_OPEN_TARGET`
- `打开微信` -> `LOCAL_OPEN_TARGET`
- `帮我找一下 report.docx` -> `LOCAL_FIND_FILE`
- `我喜欢玩什么游戏？` -> `MEMORY_QUESTION`
- `讲个笑话` -> `GENERAL_CHAT`

### 9.2 LocalAppResolveTool

文件：`tests/test_local_app_resolve_tool.py`

用例：

- 桌面存在 exact `.lnk`，返回 confidence >= 0.95。
- 全角冒号和无冒号文件名可匹配。
- 返回候选不超过 limit。
- 不枚举 `Program Files`。
- 开始菜单递归深度不超过 3。
- path 不通过 guardrails 时过滤。

### 9.3 LocalOpenTool

文件：`tests/test_local_open_tool.py`

用例：

- 只能打开 resolver 返回过的 path。
- `.bat/.cmd/.ps1` 被拒绝。
- `os.startfile` 用 monkeypatch 验证调用，不真的打开程序。
- guardrails 二次校验失败时拒绝。

### 9.4 ExecutionGovernanceHook

文件：`tests/test_execution_governance_hook.py`

用例：

- `LOCAL_OPEN_TARGET` 第 0 轮调用 `exec` 被拒绝。
- `where /R` 被拒绝。
- `dir /s` 被拒绝。
- `Get-ChildItem -Recurse` 被拒绝。
- 超过工具预算被拒绝。
- resolver 已有唯一高置信候选时继续搜索被拒绝。

### 9.5 Adapter 集成

文件：`tests/test_nanobot_adapter_execution_governance.py`

用例：

- route 为 `LOCAL_OPEN_TARGET` 时注册 `local_app_resolve/local_open`。
- cleanup 后工具注销。
- 注入 execution prompt。
- hooks 同时包含 `_ToolTracker` 和 `ExecutionGovernanceHook`。
- 配置关闭时行为回到原路径。

### 9.6 Regression：本次问题

文件：`tests/test_54_execution_regression.py`

核心断言：

```python
def test_open_desktop_game_does_not_use_recursive_shell_search():
    prompt = "帮我打开桌面的洛克王国：世界"
    route = ExecutionIntentRouter().route(prompt)
    assert route.intent == ExecutionIntent.LOCAL_OPEN_TARGET
    assert "exec" in route.forbidden_tools
```

```python
def test_local_open_blocks_program_files_search_command():
    hook = ExecutionGovernanceHook(route=local_open_route(), budget=ExecutionBudget.local_open())
    tc = fake_tool_call("exec", {"command": 'where /R "C:\\Program Files" 洛克*'})
    with pytest.raises(RuntimeError):
        asyncio.run(hook.before_execute_tools(fake_context([tc])))
```

## 10. 验收标准

本方案完成后，以下标准必须满足：

1. 对“打开桌面的 X”，首轮工具必须是 `local_app_resolve`，不能是 `exec`。
2. 对“打开桌面的洛克王国：世界”，不会出现 `where /R`、`dir /s`、`Program Files`、`AppData` 搜索。
3. 找不到候选时，最多 1 次 resolver 调用后停止。
4. 找到唯一高置信候选时，下一步只能 `local_open` 或回复用户。
5. 工具输出单次不超过 1500 chars。
6. 执行 trace 能看到每次工具调用、阻断原因和 token usage 摘要。
7. 关闭 `EXECUTION_GOVERNANCE_ENABLED` 后不影响旧流程。

## 11. 实施顺序

建议按以下 commit 拆分：

1. `新增执行意图路由与预算模型`
2. `新增本地应用解析工具`
3. `新增受控本地打开工具`
4. `接入执行治理Hook`
5. `补充执行轨迹和回归测试`

优先级：

- P0：router、budget、hook 阻断 `LOCAL_OPEN_TARGET` 的递归 shell。
- P0：`LocalAppResolveTool` 支持桌面和开始菜单。
- P1：`LocalOpenTool` 受控打开。
- P1：trace repository。
- P2：UI 展示执行轨迹。
- P2：更泛化的 `local_file_search`。

## 12. 风险与降级

| 风险 | 影响 | 降级 |
| --- | --- | --- |
| 误判普通聊天为执行任务 | 可能阻止模型回答 | router confidence < 0.75 时不启用治理 |
| 专用工具找不到真实安装位置 | 不能自动打开 | 返回明确失败，不继续全盘搜 |
| `os.startfile` 在测试环境不可用 | 测试失败 | monkeypatch，生产代码判断 `hasattr(os, "startfile")` |
| 开始菜单路径不存在 | resolver 返回空 | 记录 searched_sources，不报异常 |
| 用户明确要求全盘搜索 | 默认阻断 | 需要二次确认后使用更高预算的 `local_file_search` |

## 13. 后续扩展

5.4.x 先解决桌面/开始菜单打开。后续再扩展：

- `local_file_search`：受限文件查找，支持用户指定目录。
- `local_process_tool`：查询/关闭用户指定进程，但必须确认。
- `app_registry_resolve`：读取 Windows 注册表卸载项/应用路径，需额外安全评估。
- `execution_trace_viewer`：在调试窗口展示工具轨迹。
- `skill_result_feedback`：把执行成功/失败反馈到 SkillManager。

## 14. 最小可行版本

如果只做最小修复，范围如下：

1. 新增 `ExecutionIntentRouter`。
2. 新增 `ExecutionGovernanceHook`，只拦截：
   - `where /R`
   - `dir /s`
   - `Get-ChildItem -Recurse`
   - `Program Files`
   - `AppData`
3. 新增 `LocalAppResolveTool`，只查桌面和开始菜单。
4. 在 `LOCAL_OPEN_TARGET` 中禁用首轮 `exec`。
5. 增加本次问题的 regression test。

这个 MVP 可以在不改 UI、不改 DB、不改 nanobot 的情况下完成，能立刻停止“越搜越大、越搜越贵”的失败模式。

