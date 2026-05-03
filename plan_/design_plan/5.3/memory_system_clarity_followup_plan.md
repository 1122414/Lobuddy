# Lobuddy 5.3 记忆系统清晰化续改计划

**创建日期:** 2026-05-03  
**来源:** 当前代码审查 findings 1-5  
**目标:** 把 5.3 从“骨架存在”推进到“运行时边界闭合、用户可理解、测试可证明”。

## 0. 当前结论

本轮 opencode 改造已经完成了 Phase 1 的关键骨架：

- `MemoryWriteGateway` 已创建。
- Lobuddy SQLite 继续作为权威记忆源。
- Markdown 投影文件已有 generated header，标明不可直接编辑。
- `/dream`、`/dream-log`、`/dream-restore` 已在 adapter 层拦截。
- Skill disable/archive/delete 会同步移除 workspace 下的 `SKILL.md`。
- `tests/test_53_phase1_verification.py` 已通过。

但系统还不能称为“记忆边界清晰完成”。核心原因是：多个配置、UI 和注释已经表达了 5.3 的目标状态，但真实运行路径尚未完全接入。

## 1. 必须坚持的最终边界

### 1.1 权威数据边界

```text
Lobuddy SQLite memory_item = 权威长期记忆
workspace/USER.md, workspace/SOUL.md, workspace/memory/MEMORY.md = 只读投影
nanobot Dream = Lobuddy 模式下禁用，未来只能产出 MemoryPatch proposal
```

规则：

- 任何长期记忆写入不得直接编辑 workspace 投影文件。
- 投影文件只允许由 `MemoryProjection` 刷新。
- 如果以后恢复 Dream，只允许 Dream 输出结构化 `MemoryPatch`，再交给 `MemoryWriteGateway`。

### 1.2 写入入口边界

```text
UI / Adapter / ExitAnalyzer / Manual Review / Future Dream
  -> MemoryWriteGateway
  -> MemoryService
  -> MemoryRepository
  -> SQLite
  -> MemoryProjection
```

规则：

- `MemoryWriteGateway` 是外层写入入口。
- `MemoryService` 是内层领域服务，不反向依赖 gateway。
- 业务写入不允许直接调用 `MemoryService.save_memory()`、`apply_patch()`、`apply_ai_response()`、`upsert_identity_memory()`。
- 允许例外：
  - 单元测试。
  - 一次性迁移脚本。
  - `MemoryService._ensure_bootstrap_memories()`。
  - 只读查询、prompt context 构建和维护任务内部操作。

### 1.3 热记忆与冷 recall 边界

```text
Hot memory = 每次 prompt 固定注入的小预算事实
Cold recall = agent 需要时通过 session_search 主动检索历史
```

规则：

- 用户画像、系统身份、当前项目上下文属于 hot memory。
- 完整历史、长对话、旧 session 属于 cold recall。
- `session_search` 会把本地聊天片段送入 LLM 上下文，必须默认关闭，并由 UI 明确说明。

### 1.4 Skill 边界

```text
SkillRecord in SQLite = skill 生命周期权威源
workspace/skills/*/SKILL.md = nanobot 可消费投影
SkillSelector = prompt 可见 skill 摘要
SkillManager.record_result = skill 使用反馈
```

规则：

- active skill 才能进入 prompt 或 workspace。
- disabled/archived/deleted skill 不得继续被 nanobot 发现。
- agent 使用 skill 后必须记录成功/失败，以支持 stale review 和自动维护。

## 2. Phase A：闭合 MemoryWriteGateway 写入边界

**优先级:** P1  
**目标:** 让所有真实业务写入都经过 gateway。  
**不做:** 不把 gateway 塞进 `MemoryService` 内部，避免循环依赖。

### A1. 调整组合根

修改文件：

- `app/main.py`
- `core/agent/nanobot_adapter.py`
- `core/memory/exit_analyzer.py`

建议实现：

```python
memory_service = MemoryService(settings)
memory_gateway = MemoryWriteGateway(memory_service, settings)
task_manager.adapter.set_memory_service(memory_service)   # 只读 context / selector
task_manager.adapter.set_memory_gateway(memory_gateway)   # 写入入口
```

`NanobotAdapter` 内部应拆分：

- `_memory_service`: 只用于 `build_prompt_context()`、维护只读上下文。
- `_memory_gateway`: 用于强信号写入、AI patch 写入、未来 Dream proposal 写入。

### A2. 迁移强信号写入

现状问题：

- `NanobotAdapter._sync_strong_signal_memory()` 直接调用 `MemoryService.upsert_identity_memory()`。

改造目标：

```python
context = WriteContext(
    source="strong_signal",
    session_id=session_key,
    message_id=None,
    task_id=None,
    triggered_by="adapter",
)
memory_gateway.submit_identity_memory(...)
```

注意：

- `_sync_strong_signal_memory()` 当前没有 `session_key` 参数，需要加上。
- `run_task()` 调用处应改为 `_sync_strong_signal_memory(original_prompt, session_key)`。
- gateway 日志必须能看到 `source=strong_signal` 和 `session_id`。

### A3. 迁移 AI 记忆更新写入

现状问题：

- `_run_memory_update()` 直接调用 `MemoryService.apply_ai_response(raw)`。

改造目标：

- 新增 `MemoryWriteGateway.submit_ai_response(raw: str, context: WriteContext) -> WriteResult`。
- 或者新增 `MemoryService.parse_ai_response_to_patch(raw: str) -> MemoryPatch`，再由 gateway 调 `submit_patch()`。

推荐方案：

```text
MemoryService.parse_ai_response_to_patch(raw)
  -> MemoryPatch
MemoryWriteGateway.submit_patch(patch, context)
  -> WriteResult
```

这样可以保留 JSON 解析能力在领域服务，写入纪律仍由 gateway 统一执行。

### A4. 迁移 ExitAnalyzer 写入

现状问题：

- `ExitAnalyzer._persist_identity()` 直接调用 `upsert_identity_memory()`。
- `ExitAnalyzer._persist_preference()` 直接调用 `save_memory()`。

改造目标：

- `ExitAnalyzer` 构造函数接收 `MemoryWriteGateway`。
- identity 使用 `submit_identity_memory()`。
- preference 构造成 `MemoryPatch` 后调用 `submit_patch()`。

### A5. Gateway 执行真实策略

`MemoryWriteGateway.submit_patch()` 目前仍是 Phase 1 delegate。需要补齐：

- 使用 `settings.memory_gateway_min_confidence`，不是 `memory_min_confidence`。
- 使用 `settings.memory_gateway_max_items_per_patch`。
- 为 accepted item 补齐：
  - `source`
  - `source_session_id`
  - `source_message_id`
- 对 secret / 空内容 / prompt injection 疑似内容给出结构化 `Rejection.reason`。
- 高重要但低置信的项目进入 `needs_review`，不直接写 active。

### A6. 验收测试

新增或修改：

- `tests/test_memory_write_boundary.py`
- `tests/test_nanobot_adapter_memory_gateway.py`
- `tests/test_exit_analyzer_memory_gateway.py`

必须覆盖：

- adapter 强信号调用 gateway，而不是直接调用 service。
- `_run_memory_update()` 生成的 patch 通过 gateway 写入。
- ExitAnalyzer preference 不再直接 `save_memory()`。
- `memory_gateway_min_confidence` 生效。
- `memory_gateway_max_items_per_patch` 生效。
- accepted memory 写入 provenance。

验收命令：

```bash
pytest tests/test_memory_write_boundary.py -q
pytest tests/test_nanobot_adapter.py tests/test_exit_analyzer_memory_gateway.py -q
pytest tests/test_53_phase1_verification.py -q
```

## 3. Phase B：实现 session_search 冷 recall

**优先级:** P1  
**目标:** UI 开关打开后，agent 真的能通过受控工具搜索历史聊天。  
**安全重点:** 这是把本地聊天历史片段送入 LLM 上下文，必须默认关闭、限范围、脱敏、限长。

### B1. 新增纯搜索服务

新增文件：

- `core/memory/session_search.py`

建议模型：

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
    score: float = 0.0

class SessionSearchService:
    def search(
        self,
        query: str,
        *,
        current_session_id: str,
        scope: SessionSearchScope,
        limit: int,
    ) -> list[SessionSearchResult]:
        ...
```

要求：

- 空 query 拒绝。
- 默认只搜 current session。
- `all_sessions` 仅在 settings 和 tool 参数都允许时启用。
- 每条结果裁剪到 `memory_session_search_max_result_chars`。
- 总输出裁剪到 `memory_session_search_total_budget_chars`。
- 复用现有敏感信息清洗逻辑，至少清洗 API key、bearer token、email。

### B2. ChatRepo 增加搜索能力

修改文件：

- `core/storage/chat_repo.py`

建议先实现 LIKE 搜索，后续再加 FTS5：

- `search_messages(query, session_id=None, limit=10)`
- 返回 `ChatMessage` 列表。
- 按 `created_at DESC` 或粗略匹配分数排序。

如果加 FTS5：

- 表名建议 `chat_message_fts`。
- 需要处理已有消息回填。
- SQLite 不支持 FTS5 时自动降级 LIKE。

### B3. 新增 nanobot Tool wrapper

新增文件：

- `core/agent/tools/session_search_tool.py`
- `core/agent/tools/__init__.py` 如不存在则创建。

前置任务：

- 先查看 `lib/nanobot` 当前 Tool 协议，确认字段和注册方式。
- 不要假设普通 Python class 就能被 nanobot 调用。

工具行为：

- name: `session_search`
- input:
  - `query`
  - `scope`
  - `limit`
- output:
  - markdown 或 JSON，必须短小。
  - 明确标注“来自本地聊天历史检索”。

### B4. Adapter 注册工具

修改文件：

- `core/agent/nanobot_adapter.py`

规则：

- `settings.memory_session_search_enabled == False` 时不注册。
- 注册时绑定当前 `session_key`，默认只能搜当前 session。
- 如果 tool 调用传 `all_sessions`，但设置不允许，则拒绝。

### B5. UI 文案补强

修改文件：

- `ui/settings_window.py`

当前文案已经提到“会向 LLM 发送历史片段”，方向正确。需要补充 tooltip：

- 默认关闭。
- 开启后 agent 可主动检索本地聊天历史。
- 检索结果会进入当前 LLM provider 上下文。
- 可以限制为当前会话。

### B6. 验收测试

新增：

- `tests/test_session_search.py`
- `tests/test_session_search_tool.py`

必须覆盖：

- 默认 disabled 时 adapter 不注册工具。
- enabled 时注册 `session_search`。
- current_session 不返回其他 session 消息。
- all_sessions 受设置控制。
- 单条和总长度预算生效。
- token/email 脱敏。
- FTS5 不可用时 LIKE fallback 可用。

## 4. Phase C：冻结 Hot Memory Bundle

**优先级:** P2  
**目标:** 让 hot memory 和 cold recall 在代码结构上分开，而不是都塞进 `retrieved_memories`。

### C1. 扩展 PromptContextBundle

修改文件：

- `core/memory/memory_schema.py`

新增字段：

```python
project_context: str = ""
memory_budget_report: dict[str, int] = Field(default_factory=dict)
```

注入顺序建议：

```text
User Profile
System Profile
Project Context
Current Session Summary
Relevant Past Memory
Available Skills
```

### C2. MemorySelector 使用分层预算

修改文件：

- `core/memory/memory_selector.py`

预算规则：

- user_profile 使用 `memory_hot_user_profile_tokens`。
- system_profile 使用 `memory_hot_system_profile_tokens`。
- project_context 使用 `memory_hot_project_context_tokens`。
- episodic / retrieved memory 使用剩余 recall budget。

注意：

- 当前字段叫 tokens，但实现主要按 chars 算。要么统一改为 chars，要么新增估算转换。
- 推荐先在代码注释中明确：短期按 `tokens * 4` 估算 chars，后续再接 `TokenMeter`。

### C3. 项目上下文来源

`project_context` 初期只从 `MemoryType.PROJECT_MEMORY` 中筛选：

- `scope == 当前项目名` 优先。
- 没有当前项目名时使用 `global` 或相关 keyword 搜索。
- 不要把所有 project memory 无限制常驻。

### C4. 验收测试

修改或新增：

- `tests/test_memory_selector.py`
- `tests/test_memory_service.py`

必须覆盖：

- `PromptContextBundle` 有 `project_context`。
- project memory 不再混入 `retrieved_memories` 的唯一通道。
- 三类 hot budget 被消费。
- 长用户画像不会挤掉系统身份。
- `total_chars` 包含新字段。

## 5. Phase D：补齐 Skill 使用边界

**优先级:** P2  
**目标:** Skill 不只是“文件能创建/删除”，而是 agent 能看见、能选择、能记录效果。

### D1. 接入 SkillSelector 到 prompt

修改文件：

- `core/agent/nanobot_adapter.py`
- `core/memory/memory_service.py` 或新增 `PromptContextAssembler`

推荐轻量方案：

- adapter 在 `build_prompt_context()` 后，把 `_skill_manager` 交给 `SkillSelector` 生成摘要。
- 写入 `bundle.active_skills`。
- `build_injection_text()` 已支持 active skills，无需大改。

示例：

```python
if self._skill_manager:
    bundle.active_skills = SkillSelector(self._skill_manager).build_skills_summary()
```

### D2. 记录 skill 使用结果

需要先确认 nanobot 是否能报告实际使用了哪个 skill。

可选实现：

1. 如果 nanobot hooks 能看到 skill/tool name：
   - tracker 记录 skill 名称。
   - 成功返回后 `SkillManager.record_result(skill_id, success=True, session_id=session_key)`。
   - 异常时记录失败。

2. 如果 nanobot 只能看到普通 tool：
   - 先只做 prompt 可见摘要。
   - 后续在 `lib/nanobot` skill loader 层补事件。

### D3. 防止 disabled skill 仍被加载

需要增加启动时体检：

- 扫描 `workspace/skills/*/SKILL.md`。
- 如果文件存在但 SQLite 中不是 active：
  - 删除或移动到 archive。
  - 写 skill maintenance report。

### D4. 验收测试

新增或修改：

- `tests/test_skill_prompt_injection.py`
- `tests/test_skill_usage_tracking.py`

必须覆盖：

- active skill 进入 `Available Skills`。
- disabled skill 不进入 prompt。
- archived skill 文件不存在。
- 若能追踪使用，成功/失败计数更新。

## 6. Phase E：MemoryLint 与可观测性

**优先级:** P2  
**目标:** 让“记忆是否健康”可被检查，而不是靠人工猜。

### E1. 新增 MemoryLintService

新增文件：

- `core/memory/memory_lint.py`

检查项：

- duplicate: 相似内容重复。
- conflict: 同一 identity title 下存在冲突 active 事实。
- stale: 长期未更新。
- low_confidence: 低置信 active 记忆存在过久。
- projection_drift: 投影文件缺失或 header 缺失。
- orphan_projection: workspace 投影存在但 SQLite 无对应 active memory。

输出模型：

```python
class MemoryLintFinding(BaseModel):
    id: str
    severity: Literal["info", "warning", "error"]
    category: str
    memory_id: str | None = None
    message: str
    recommendation: str
```

### E2. 接入维护任务

修改文件：

- `core/memory/memory_maintenance.py`
- `app/main.py`

规则：

- `memory_lint_enabled == True` 时维护周期运行。
- 只生成 report，不自动删除或改写，除非后续有明确策略。

### E3. 验收测试

新增：

- `tests/test_memory_lint.py`

必须覆盖：

- duplicate finding。
- conflict finding。
- stale finding。
- projection missing/header missing。
- disabled 时维护任务不运行 lint。

## 7. Phase F：Project Wiki Projection

**优先级:** P3  
**目标:** 给项目记忆一个更适合人读和 agent 读的稳定视图。

新增或修改：

- `core/memory/memory_projection.py`
- 可选新增 `core/memory/project_wiki_projection.py`

输出：

```text
workspace/memory/MEMORY.md        # nanobot 兼容入口
workspace/memory/wiki/index.md    # 当前项目知识索引
workspace/memory/wiki/log.md      # 按时间记录的项目事实变化
```

规则：

- SQLite 仍是权威源。
- wiki 文件全部带 generated header。
- log 只记录 active/deprecated 变更摘要，不存敏感信息。

## 8. 分阶段实施顺序

### 第一批：必须先做

1. Adapter 强信号写入接入 `MemoryWriteGateway`。
2. AI 记忆更新接入 `MemoryWriteGateway`。
3. ExitAnalyzer 接入 `MemoryWriteGateway`。
4. Gateway 使用 `memory_gateway_*` 设置并写入 provenance。
5. 增加边界测试，证明业务写入不绕过 gateway。

完成后，才能说“长期记忆写入边界清晰”。

### 第二批：补 Hermes 式冷 recall

1. 新建 `SessionSearchService`。
2. 给 `ChatRepo` 增加搜索。
3. 实现 nanobot `session_search` Tool wrapper。
4. adapter 按设置注册工具。
5. 补脱敏、限长、scope 测试。

完成后，才能说“hot memory 和完整历史边界清晰”。

### 第三批：让 prompt 结构清晰

1. `PromptContextBundle` 新增 `project_context`。
2. `MemorySelector` 消费 hot memory budget。
3. active skills 注入 `Available Skills`。
4. 增加 prompt context snapshot 测试。

完成后，才能说“模型每次看到什么记忆是清晰的”。

### 第四批：健康检查和 wiki

1. 实现 `MemoryLintService`。
2. 接入 maintenance report。
3. 实现 Project Wiki Projection。

完成后，才能说“记忆系统可审计、可维护”。

## 9. 完成定义

### 9.1 代码级完成定义

- `rg "upsert_identity_memory\\(|save_memory\\(|apply_patch\\(|apply_ai_response\\(" core app ui` 中，业务层直接调用要么消失，要么有明确注释说明是允许例外。
- `memory_gateway_min_confidence` 和 `memory_gateway_max_items_per_patch` 有真实测试覆盖。
- 开启 `memory_session_search_enabled` 后，agent 可见 `session_search` 工具。
- 关闭 `memory_session_search_enabled` 后，agent 不可见该工具。
- `PromptContextBundle` 明确区分 user/system/project/session/retrieved/skills。
- active skill 能进入 prompt，disabled skill 不能进入 prompt。

### 9.2 用户体验完成定义

- 用户在设置页能理解：
  - 哪些记忆会常驻 prompt。
  - session_search 会把历史片段送入 LLM。
  - Dream 在 Lobuddy 模式下被禁用。
  - skill 自动候选默认关闭。
- 用户不会看到一个开启后无效果的设置项。

### 9.3 测试完成定义

至少新增或更新以下测试：

```text
tests/test_memory_write_boundary.py
tests/test_nanobot_adapter_memory_gateway.py
tests/test_exit_analyzer_memory_gateway.py
tests/test_session_search.py
tests/test_session_search_tool.py
tests/test_memory_selector.py
tests/test_skill_prompt_injection.py
tests/test_memory_lint.py
```

建议总验收命令：

```bash
pytest tests/test_53_phase1_verification.py -q
pytest tests/test_memory_service.py tests/test_memory_selector.py -q
pytest tests/test_memory_write_boundary.py tests/test_nanobot_adapter_memory_gateway.py -q
pytest tests/test_session_search.py tests/test_session_search_tool.py -q
pytest tests/test_skill_manager.py tests/test_skill_prompt_injection.py -q
pytest tests/test_memory_lint.py -q
```

## 10. 不建议做的事

- 不要让 `MemoryService` 内部创建或调用 `MemoryWriteGateway`。
- 不要把 `session_search` 默认打开。
- 不要让 session_search 默认搜索所有 session。
- 不要用 Markdown 投影文件反向同步 SQLite，除非以后做明确的导入工具。
- 不要让 Dream 直接编辑 `USER.md`、`SOUL.md`、`MEMORY.md`。
- 不要自动 approve skill candidate，除非用户显式开启且审查链路完善。
- 不要只加 UI 开关而不接运行时行为。

## 11. 下一轮最小可交付版本

如果只做一轮，建议最小范围是：

1. `MemoryWriteGateway` 接管 adapter 和 ExitAnalyzer 的全部业务写入。
2. Gateway 写入 provenance。
3. `session_search` 的纯服务和 ChatRepo 搜索先完成，但 nanobot Tool 注册可以作为下一步。
4. `PromptContextBundle.project_context` 和 hot budget 生效。
5. active skills 注入 prompt。

这轮完成后，记忆系统可以达到：

```text
写入边界闭合
投影边界清晰
Dream 风险受控
hot memory 分层明确
skill 可见性明确
session_search 进入可实现状态
```

