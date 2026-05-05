# Lobuddy 5.4 执行能力补完计划：修复本地打开链路未闭环问题

制定时间：2026-05-04  
来源：5.4 execution capability review findings  
目标：把已实现的 execution governance 从“结构存在”补到“真实可用、可测试、可审计”

## 1. 当前结论

opencode 已经完成了 5.4 执行能力升级的主体结构：

- `ExecutionIntentRouter`
- `ExecutionBudget`
- `ExecutionGovernanceHook`
- `LocalAppResolveTool`
- `LocalOpenTool`
- `ExecutionTraceRepository`
- adapter 中的工具注册和 execution prompt 注入

但目前不能认为完成。主要原因是关键链路未闭合：

1. 本地工具直接依赖 `nanobot`，导致当前测试环境收集失败。
2. `LocalOpenTool` 注册时拿不到 resolver 后续产生的候选，真实打开会被拒绝。
3. 中文目标提取不准，会把“洛克王国：世界”提成“的洛克王国：世界”，把“微信”提成“信”。
4. 高置信候选识别和 execution trace 只是半成品，没有真正接入 hook/adapter。

本计划只补齐上述闭环，不扩大到 UI、注册表扫描、全盘文件搜索或技能反馈系统。

## 2. 修复原则

- 优先保证测试可收集、可局部运行。
- 优先保证“帮我打开桌面的洛克王国：世界”这个原始场景可收敛。
- 不把本地打开任务退回给通用 `exec`。
- 不搜索 `Program Files`、`AppData`、整盘目录。
- 不让模型手写 path 后直接打开。
- trace 只保存摘要，不保存完整大输出。

## 3. P0 修复 1：本地工具提供 nanobot fallback

### 问题

文件：

- `core/agent/tools/local_app_resolve_tool.py`
- `core/agent/tools/local_open_tool.py`

当前直接导入：

```python
from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import ...
```

当前环境未安装 editable nanobot 时，测试收集直接失败：

```text
ModuleNotFoundError: No module named 'nanobot'
```

即使设置 `PYTHONPATH=lib/nanobot`，仍会被 `tiktoken` 等依赖拖住。

### 修复方案

参考 `core/agent/tools/session_search_tool.py` 的 fallback 写法：

- `try` 导入 nanobot tool 基类和 schema。
- `except Exception` 时定义最小 `Tool` fallback。
- fallback 的 `tool_parameters()` 返回 identity decorator。
- fallback 的 schema helper 返回轻量占位对象。

`local_app_resolve_tool.py` 需要 fallback：

- `Tool`
- `tool_parameters`
- `tool_parameters_schema`
- `StringSchema`
- `IntegerSchema`
- `ArraySchema`

`local_open_tool.py` 需要 fallback：

- `Tool`
- `tool_parameters`
- `tool_parameters_schema`
- `StringSchema`

### 验收

以下命令必须不再收集失败：

```bash
pytest tests/test_54_execution_regression.py -q
pytest tests/test_execution_intent.py tests/test_execution_governance_hook.py tests/test_tool_policy_54.py -q
```

新增断言：

```python
def test_local_tools_import_without_nanobot_installed():
    from core.agent.tools.local_app_resolve_tool import LocalAppResolveTool
    from core.agent.tools.local_open_tool import LocalOpenTool
    assert LocalAppResolveTool().name == "local_app_resolve"
    assert LocalOpenTool().name == "local_open"
```

## 4. P0 修复 2：resolver 候选同步给 local_open

### 问题

文件：`core/agent/nanobot_adapter.py`

当前注册方式：

```python
resolver_tool = LocalAppResolveTool()
gateway.register_tool(resolver_tool)

open_tool = LocalOpenTool(resolver_candidates=[])
gateway.register_tool(open_tool)
```

`LocalOpenTool` 只接受 `resolver_candidates` 中出现过的路径。由于传入的是空列表，即使 `local_app_resolve` 找到候选，`local_open` 仍会返回：

```json
{"opened": false, "reason": "no_resolver_candidates_to_validate_against"}
```

### 修复方案

推荐最小改法：共享一个候选列表对象。

```python
shared_candidates: list[dict[str, Any]] = []
resolver_tool = LocalAppResolveTool(candidate_sink=shared_candidates)
open_tool = LocalOpenTool(resolver_candidates=shared_candidates)
```

`LocalAppResolveTool` 调整：

- `__init__(candidate_sink: list[dict[str, Any]] | None = None)`
- 找到候选后：

```python
self._last_candidates = candidates
if self._candidate_sink is not None:
    self._candidate_sink.clear()
    self._candidate_sink.extend(candidates)
```

注意：

- 不要让 `LocalOpenTool` 直接引用 `resolver_tool.last_candidates` 的拷贝，因为 property 当前返回 list，后续可能被复制。
- 共享列表只在本轮 adapter.run_task 内存在，cleanup 后自然释放。

### 验收

新增 adapter 级或工具级测试：

```python
async def test_resolver_candidates_shared_with_open_tool(tmp_path, monkeypatch):
    candidate_sink = []
    resolver = LocalAppResolveTool(candidate_sink=candidate_sink)
    opener = LocalOpenTool(resolver_candidates=candidate_sink)
    # arrange a fake desktop source containing app.lnk
    # run resolver, then assert opener accepts the resolved path
```

若 adapter 集成测试较重，先用工具级测试锁住共享候选，再补 adapter 注册测试。

## 5. P1 修复 3：中文目标提取准确化

### 问题

文件：`core/agent/execution_intent.py`

实测：

```text
帮我打开桌面的洛克王国：世界 -> target='的洛克王国：世界'
打开微信 -> target='信'
```

这会导致 resolver 匹配失败或置信度降低。

### 修复目标

实测结果应为：

```text
帮我打开桌面的洛克王国：世界 -> 洛克王国：世界
打开微信 -> 微信
帮我打开微信 -> 微信
帮我打开桌面上的洛克王国：世界 -> 洛克王国：世界
帮我启动桌面的 QQ -> QQ
```

### 修复方案

不要依赖 `match.end()` 后的残余字符串直接作为 target。改为规则化清洗：

1. 保留原始中文关键词，不使用乱码字面量。
2. 先处理引号：

```python
「...」 / “...” / "..." / '...'
```

3. 再移除动作前缀：

```text
帮我打开
帮我启动
打开
启动
运行
帮我开
```

4. 再移除位置限定：

```text
桌面的
桌面上的
桌面上
桌面
开始菜单里的
开始菜单
应用
游戏
快捷方式
```

5. 去掉末尾礼貌词和标点：

```text
一下
吧
好吗
？
。
，
,
.
```

### 建议实现

新增私有函数：

```python
def _clean_local_open_target(prompt: str) -> str:
    text = prompt.strip()
    text = _strip_quoted_target(text) or text
    text = re.sub(r"^(请)?(帮我)?(打开|启动|运行|开一下|帮我开)", "", text)
    text = re.sub(r"^(桌面上的|桌面的|桌面上|桌面|开始菜单里的|开始菜单)", "", text)
    text = re.sub(r"^(应用|游戏|快捷方式)", "", text)
    text = re.sub(r"(一下|吧|好吗)?[？?。,.，！!]*$", "", text)
    return text.strip(" ：:，,。 ")
```

`_extract_target()` 根据 intent 调用对应 cleaner。

### 验收

新增真实中文测试，不允许再用乱码输入覆盖：

```python
@pytest.mark.parametrize(
    ("prompt", "target"),
    [
        ("帮我打开桌面的洛克王国：世界", "洛克王国：世界"),
        ("打开微信", "微信"),
        ("帮我启动桌面上的 QQ", "QQ"),
        ("帮我打开“洛克王国：世界”", "洛克王国：世界"),
    ],
)
def test_extract_real_chinese_local_open_target(prompt, target):
    route = ExecutionIntentRouter().route(prompt)
    assert route.intent == ExecutionIntent.LOCAL_OPEN_TARGET
    assert route.target == target
```

## 6. P1 修复 4：高置信候选接入 hook

### 问题

文件：`core/agent/execution_hook.py`

当前 `ExecutionBudget.record_high_confidence_candidate()` 只在测试里手动调用。真实运行时，hook 没有解析 `local_app_resolve` 的工具结果，所以无法知道候选是否已经找到。

### 修复方案

在 `after_iteration()` 中解析 `context.tool_calls` 与 `context.tool_results`：

```python
for tc, result in zip(context.tool_calls, context.tool_results):
    if tc.name == "local_app_resolve" and _has_high_confidence_candidate(result):
        self._budget.record_high_confidence_candidate()
```

判断函数：

```python
def _has_high_confidence_candidate(result: Any) -> bool:
    data = json.loads(result) if isinstance(result, str) else result
    for candidate in data.get("candidates", []):
        if candidate.get("openable") and candidate.get("confidence", 0) >= 0.9:
            return True
    return False
```

下一轮如果模型继续调用 `exec` 或其他搜索工具，应被阻断；如果调用 `local_open`，允许。

### 验收

新增测试：

```python
def test_high_confidence_candidate_recorded_from_tool_result():
    hook = _make_hook(_local_open_route(), block_shell=False)
    ctx = fake_context(
        tool_calls=[fake_tc("local_app_resolve", {"target": "微信"})],
        tool_results=['{"candidates":[{"confidence":0.98,"openable":true}]}'],
    )
    asyncio.run(hook.after_iteration(ctx))
    assert hook._budget.resolver_has_high_confidence is True
```

再测下一轮继续搜索被拒绝：

```python
with pytest.raises(RuntimeError, match="high-confidence"):
    asyncio.run(hook.before_execute_tools(fake_context([fake_tc("exec", {"command": "echo search"})])))
```

## 7. P1 修复 5：ExecutionTraceRepository 真正接入

### 问题

文件：

- `core/storage/execution_trace_repository.py`
- `core/agent/execution_hook.py`
- `core/agent/nanobot_adapter.py`

`ExecutionTraceRepository` 已存在，但没有被实例化或调用。`execution_trace_enabled` 也没有产生实际行为。

### 修复方案

调整 `ExecutionGovernanceHook` 构造参数：

```python
def __init__(
    self,
    route: ExecutionRoute,
    budget: ExecutionBudget,
    session_id: str = "",
    trace_repo: ExecutionTraceRepository | None = None,
) -> None:
```

adapter 中：

```python
trace_repo = None
if settings.execution_trace_enabled:
    from core.storage.execution_trace_repository import ExecutionTraceRepository
    trace_repo = ExecutionTraceRepository()

execution_hook = ExecutionGovernanceHook(
    route=route,
    budget=budget,
    session_id=session_key,
    trace_repo=trace_repo,
)
```

hook 中记录：

- `before_execute_tools()` 阻断时记录 `status="blocked"`。
- `after_iteration()` 正常工具结果记录 `status="completed"` 或 `status="error"`。
- `usage` 从 `context.usage` 取 `prompt_tokens` / `completion_tokens`。

注意：

- 不记录完整 `tool_results`。
- `result_summary` 只保存前 500 chars。
- 记录失败不能影响主任务，trace 写入异常只打 debug 日志。

### 验收

新增测试：

```python
def test_execution_trace_repo_records_completed_tool(tmp_path):
    # use temporary sqlite database if existing Database supports override
    # or monkeypatch repo.record and assert called
```

最小可测方式：给 hook 注入 fake repo：

```python
class FakeTraceRepo:
    def __init__(self):
        self.records = []
    def record(self, **kwargs):
        self.records.append(kwargs)

def test_hook_records_trace_to_repo():
    repo = FakeTraceRepo()
    hook = ExecutionGovernanceHook(route, budget, session_id="s1", trace_repo=repo)
    asyncio.run(hook.after_iteration(ctx))
    assert repo.records
```

## 8. P1 修复 6：adapter 集成测试补齐

### 问题

计划中要求 `tests/test_nanobot_adapter_execution_governance.py`，当前不存在。

### 修复方案

新增 `tests/test_nanobot_adapter_execution_governance.py`，重点不要跑真实 nanobot，只 mock：

- `Nanobot.from_config`
- `NanobotGateway`
- `LocalAppResolveTool`
- `LocalOpenTool`
- `ExecutionGovernanceHook`

测试点：

1. `LOCAL_OPEN_TARGET` 时注册 `local_app_resolve` 和 `local_open`。
2. cleanup 后注销两个工具。
3. prompt 中包含 execution route 注入。
4. hooks 包含 `_ToolTracker` 和 `ExecutionGovernanceHook`。
5. `execution_governance_enabled=False` 时不注册 execution 工具。
6. `execution_local_tools_enabled=False` 时不注册本地工具，但仍可启用 hook 阻断递归 shell。
7. `execution_trace_enabled=True` 时 hook 得到 trace repo。

### 关键修正

当前 adapter 注册工具没有检查：

```python
execution_local_tools_enabled
```

应补：

```python
local_tools_enabled = getattr(self.settings, "execution_local_tools_enabled", True)
if local_tools_enabled and route.intent == ExecutionIntent.LOCAL_OPEN_TARGET:
    ...
```

## 9. P2 修复 7：工具路径安全校验补齐

### 问题

方案要求：

- `LocalAppResolveTool` 返回候选 path 前通过 `SafetyGuardrails.validate_path()`。
- `LocalOpenTool` 打开前再次校验 path。

当前工具没有 guardrails 注入。

### 修复方案

工具构造参数：

```python
LocalAppResolveTool(guardrails: SafetyGuardrails | None = None, ...)
LocalOpenTool(guardrails: SafetyGuardrails | None = None, ...)
```

resolver：

```python
if self._guardrails and self._guardrails.validate_path(str(entry.resolve())):
    continue
```

open：

```python
if self._guardrails:
    error = self._guardrails.validate_path(path)
    if error:
        return json.dumps({"opened": False, "reason": "guardrail_blocked", "detail": error})
```

adapter 注册时传入 `self.guardrails`。

### 验收

新增测试：

```python
def test_local_open_rejects_guardrail_blocked_path():
    guardrails = FakeGuardrails(error="outside workspace")
    tool = LocalOpenTool(resolver_candidates=[{"path": "C:\\bad.exe"}], guardrails=guardrails)
    data = json.loads(asyncio.run(tool.execute(path="C:\\bad.exe")))
    assert data["opened"] is False
    assert data["reason"] == "guardrail_blocked"
```

## 10. P2 修复 8：工具结果输出预算

### 问题

`execution_max_tool_result_chars` 已有配置，但 hook 没有裁剪工具结果。nanobot runner 自己有 `max_tool_result_chars`，但 5.4 的任务级预算没有体现。

### 修复方案

短期：

- 在 `LocalAppResolveTool` 内保证返回 JSON 总长度不超过 `max_result_chars`。
- 通过 `limit`、路径截断、reason 截断控制输出。

中期：

- `ExecutionGovernanceHook.after_iteration()` 记录超预算事件。
- 如工具结果超过预算，仅 trace 标记，不修改 nanobot message，避免复杂副作用。

### 验收

```python
def test_local_app_resolve_result_is_bounded():
    result = asyncio.run(tool.execute(target="x", limit=10))
    assert len(result) <= 3000
```

## 11. 推荐修复顺序

按以下顺序提交：

1. `修复本地执行工具测试导入`
   - fallback
   - `tests/test_54_execution_regression.py` 可收集

2. `修复本地打开候选共享`
   - candidate sink
   - opener 接受 resolver 候选

3. `修复中文执行目标提取`
   - 真实中文 pattern
   - target cleaner
   - 中文 regression tests

4. `接入高置信候选治理`
   - parse resolver result
   - 阻止找到候选后继续搜索

5. `接入执行轨迹记录`
   - fake repo tests
   - adapter 根据配置注入 repo

6. `补齐 adapter 执行治理集成测试`
   - 工具注册、prompt 注入、hook 列表、配置开关

7. `补齐 path guardrails 和输出预算`
   - resolver/open 二次校验
   - bounded output

## 12. 最终验收命令

最小验收：

```bash
pytest tests/test_execution_intent.py tests/test_execution_governance_hook.py tests/test_54_execution_regression.py tests/test_tool_policy_54.py -q
python -m py_compile core/agent/execution_intent.py core/agent/execution_budget.py core/agent/execution_hook.py core/agent/tools/local_app_resolve_tool.py core/agent/tools/local_open_tool.py core/storage/execution_trace_repository.py core/agent/nanobot_adapter.py
```

补齐 adapter 测试后：

```bash
pytest tests/test_nanobot_adapter_execution_governance.py -q
```

全量 5.4 execution smoke：

```bash
python tests/run_54_execution_tests.py
```

## 13. 完成定义

只有同时满足以下条件，才能认为 5.4 执行能力闭环完成：

1. 不安装 nanobot editable 包时，local tool tests 仍可收集并运行。
2. `帮我打开桌面的洛克王国：世界` 路由为 `LOCAL_OPEN_TARGET`，target 为 `洛克王国：世界`。
3. `打开微信` target 为 `微信`。
4. resolver 找到候选后，open tool 能接受同一轮候选 path。
5. 找到高置信候选后，继续 `exec` 搜索会被 hook 阻断。
6. `where /R`、`dir /s`、`Get-ChildItem -Recurse` 在本地打开任务中被阻断。
7. `Program Files`、`AppData` 在本地打开任务中被阻断。
8. execution trace 能记录 completed/blocked 工具调用摘要。
9. adapter 集成测试证明工具注册、cleanup、prompt 注入、hook 注入都生效。
10. `execution_governance_enabled=false` 可回退旧行为。

