# Lobuddy 5.3 记忆系统最终缺口闭环计划

**创建日期:** 2026-05-04  
**来源:** 第三轮审查 findings 1-5  
**适用对象:** opencode 下一轮定向修复  
**目标:** 不再扩展新能力，只关闭当前阻止“记忆系统边界清晰”的最后缺口。

## 0. 当前状态

经过前几轮改造，Lobuddy 5.3 已经具备这些基础：

- `MemoryWriteGateway` 已存在，并被 `app/main.py` 注入 `NanobotAdapter`。
- adapter 强信号写入和 AI patch 更新主路径已经调用 gateway。
- `ExitAnalyzer` 主路径在 `app/main.py` 中传入 gateway。
- `session_search` service、ChatRepo 搜索、Tool wrapper 已经创建。
- `PromptContextBundle.project_context`、`memory_budget_report`、hot budget 分层已经出现。
- active skills 已注入 prompt。
- `MemoryLintService` 已存在并接入 maintenance。
- `memory_gateway_*` settings 重复定义已经清理。

但仍有 5 个缺口会让系统边界不闭合：

1. Gateway provenance 仍只改返回对象，没有持久化到 SQLite。
2. `session_search_tool.py` 在当前测试环境不可导入。
3. Gateway 阈值仍被 `MemoryService.memory_min_confidence` 二次覆盖。
4. Skill 使用反馈链路仍未闭合。
5. `ExitAnalyzer` 仍保留无 gateway fallback 写入旁路。

本计划只处理这 5 个问题。

## 1. 总体完成定义

完成后必须满足：

```text
pytest tests/test_memory_write_boundary.py -q
pytest tests/test_session_search.py tests/test_session_search_tool.py -q
pytest tests/test_skill_selector.py tests/test_nanobot_adapter.py -q
pytest tests/test_53_phase1_verification.py -q
python -m py_compile core/agent/nanobot_adapter.py core/agent/tools/session_search_tool.py core/memory/memory_write_gateway.py core/memory/memory_service.py core/memory/exit_analyzer.py
```

并且：

- gateway 写入后的 `source/source_session_id/source_message_id` 可从 SQLite 读回。
- `SessionSearchTool` 可在没有额外手动 `PYTHONPATH`、没有完整 nanobot runtime 依赖的测试环境中导入。
- gateway 业务写入只受 `memory_gateway_min_confidence` 控制，不再被 `memory_min_confidence` 二次拒绝。
- `ExitAnalyzer` 不能在业务路径中绕过 gateway。
- Skill 使用反馈如果无法真实记录，必须显式声明并测试“只完成 prompt 可见性，不伪造 record_result”。

## 2. Phase A：修复 Gateway provenance 真入库

**优先级:** P1  
**对应 finding:** 1、3  
**目标:** gateway 在保存前写入 provenance，并避免 service 二次 confidence 策略。

### A1. 新增 gateway 专用保存 API

修改文件：

- `core/memory/memory_service.py`

新增方法：

```python
def apply_gateway_patch(
    self,
    patch: MemoryPatch,
    *,
    source: str,
    source_session_id: str | None = None,
    source_message_id: str | None = None,
) -> tuple[list[MemoryItem], list[MemoryPatchItem]]:
    """Apply a MemoryPatch already accepted by MemoryWriteGateway.

    This method does not apply memory_min_confidence again. Gateway owns
    business confidence policy for gateway writes.
    """
```

实现要求：

- 复用 `apply_patch()` 的 merge/update/deprecate 逻辑，但保存前要写入 provenance。
- 新建 `MemoryItem` 时直接设置：
  - `source=source`
  - `source_session_id=source_session_id`
  - `source_message_id=source_message_id`
- 更新 existing memory 时也设置：
  - `existing.source = source`
  - `existing.source_session_id = source_session_id`
  - `existing.source_message_id = source_message_id`
- 不再读取 `memory_min_confidence`。
- 仍然保留 `_sanitize_memory_text()`、空内容拒绝、duplicate/merge 逻辑。
- `MemoryService.apply_patch()` 继续保留给旧测试和内部低层调用，但注释标明：业务写入请使用 `MemoryWriteGateway`。

### A2. 修改 MemoryWriteGateway 调用

修改文件：

- `core/memory/memory_write_gateway.py`

将当前：

```python
accepted, rejected_by_service = self._memory_service.apply_patch(accepted_patch)
result.accepted = accepted
for mem in result.accepted:
    mem.source = context.source
    if context.session_id:
        mem.source_session_id = context.session_id
```

改为：

```python
accepted, rejected_by_service = self._memory_service.apply_gateway_patch(
    accepted_patch,
    source=context.source,
    source_session_id=context.session_id,
    source_message_id=context.message_id,
)
result.accepted = accepted
```

不要再“保存后补字段”。

### A3. 补强测试

修改文件：

- `tests/test_memory_write_boundary.py`

新增或修改测试：

```python
def test_gateway_provenance_persisted_to_sqlite(...):
    service = _make_memory_service(...)
    gateway = MemoryWriteGateway(service, settings)
    context = WriteContext(
        source="ai_patch",
        session_id="session-123",
        message_id="message-456",
        triggered_by="test",
    )
    result = asyncio.run(gateway.submit_patch(patch, context))
    loaded = service.get_memory(result.accepted[0].id)

    assert loaded.source == "ai_patch"
    assert loaded.source_session_id == "session-123"
    assert loaded.source_message_id == "message-456"
```

新增：

```python
def test_gateway_confidence_not_overridden_by_memory_service(...):
    settings.memory_gateway_min_confidence = 0.5
    settings.memory_min_confidence = 0.95
    patch item confidence = 0.7

    result should be accepted through gateway
    loaded item should exist in SQLite
```

这两个测试是本轮最关键验收，不可省略。

## 3. Phase B：让 SessionSearchTool 可导入、可测试、可注册

**优先级:** P1  
**对应 finding:** 2  
**目标:** `session_search_tool.py` 不应因为顶层 import nanobot/tiktoken 失败而不可导入。

### B1. 去掉顶层 nanobot 重依赖

当前问题：

```python
from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, IntegerSchema, tool_parameters_schema
```

在测试环境中，`nanobot` 不一定已安装；即使 `PYTHONPATH=lib/nanobot`，又可能缺 `tiktoken`。

推荐改造方式：

1. 延迟导入 nanobot Tool 基类。
2. 提供轻量 fallback base class 和 schema decorator。
3. 保证 fallback 仍提供 nanobot registry 所需的最小协议：
   - `name`
   - `description`
   - `parameters`
   - `read_only`
   - `execute(...)`
   - `to_schema()` 如 registry 需要。

示例结构：

```python
try:
    from nanobot.agent.tools.base import Tool, tool_parameters
    from nanobot.agent.tools.schema import StringSchema, IntegerSchema, tool_parameters_schema
except Exception:
    class Tool:
        @property
        def name(self) -> str: ...
        @property
        def description(self) -> str: ...
        @property
        def parameters(self) -> dict: ...
        @property
        def read_only(self) -> bool:
            return True
        def to_schema(self) -> dict:
            return {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.parameters,
                },
            }

    def tool_parameters(schema):
        def deco(cls):
            cls.parameters = property(lambda self: schema)
            return cls
        return deco

    def tool_parameters_schema(...):
        return {...}
```

也可以不用 decorator，直接在 `SessionSearchTool.parameters` 中返回 dict。更简单、更稳：

```python
class SessionSearchTool(Tool):
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "..."},
                "scope": {"type": "string", "enum": ["current_session", "all_sessions"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        }
```

优先推荐直接实现 `parameters`，避免 decorator fallback 复杂化。

### B2. Adapter 注册失败不要静默成功

修改文件：

- `core/agent/nanobot_adapter.py`

当前注册失败只 warning 并继续。这个行为运行时可以接受，但测试和 UI 需要可观测。

建议：

- warning 保留。
- 增加明确状态日志：
  - `session_search_enabled_but_unavailable`
- 可选在 `AgentResult` metadata 中记录工具注册失败；如果当前模型不支持 metadata，则先不做。

### B3. 补测试

修改文件：

- `tests/test_session_search_tool.py`

要求：

- 不设置 `PYTHONPATH` 也能 import `SessionSearchTool`。
- `tool.name == "session_search"`。
- `tool.parameters` 是合法 JSON schema dict。
- 空 query 返回“Query required”。
- execute 能返回 markdown。

新增 adapter 级轻量测试：

- `memory_session_search_enabled=False` 时不注册。
- `memory_session_search_enabled=True` 且 tool import 正常时会调用 `gateway.register_tool()`。

不要让测试依赖完整 nanobot 安装。

## 4. Phase C：收紧 ExitAnalyzer 写入边界

**优先级:** P2  
**对应 finding:** 5  
**目标:** 业务路径不允许无 gateway 写入长期记忆。

### C1. 构造函数要求 gateway

修改文件：

- `core/memory/exit_analyzer.py`

当前：

```python
def __init__(..., memory_service: MemoryService, gateway: MemoryWriteGateway | None = None)
```

改为：

```python
def __init__(..., memory_service: MemoryService, gateway: MemoryWriteGateway)
```

如果为了旧测试兼容必须允许 `None`，则 fallback 不能写入，只能跳过：

```python
if self._gateway is None:
    logger.warning("ExitAnalyzer memory write skipped: gateway missing")
    return None
```

不要再 fallback 到：

- `MemoryService.upsert_identity_memory()`
- `MemoryService.save_memory()`

### C2. 删除旁路写入

删除或替换这些 fallback：

- `_persist_identity()` 中无 gateway 时直接 `upsert_identity_memory()` 的分支。
- `_persist_preference()` 中无 gateway 时构造 `MemoryItem` 并 `save_memory()` 的分支。

### C3. 修改测试

修改：

- `tests/test_memory_write_boundary.py`
- 可能还有 `tests/test_exit_wiring.py`

测试目标：

- `ExitAnalyzer(settings, service, gateway=gateway)` 可正常写入。
- `ExitAnalyzer(..., gateway=None)` 如果仍允许构造，则不会写入任何长期记忆，并返回 skipped/None。
- `rg "upsert_identity_memory\\(|save_memory\\(" core/memory/exit_analyzer.py` 不应再命中业务写入 fallback。

## 5. Phase D：Skill 使用反馈策略收口

**优先级:** P2  
**对应 finding:** 4  
**目标:** 不再模糊“skill prompt 可见”和“skill 使用反馈”两个层次。

当前状态：

- active skills 已经通过 `SkillSelector.build_skills_summary()` 注入 prompt。
- 但 `record_result()` 没有被 adapter 调用。

### D1. 先判断 nanobot 是否能报告实际 skill 使用

opencode 需要先检查：

- `lib/nanobot` 的 skill loader 是否把 skill 当作 tool。
- `_ToolTracker.tools_used` 是否包含 skill 名称。
- skill 调用事件是否有独立 hook。

### D2. 如果能识别 skill 使用

实现：

- adapter 运行前建立 active skill name/id map。
- `_ToolTracker` 或新 hook 记录实际 skill name。
- 成功时：

```python
self._skill_manager.record_result(skill_id, True, session_id=session_key)
```

- 失败/异常时：

```python
self._skill_manager.record_result(skill_id, False, session_id=session_key)
```

测试：

- active skill 被 tracker 记录后 success_count +1。
- 异常路径 failure_count +1。

### D3. 如果不能识别 skill 使用

不要伪造反馈。

必须做：

- 在 `core/agent/nanobot_adapter.py` 中加明确注释：

```python
# Active skills are prompt-visible in Lobuddy 5.3.
# Usage feedback is intentionally not recorded here because nanobot does not
# expose reliable per-skill execution events yet.
```

- 在计划/测试中明确当前完成定义：
  - prompt 可见性已完成。
  - 使用反馈等待 nanobot skill event hook。

新增测试：

- active skill 出现在 injection。
- disabled skill 不出现。
- adapter 不调用 `record_result()`，除非测试模拟了可靠 skill execution event。

### D4. 推荐本轮选择

如果没有清晰可靠事件，选择 D3。  
不要把普通 tool 调用当作 skill 调用，否则 skill 成功率会污染。

## 6. Phase E：清理工作树副产物

当前审查发现工作树有：

```text
M core/skills/__pycache__/skill_registry.cpython-311.pyc
M data/memory/SYSTEM.md
```

这些不是本轮计划文档的一部分。opencode 实施代码修复前应确认：

- `__pycache__` 不应纳入提交。
- `data/memory/SYSTEM.md` 是运行时投影文件，除非用户明确要求提交，否则不要混入代码改造提交。

建议：

- 如果它们是误改或运行测试产生，实施前先与用户确认是否清理。
- 不要用 `git reset --hard`。
- 不要误删用户数据。

## 7. 本轮禁止事项

- 不要继续新增大模块。
- 不要重写整个 memory service。
- 不要只改测试让它绿。
- 不要让 gateway 保存后再补 provenance。
- 不要让 `SessionSearchTool` import 依赖完整 nanobot runtime 才能导入。
- 不要让 `ExitAnalyzer` 无 gateway 时 fallback 直接写 memory。
- 不要伪造 skill 使用反馈。

## 8. 验收 checklist

### 写入网关

- [ ] `MemoryWriteGateway.submit_patch()` 调用 `MemoryService.apply_gateway_patch()`。
- [ ] `apply_gateway_patch()` 保存前写入 provenance。
- [ ] SQLite 读回 source/source_session_id/source_message_id 正确。
- [ ] gateway confidence 不被 `memory_min_confidence` 二次覆盖。

### session_search tool

- [ ] `from core.agent.tools.session_search_tool import SessionSearchTool` 在普通测试环境中成功。
- [ ] `SessionSearchTool.parameters` 是 JSON schema dict。
- [ ] `tests/test_session_search_tool.py` 不依赖手动 `PYTHONPATH`。
- [ ] adapter enabled 时能注册 tool，disabled 时不注册。

### ExitAnalyzer

- [ ] 无 gateway 时不再写入长期记忆。
- [ ] 主路径 gateway 写入仍正常。
- [ ] `rg "upsert_identity_memory\\(|save_memory\\(" core/memory/exit_analyzer.py` 不再出现 fallback 写入。

### Skill

- [ ] active skill prompt 注入测试保留。
- [ ] 使用反馈要么真实记录，要么明确暂不记录。
- [ ] 不把普通 tool 使用误记为 skill 使用。

## 9. 推荐执行顺序

1. 修 `MemoryService.apply_gateway_patch()` 和 `MemoryWriteGateway.submit_patch()`。
2. 补 SQLite provenance 测试和 gateway confidence 测试。
3. 修 `SessionSearchTool` 的 nanobot 依赖导入。
4. 跑 `tests/test_session_search_tool.py`。
5. 收紧 `ExitAnalyzer` fallback。
6. 明确 Skill 使用反馈策略，补对应测试或注释。
7. 跑完整 5.3 相关测试。

最终验收命令：

```bash
pytest tests/test_memory_write_boundary.py -q
pytest tests/test_session_search.py tests/test_session_search_tool.py -q
pytest tests/test_memory_selector.py tests/test_memory_lint.py tests/test_skill_selector.py -q
pytest tests/test_nanobot_adapter.py tests/test_exit_wiring.py -q
pytest tests/test_53_phase1_verification.py -q
python -m py_compile core/agent/nanobot_adapter.py core/agent/tools/session_search_tool.py core/memory/memory_write_gateway.py core/memory/memory_service.py core/memory/exit_analyzer.py
```

