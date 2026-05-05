# Lobuddy 5.4 记忆系统边界补全计划

生成日期：2026-05-04  
目标版本：5.4  
适用范围：`core/memory/`、`core/agent/`、`app/main.py`、相关测试

## 1. 当前判断

经过 5.3 多轮改造后，Lobuddy 与 nanobot 的记忆系统边界已经基本清晰：

- nanobot 负责执行 agent 任务，不直接拥有 Lobuddy 长期记忆。
- Lobuddy 的长期记忆写入应统一经过 `MemoryWriteGateway`。
- `MemoryService` 是 SQLite 结构化记忆的持久化服务，但不应再被 adapter、ExitAnalyzer 等业务入口直接绕过 gateway 调用。
- `session_search` 已从 UI 空开关补齐为服务、Tool、ChatRepo 搜索与注册链路。
- hot memory 已开始按 profile、project context、session summary、retrieved memory、active skills 分层注入 prompt。
- skill 当前只完成“可见性边界”：agent 可以在 prompt 中看到 active skills；但“真实使用反馈”暂不闭合，因为 nanobot 当前没有可靠的 per-skill execution hook。

本轮 5.4 不应大改架构，而应完成最后几处边界补洞，尤其是 identity memory 的 provenance 入库。

## 2. 5.4 核心目标

5.4 的目标不是新增一套记忆系统，而是把已有边界做成运行时事实：

1. 所有长期记忆写入都必须经过 `MemoryWriteGateway`。
2. patch memory 和 identity memory 都必须把 `source`、`source_session_id`、`source_message_id` 持久化到 SQLite。
3. Gateway 阈值必须是 gateway 写入链路的唯一置信度入口。
4. ExitAnalyzer 不得保留无 gateway 的业务写入旁路。
5. session_search、hot memory、skill prompt visibility 的边界保持稳定，不再退化为文档能力。
6. skill 使用反馈不做伪闭环；等 nanobot 暴露可靠 hook 后再接入。

## 3. 已闭合问题清单

以下 finding 不应在 5.4 中重复返工，只需通过回归测试守住：

| Finding | 当前状态 | 说明 |
| --- | --- | --- |
| adapter 强信号写入绕过 gateway | 已闭合 | adapter 写入应走 `MemoryWriteGateway` |
| AI memory patch 绕过 gateway | 已闭合 | patch 应走 `submit_patch()`/`apply_gateway_patch()` |
| patch provenance 只改返回对象 | 已闭合 | patch 保存前应持久化 source/session/message |
| gateway 阈值被 `memory_min_confidence` 二次覆盖 | 已闭合 | gateway patch 应绕过 service 内部阈值 |
| session_search 只有 UI/setting | 已闭合 | 已补 service、Tool、注册链路与测试 |
| session_search Tool 测试环境不可导入 | 已闭合 | Tool 应有 nanobot 缺失时的测试友好 fallback |
| hot memory 预算未消费 | 已闭合 | `PromptContextBundle` 应含 project context 与预算报告 |
| hot project context 未进入 bundle | 已闭合 | project context 应明确进入 prompt 分层 |
| settings 中 gateway 字段重复定义 | 已闭合 | 保留单一定义 |
| ExitAnalyzer 无 gateway 旁路 | 基本闭合 | 构造函数应强制 gateway；5.4 继续补 session provenance |
| skill 只保存 manager 未进入 prompt | 已闭合 | active skills 应进入 prompt |
| skill 使用反馈未闭合 | 有意保留 | 不应伪造 record_result，等待 nanobot hook |

## 4. 5.4 必做改造

### 4.1 持久化 identity memory 的 session/message provenance

当前残留问题：

`MemoryWriteGateway.submit_identity_memory()` 已接管 identity 写入，但只把 `context.source` 传入 `MemoryService.upsert_identity_memory()`。`MemoryService.upsert_identity_memory()` 也不接收 `source_session_id` 和 `source_message_id`，导致用户名、宠物名、ExitAnalyzer identity 写入无法追溯到具体 session/message。

需要修改：

- `core/memory/memory_service.py`
  - 将 `upsert_identity_memory()` 签名扩展为：
    - `source: str = "ai"`
    - `source_session_id: str | None = None`
    - `source_message_id: str | None = None`
  - 新建 `MemoryItem` 时必须写入：
    - `source=source`
    - `source_session_id=source_session_id`
    - `source_message_id=source_message_id`
  - 如果命中已有 identity memory，也要明确策略：
    - 5.4 推荐记录“最近一次确认来源”：当 context 带 provenance 时，更新已有 item 的 `source/source_session_id/source_message_id/updated_at`。
    - 不引入完整 provenance event log，避免扩大范围。

- `core/memory/memory_write_gateway.py`
  - `submit_identity_memory()` 调用 `upsert_identity_memory()` 时传入：
    - `source=context.source`
    - `source_session_id=context.session_id`
    - `source_message_id=context.message_id`
  - 返回对象与 SQLite 读回对象必须一致。

验收标准：

- 通过 gateway 新建 identity memory 后，`MemoryService.get_memory()` 读回的 `source/source_session_id/source_message_id` 与 `WriteContext` 一致。
- 对已有 identity memory 再次确认时，最新 session/message provenance 可读回。

### 4.2 给 ExitAnalyzer identity/preference 写入补 session provenance

当前残留风险：

ExitAnalyzer 主路径已经传入 gateway，但如果它构造 `WriteContext` 时不带 session_id，SQLite 里仍然只能知道来源是 `exit_analysis`，不知道来自哪次 session。

需要修改：

- `core/memory/exit_analyzer.py`
  - `analyze_and_persist(session_id)` 应把 `session_id` 传入 `_persist_result()`。
  - `_persist_result(result, session_id)` 再传给 `_persist_identity()` 与 `_persist_preference()`。
  - `_persist_identity()` 构造：
    - `WriteContext(source="exit_analysis", session_id=session_id, triggered_by="exit_analysis")`
  - `_persist_preference()` 同样带 `session_id`。
  - 若当前函数已经有 session_id 参数但没有传递到 context，则只补传递，不改分析逻辑。

验收标准：

- ExitAnalyzer 产生的 identity/preference 写入都能通过 fake gateway 或 SQLite 读回验证 `source_session_id`。
- 不恢复任何 `gateway=None` 的 MemoryService 直写 fallback。

### 4.3 保持 gateway 阈值单一入口

5.3 已修复 patch 阈值二次覆盖，5.4 只需要守住：

- gateway patch 写入继续走 `apply_gateway_patch()`。
- `MemoryService.apply_patch()` 可以保留给非 gateway 内部调用或旧接口，但 adapter/ExitAnalyzer 不应直接调用它。
- identity memory 如有 confidence 字段，也应在 gateway 层完成策略判断，不在 service 层再次用 UI 旧阈值拒绝。

验收标准：

- `memory_gateway_min_confidence < memory_min_confidence` 时，通过 gateway 的合格 patch 不应被 service 拒绝。
- 测试必须读 SQLite，不能只断言返回对象。

### 4.4 session_search 边界只做回归，不新增复杂 recall

session_search 当前目标是 Hermes 式 cold history recall 的最小可用链路，不要在 5.4 继续扩张成 RAG 系统。

需要守住：

- setting 开启后 adapter 注册 `session_search` Tool。
- Tool 在没有完整 nanobot 依赖的测试环境仍可导入。
- ChatRepo 搜索返回有 session/message 边界的结果。
- Tool 不写长期记忆，只做外部 recall。

验收标准：

- `tests/test_session_search.py`
- `tests/test_session_search_tool.py`

### 4.5 hot memory 与 prompt bundle 边界只做回归

需要守住：

- `PromptContextBundle` 保持以下分层：
  - `user_profile`
  - `system_profile`
  - `project_context`
  - `session_summary`
  - `retrieved_memories`
  - `active_skills`
  - `memory_budget_report`
- `memory_hot_user_profile_tokens`
- `memory_hot_system_profile_tokens`
- `memory_hot_project_context_tokens`
- `memory_fixed_budget_tokens`

验收标准：

- 每个预算字段至少有一个测试证明被运行时消费。
- project context 不应混入 user profile 或 retrieved memories。

### 4.6 skill 使用反馈暂不强行闭合

当前状态：

- `SkillSelector.build_skills_summary()` 已把 active skills 注入 prompt。
- `SkillManager.record_result()` 仍没有可靠调用点。

5.4 决策：

- 不根据 prompt 中出现的 skill 名称推断使用成功。
- 不根据任务成功整体结果批量给 skill 记账。
- 不用字符串匹配 nanobot 输出伪造 per-skill usage。
- 保留代码注释或设计文档说明：skill usage feedback 需要 nanobot 暴露 tool/skill execution event 后再接入。

后续可选 hook：

- nanobot tool call event
- skill execution trace
- adapter result metadata
- structured run telemetry

验收标准：

- 没有新增虚假的 `record_result()` 调用。
- 文档或测试明确当前边界：skills are prompt-visible, not usage-accounted。

## 5. 推荐实现顺序

1. 修改 `MemoryService.upsert_identity_memory()` 的签名与保存逻辑。
2. 修改 `MemoryWriteGateway.submit_identity_memory()`，把 `WriteContext` provenance 传到底。
3. 补 `tests/test_memory_write_boundary.py`：
   - identity 新建 provenance 入库；
   - identity 已存在时 provenance 更新或保持策略；
   - 返回对象与 `get_memory()` 读回一致。
4. 修改 ExitAnalyzer 的 session_id 传递链路。
5. 补 ExitAnalyzer/gateway 捕获测试，证明 context 带 session_id。
6. 跑 memory、session_search、selector、skill selector 回归。
7. 确认没有新增 MemoryService 直写入口。

## 6. 建议测试用例

### 6.1 identity provenance 入库

测试目标：

- `gateway.submit_identity_memory()` 接收：
  - `WriteContext(source="strong_signal", session_id="session-1", message_id="message-1")`
- SQLite 读回：
  - `source == "strong_signal"`
  - `source_session_id == "session-1"`
  - `source_message_id == "message-1"`

### 6.2 identity 已存在时 provenance 策略

测试目标：

- 第一次写入 identity memory。
- 第二次用不同 session/message 再次确认同一 identity。
- 根据 5.4 选定策略断言：
  - 推荐：读回为最近一次 provenance。

### 6.3 ExitAnalyzer 带 session_id 写入 gateway

测试目标：

- 用 fake gateway 捕获 `submit_identity_memory()` 或 `submit_patch()` 的 `WriteContext`。
- 调用 `analyze_and_persist(session_id="session-exit-1")`。
- 断言 context：
  - `source == "exit_analysis"`
  - `session_id == "session-exit-1"`
  - `triggered_by == "exit_analysis"`

### 6.4 无 MemoryService 旁路

测试目标：

- 搜索 adapter 与 ExitAnalyzer 中的业务写入。
- 不允许出现新的：
  - `memory_service.save_memory(...)`
  - `memory_service.apply_ai_response(...)`
  - `memory_service.upsert_identity_memory(...)`
- 例外：`MemoryWriteGateway` 内部可以调用 `MemoryService`。

## 7. 验收命令

```bash
pytest tests/test_memory_write_boundary.py -q
pytest tests/test_session_search.py tests/test_session_search_tool.py -q
pytest tests/test_memory_selector.py tests/test_memory_lint.py tests/test_skill_selector.py -q
pytest tests/test_53_phase1_verification.py -q
python -m py_compile core/agent/nanobot_adapter.py core/agent/tools/session_search_tool.py core/memory/memory_write_gateway.py core/memory/memory_service.py core/memory/exit_analyzer.py
```

如果 `tests/test_nanobot_adapter.py` 因本地缺少 `loguru`、`trio`、`tiktoken` 等 nanobot 测试依赖失败，不应直接判定为 memory 边界失败；但需要在最终说明中记录环境缺口。

## 8. 非目标

5.4 不做以下事项：

- 不重写 MemoryService。
- 不新增第二套 memory repository。
- 不把 session_search 扩展成 embedding/RAG。
- 不改变 nanobot 子模块内部实现。
- 不伪造 skill 使用结果。
- 不把 `data/memory/SYSTEM.md` 的运行时投影变化混入本次实现提交，除非该文件变化是明确需要的。

## 9. 完成定义

当以下条件全部满足时，5.4 记忆系统边界可以视为清晰：

- adapter、AI patch、strong signal、ExitAnalyzer 的长期记忆写入都经过 `MemoryWriteGateway`。
- patch memory 与 identity memory 的 `source/source_session_id/source_message_id` 都能从 SQLite 读回。
- gateway 阈值是 gateway 写入链路唯一生效阈值。
- session_search 是只读 cold recall 工具，不写长期记忆。
- hot memory 的 profile/project/session/retrieved/skills 分层在 prompt bundle 中明确存在。
- skill 已做到 prompt 可见，但未伪造 usage feedback。
- 测试不仅断言返回对象，也断言持久化读回结果。

