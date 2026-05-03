# Lobuddy 5.3 记忆系统边界闭环升级计划

**创建日期:** 2026-05-03  
**来源:** 第二轮代码审查 findings 1-6  
**目标:** 关闭当前残留的运行时边界漏洞，让 Lobuddy 记忆系统从“入口雏形清晰”推进到“数据、工具、prompt、skill、配置全部闭环”。

## 0. 当前状态判断

opencode 第二轮改造已经完成了实质进步：

- `app/main.py` 已创建 `MemoryWriteGateway`，并注入 `NanobotAdapter`。
- `NanobotAdapter._sync_strong_signal_memory()` 主路径已改为通过 gateway 写 identity memory。
- `NanobotAdapter._run_memory_update()` 已拆出 `parse_ai_response_to_patch()`，并通过 gateway 提交 patch。
- `ExitAnalyzer` 主路径可接收 gateway，并优先通过 gateway 写入。
- `MemoryWriteGateway` 已开始使用 `memory_gateway_min_confidence` 和 `memory_gateway_max_items_per_patch`。
- 新增 `tests/test_memory_write_boundary.py`，覆盖了一部分 gateway 行为。

但当前仍不能判定为“记忆系统清晰完成”。本轮计划只处理审查发现的 6 个明确问题：

1. Gateway provenance 只改返回对象，没有持久化到 SQLite。
2. `session_search` 仍只有设置/UI，没有服务、Tool 和注册链路。
3. Gateway 阈值和 `MemoryService.memory_min_confidence` 双重生效，策略不唯一。
4. Hot project context 配置仍未进入 `PromptContextBundle`。
5. `SkillManager` 仍未进入 prompt 或使用反馈链路。
6. `Settings` 中 `memory_gateway_*` 字段重复定义。

## 1. 本轮完成后的目标边界

### 1.1 写入边界

```text
Business write source
  -> MemoryWriteGateway
  -> MemoryService.apply_patch_from_gateway(...)
  -> MemoryRepository.save(...)
  -> SQLite memory_item(source/source_session_id/source_message_id)
  -> MemoryProjection refresh
```

完成后必须满足：

- gateway 的 `WriteContext.source/session_id/message_id/task_id` 真正入库。
- 测试必须从 `service.get_memory()` 或 repository 读回 SQLite 数据再断言 provenance。
- `MemoryService.apply_patch()` 可以保留给低层测试和旧兼容，但业务主路径不使用它绕过 gateway。

### 1.2 冷 recall 边界

```text
memory_session_search_enabled=False
  -> 不注册 session_search tool

memory_session_search_enabled=True
  -> 注册 session_search tool
  -> 默认 current_session
  -> 限长、脱敏、可审计
```

完成后必须满足：

- 设置页开关打开后有真实工具链路。
- 关闭时 agent 看不到该工具。
- `all_sessions` 不能默认启用。
- 检索结果进入 LLM 上下文前必须脱敏和裁剪。

### 1.3 Prompt hot/cold 边界

```text
Hot context:
  User Profile
  System Profile
  Project Context
  Current Session Summary
  Available Skills

Cold recall:
  session_search tool result
  keyword/FTS retrieved episodic memory
```

完成后必须满足：

- `PromptContextBundle` 有独立 `project_context`。
- `memory_hot_*_tokens` 配置被 selector 消费。
- `PROJECT_MEMORY` 不再只能混在 `retrieved_memories` 中。

### 1.4 Skill 边界

```text
SkillManager SQLite active records
  -> SkillSelector.build_skills_summary()
  -> PromptContextBundle.active_skills
  -> Nanobot prompt
  -> optional usage feedback -> SkillManager.record_result()
```

完成后必须满足：

- active skill 进入 prompt。
- disabled/archived/deleted skill 不进入 prompt。
- 如果当前 nanobot 无法报告具体 skill 使用，必须在代码和测试中明确“暂不记录使用反馈”，不能假装已闭环。

## 2. Phase A：修复 Gateway provenance 真入库

**优先级:** P1  
**对应 finding:** 1、3  
**目标:** gateway 的上下文必须在保存前进入 `MemoryItem`，并且 gateway 阈值是业务写入的唯一外层策略。

### A1. 不要在保存后补 provenance

当前问题位置：

- `core/memory/memory_write_gateway.py`
- 当前流程是 `self._memory_service.apply_patch(accepted_patch)` 后再改 `mem.source` 和 `mem.source_session_id`。

这只改了返回对象，不保证 SQLite 已保存的行同步更新。

### A2. 新增 gateway 专用 apply 方法

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
    skip_confidence_check: bool = True,
) -> tuple[list[MemoryItem], list[MemoryPatchItem]]:
    ...
```

要求：

- 保存新 `MemoryItem` 时直接写入：
  - `source=source`
  - `source_session_id=source_session_id`
  - `source_message_id=source_message_id`
- 更新 existing memory 时也要更新 provenance：
  - `existing.source = source`
  - `existing.source_session_id = source_session_id`
  - `existing.source_message_id = source_message_id`
- `skip_confidence_check=True` 时不要再使用 `memory_min_confidence` 二次拒绝，因为 gateway 已经按 `memory_gateway_min_confidence` 处理。
- `apply_patch()` 可保留为 legacy/internal API，但注释说明业务路径应走 gateway。

可选更稳方案：

- 抽出内部私有方法 `_apply_patch_core(patch, policy)`，让 legacy 和 gateway 共用。
- 但本轮以降低风险为主，可以先新增 `apply_gateway_patch()`，避免大改。

### A3. 修改 Gateway 调用点

修改文件：

- `core/memory/memory_write_gateway.py`

将：

```python
accepted, rejected_by_service = self._memory_service.apply_patch(accepted_patch)
for mem in result.accepted:
    mem.source = context.source
    mem.source_session_id = context.session_id
```

改为：

```python
accepted, rejected_by_service = self._memory_service.apply_gateway_patch(
    accepted_patch,
    source=context.source,
    source_session_id=context.session_id,
    source_message_id=context.message_id,
    skip_confidence_check=True,
)
result.accepted = accepted
```

### A4. 修复测试缺口

修改文件：

- `tests/test_memory_write_boundary.py`

必须新增断言：

```python
loaded = service.get_memory(accepted.id)
assert loaded.source == "ai_patch"
assert loaded.source_session_id == "test-session-123"
assert loaded.source_message_id == "msg-123"
```

新增测试：

1. `test_gateway_provenance_persisted_to_sqlite`
2. `test_gateway_min_confidence_is_not_overridden_by_service_min_confidence`

第二个测试建议：

```python
settings = Settings(
    memory_gateway_min_confidence=0.5,
    memory_min_confidence=0.95,
)
patch item confidence = 0.7

通过 gateway 应 accepted，并且 SQLite 中存在。
```

这能证明 gateway 阈值是业务写入的外层策略，service 不再二次覆盖。

### A5. 验收标准

- `rg "apply_patch\\(" core/agent core/memory/exit_analyzer.py app ui` 不应出现业务层直接调用。
- `MemoryWriteGateway.submit_patch()` 不再保存后补 provenance。
- SQLite 读回来的 row provenance 正确。

验收命令：

```bash
pytest tests/test_memory_write_boundary.py -q
pytest tests/test_memory_service.py -q
python -m py_compile core/memory/memory_write_gateway.py core/memory/memory_service.py
```

## 3. Phase B：实现 session_search 冷历史 recall

**优先级:** P1  
**对应 finding:** 2  
**目标:** 关闭“设置/UI 有开关但没有功能”的空边界。

### B1. ChatRepository 增加搜索 API

修改文件：

- `core/storage/chat_repo.py`

新增：

```python
def search_messages(
    self,
    query: str,
    *,
    session_id: str | None = None,
    limit: int = 10,
) -> list[ChatMessage]:
    ...
```

实现要求：

- 空 query 返回空列表。
- 初版可使用 `LIKE`。
- 如果后续加入 FTS5，必须有 fallback。
- current session 搜索必须带 `session_id` 条件。

### B2. 新增 SessionSearchService

新增文件：

- `core/memory/session_search.py`

建议结构：

```python
class SessionSearchScope(str, Enum):
    CURRENT_SESSION = "current_session"
    ALL_SESSIONS = "all_sessions"

class SessionSearchResult(BaseModel):
    session_id: str
    message_id: str
    role: str
    content: str
    created_at: datetime

class SessionSearchService:
    def __init__(self, settings: Settings, chat_repo: ChatRepository | None = None) -> None:
        ...

    def search(
        self,
        query: str,
        *,
        current_session_id: str,
        scope: SessionSearchScope | str | None = None,
        limit: int = 5,
    ) -> list[SessionSearchResult]:
        ...
```

要求：

- 默认 scope 使用 `settings.memory_session_search_default_scope`。
- 如果 scope 是 `all_sessions`，必须显式允许；本轮可以先拒绝 `all_sessions`，只实现 current_session。
- 结果内容调用 `_sanitize_memory_text()` 或等价清洗逻辑。
- 单条结果裁剪到 `memory_session_search_max_result_chars`。
- 总结果裁剪到 `memory_session_search_total_budget_chars`。

### B3. 新增 nanobot Tool wrapper

新增文件：

- `core/agent/tools/session_search_tool.py`

前置要求：

- 先查看 `lib/nanobot` 当前 Tool 协议。
- wrapper 必须符合 nanobot 的工具注册方式，不要只写普通 class。

工具 contract：

```text
name: session_search
description: Search local chat history when current context lacks older details.
args:
  query: string
  scope: "current_session" | "all_sessions"
  limit: integer
```

输出：

- 推荐 JSON 或短 markdown。
- 必须标明结果来自本地聊天历史。
- 不要输出超过总预算。

### B4. Adapter 注册工具

修改文件：

- `core/agent/nanobot_adapter.py`

在创建 `NanobotGateway(bot)` 后、`bot.run()` 前：

```python
if self.settings.memory_session_search_enabled:
    tool = SessionSearchTool(
        SessionSearchService(self.settings),
        current_session_id=session_id,
    )
    gateway.register_tool(tool)
```

注意：

- 如果 `NanobotGateway` 没有 `register_tool()`，需要按 nanobot 实际 API 接入。
- 关闭设置时不能注册。
- 注册失败应 debug log，不应阻断主任务。

### B5. UI 文案

修改文件：

- `ui/settings_window.py`

当前文案方向正确，但需要 tooltip：

```text
开启后，agent 可以按需检索本地聊天历史。检索片段会进入当前 LLM provider 上下文。默认仅限当前会话，并会脱敏和限长。
```

### B6. 测试

新增：

- `tests/test_session_search.py`
- `tests/test_session_search_tool.py`
- 可选 `tests/test_nanobot_adapter_session_search.py`

必须覆盖：

- disabled 不注册 tool。
- enabled 注册 tool。
- current_session 不泄露其他 session。
- query 为空返回空。
- 单条和总长度预算生效。
- email/API token 脱敏。

验收命令：

```bash
pytest tests/test_session_search.py tests/test_session_search_tool.py -q
pytest tests/test_nanobot_adapter.py -q
```

## 4. Phase C：实现 Hot Project Context 与分层预算

**优先级:** P2  
**对应 finding:** 4  
**目标:** 让 hot memory 不再只是配置项，而是真正影响 prompt。

### C1. 扩展 PromptContextBundle

修改文件：

- `core/memory/memory_schema.py`

新增：

```python
project_context: str = Field(default="", description="Hot project context")
budget_report: dict[str, int] = Field(default_factory=dict)
```

修改 `build_injection_text()` 顺序：

```text
User Profile
System Profile
Project Context
Current Session Summary
Relevant Past Memory
Available Skills
```

### C2. MemorySelector 消费 hot budget

修改文件：

- `core/memory/memory_selector.py`

建议实现一个简单 helper：

```python
def _token_budget_to_chars(tokens: int) -> int:
    return tokens * 4
```

预算规则：

- `user_profile` 最多 `memory_hot_user_profile_tokens * 4` chars。
- `system_profile` 最多 `memory_hot_system_profile_tokens * 4` chars。
- `project_context` 最多 `memory_hot_project_context_tokens * 4` chars。
- `retrieved_memories` 使用剩余 prompt budget。

### C3. Project context 选择规则

初版规则：

- 从 `MemoryType.PROJECT_MEMORY` 读取 active items。
- 如果 `session_id` 或 `user_message` 能推断 scope，优先同 scope。
- 推断不到时按 priority/importance 排序取全局 project memory。
- 不要把全部 project memory 无限制注入。

### C4. 测试

新增或修改：

- `tests/test_memory_selector.py`

必须覆盖：

- `PromptContextBundle.project_context` 存在。
- project memory 进入 `project_context`。
- `memory_hot_project_context_tokens` 影响输出长度。
- user/system/project 三类 hot budget 互不挤占。
- `total_chars` 包含 `project_context`。

验收命令：

```bash
pytest tests/test_memory_selector.py tests/test_memory_service.py -q
```

## 5. Phase D：接入 Skill prompt 可见性与反馈边界

**优先级:** P2  
**对应 finding:** 5  
**目标:** 让 SkillManager 不只是被保存到 adapter，而是真正影响 agent 上下文。

### D1. Prompt 中注入 active skills

修改文件：

- `core/agent/nanobot_adapter.py`

在 `bundle = self._memory_service.build_prompt_context(...)` 之后：

```python
if self._skill_manager is not None:
    from core.skills.skill_selector import SkillSelector
    bundle.active_skills = SkillSelector(self._skill_manager).build_skills_summary()
```

然后再：

```python
injection = bundle.build_injection_text()
```

要求：

- disabled/archived skill 不进入 summary。
- summary 有长度限制，避免 skill 过多撑爆 prompt。

### D2. Skill 使用反馈策略

先确认 nanobot 是否能提供“实际使用了哪个 skill”的事件。

如果可以：

- `_ToolTracker` 或新的 hook 记录 skill name。
- 成功任务后调用 `SkillManager.record_result(skill_id, True, session_id)`。
- 失败任务后调用 `SkillManager.record_result(skill_id, False, session_id)`。

如果不可以：

- 本轮明确只完成 prompt 可见性。
- 在代码注释和计划中记录：`record_result` 仍只由外部/未来 hook 调用。
- 不要用普通 tool 名称冒充 skill 使用。

### D3. Skill 候选生成不要自动 approve

检查：

- `skill_auto_candidate_enabled` 默认仍为 false。
- `skill_candidate_auto_approve_threshold` 不应导致无人审查自动创建 active skill，除非 UI 明确开启。

### D4. 测试

新增：

- `tests/test_skill_prompt_injection.py`

必须覆盖：

- active skill 出现在 `Available Skills`。
- disabled skill 不出现。
- adapter 有 skill_manager 时会把 active_skills 写入 prompt injection。
- 无 skill_manager 时行为不变。

验收命令：

```bash
pytest tests/test_skill_selector.py tests/test_skill_prompt_injection.py -q
pytest tests/test_nanobot_adapter.py -q
```

## 6. Phase E：去重 settings 中 memory_gateway_* 字段

**优先级:** P3  
**对应 finding:** 6  
**目标:** 配置定义只出现一次，降低维护歧义。

### E1. 删除重复字段

修改文件：

- `core/config/settings.py`

当前重复位置：

- 约 288-292 行。
- 约 397-401 行。

建议保留 5.3 区块中的定义，删除前面靠近 `memory_min_confidence` 的重复定义。

保留：

```python
# Memory write gateway
memory_gateway_min_confidence: float = Field(...)
memory_gateway_max_items_per_patch: int = Field(...)
```

### E2. 测试

现有 `tests/test_53_phase1_verification.py` 已覆盖默认值。补一个轻量静态测试可选：

```python
def test_memory_gateway_settings_defined_once():
    source = Path("core/config/settings.py").read_text(encoding="utf-8")
    assert source.count("memory_gateway_min_confidence:") == 1
    assert source.count("memory_gateway_max_items_per_patch:") == 1
```

验收命令：

```bash
pytest tests/test_53_phase1_verification.py -q
python -m py_compile core/config/settings.py
```

## 7. Phase F：MemoryLint 不要继续空开关

**优先级:** P2  
**补充项:** 虽然本轮 finding 没单独列出实现缺失，但 `memory_lint_enabled` 当前仍是配置/UI 先行。

两种可接受方案，必须选一种。

### 方案 F1：本轮实现最小 MemoryLintService

新增文件：

- `core/memory/memory_lint.py`

最小检查：

- duplicate active memory。
- low confidence active memory。
- stale memory。
- projection file missing/header missing。

接入：

- `core/memory/memory_maintenance.py`

### 方案 F2：暂时隐藏 UI 开关

如果本轮不实现 MemoryLintService，则：

- UI 不展示“启动时运行记忆体检”。
- 或 tooltip 明确标注“计划中，当前未启用”。
- settings 可保留，但不要给用户制造已完成错觉。

推荐：选择 F1，因为记忆系统要清晰，体检报告很重要。

## 8. 实施顺序

### 第一组：必须先做

1. 修 gateway provenance 入库。
2. 修 gateway/service 双阈值冲突。
3. 给 provenance 增加 SQLite 读回测试。
4. 去重 settings。

原因：这是当前最核心的数据边界。如果 source/session_id 不入库，后面 lint、review、debug 都会失真。

### 第二组：补空开关

1. 实现 `SessionSearchService`。
2. 实现 `session_search` Tool wrapper。
3. adapter 按设置注册。
4. 实现或隐藏 MemoryLint UI。

原因：用户可见开关必须对应真实能力。

### 第三组：prompt 清晰化

1. `PromptContextBundle.project_context`。
2. hot budget 分层。
3. active skills 注入 prompt。
4. 补 prompt snapshot 测试。

原因：这组决定模型每轮到底看到什么。

## 9. 最小可交付版本

如果下一轮只做一个最小闭环，范围应为：

```text
P1 必做：
- Gateway provenance 真入库
- Gateway 阈值不被 MemoryService 二次覆盖
- settings 去重
- session_search 不再是空开关：至少实现 service + ChatRepo 搜索

P2 可并行：
- project_context 字段 + hot project budget
- active skills prompt 注入
```

最小闭环验收：

```bash
pytest tests/test_memory_write_boundary.py -q
pytest tests/test_session_search.py -q
pytest tests/test_memory_selector.py -q
pytest tests/test_skill_prompt_injection.py -q
pytest tests/test_53_phase1_verification.py -q
```

## 10. 禁止事项

- 不要只修测试里的返回对象，必须断言 SQLite 读回。
- 不要让 `session_search` 默认搜索所有 session。
- 不要在 `MemoryService` 内部创建 `MemoryWriteGateway`。
- 不要让 gateway 保存后再补 provenance。
- 不要保留用户可见但无运行时功能的开关。
- 不要把 disabled/archived skill 注入 prompt。
- 不要让 `memory_gateway_min_confidence` 和 `memory_min_confidence` 在同一业务写入路径上产生相互覆盖。

## 11. 完成判定

当以下条件全部满足，才能说当前 Lobuddy 记忆系统边界清晰：

- `MemoryWriteGateway` 是 adapter、ExitAnalyzer、未来 Dream proposal 的唯一业务写入入口。
- `source/source_session_id/source_message_id` 从 gateway 写入后可从 SQLite 读回。
- `session_search` 开关有真实工具链路，且默认关闭、限范围、脱敏、限长。
- `PromptContextBundle` 明确区分 user/system/project/session/retrieved/skills。
- `memory_hot_*` 配置被运行时消费。
- active skills 可见，非 active skills 不可见。
- `Settings` 中无重复 memory gateway 字段。
- 测试覆盖的不只是“对象返回正确”，还包括数据库、prompt 注入文本和工具注册状态。

