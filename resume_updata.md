下面是可直接交给 opencode 执行的 `plan.md`。它基于你当前 Lobuddy 的实际状态：项目已可运行，已有聊天历史、个性/能力系统、多模态图片分析，但仍存在基础设施缺口、Qt Signal 耦合、任务状态未完全持久化，以及子 Agent 过重、未接入 nanobot 内置子 Agent / 流式输出 / 内置工具集 / Skills / 长期记忆等问题。

````md
# Lobuddy v2 Plan

> 目标：将 Lobuddy 从“可运行的桌宠 AI 应用”升级为“桌面常驻 Agent Runtime”
> 适用对象：opencode
> 开发原则：先做 runtime，再做玩法；先做可恢复与低消耗，再做更多能力；所有新增能力必须带验证点与验证方式

---

## 0. 项目目标

Lobuddy v2 的核心目标不是继续堆桌宠功能，而是完成以下升级：

1. **子 Agent 混合架构**
   - 轻量子 Agent：同进程、独立子会话、最小上下文、受限工具、结构化输出、用完即销毁
   - 隔离子 Agent：独立进程、独立配置、独立工作区、强隔离、用完即销毁

2. **任务流升级为可恢复状态机**
   - 不再只是“队列 + 执行 + 保存结果”
   - 需要支持状态持久化、崩溃恢复、事件驱动、流式过程反馈

3. **记忆系统升级**
   - 从“聊天历史 + 自动摘要”升级为：
     - Working Memory
     - Rolling Summary
     - Profile Memory
     - Workflow Memory

4. **上下文压缩与 Token 优化**
   - 不再默认全量注入 skill / 记忆 / 历史 / 工具结果
   - 改为默认按需加载最小必要上下文

5. **能力接入升级**
   - 接入 nanobot 的内置工具集
   - 接入流式输出
   - 接入 AgentHook 扩展
   - 建立 Skills 系统
   - 预留 MCP/A2A 扩展位

6. **可验证、可量化、可写简历**
   - 所有核心能力都要有 benchmark、trace、指标输出
   - 最终能沉淀为 AI 应用开发岗简历可写的工程成果

---

## 1. 当前项目判断

当前 Lobuddy 已具备以下基础：

- 可运行的桌宠 UI 与聊天任务面板
- 任务管理、SQLite 持久化、聊天历史、历史自动压缩
- 个性系统、能力系统、多模态图片分析
- 独立进程子 Agent（用于图片分析）
- 基础测试覆盖较全

但当前仍存在关键差距：

1. 子 Agent 过重，主要依赖 `multiprocessing.Process + 全新 Nanobot 实例 + 文件结果回传`
2. 尚未使用 nanobot 原生 `SubagentManager`
3. 未使用 nanobot 原生流式能力
4. 未启用 nanobot 内置工具集
5. EventBus 未真正接管核心层
6. 任务状态持久化与恢复机制不完整
7. 长期记忆、Skills、MCP 等能力尚未接入
8. token 消耗控制仍停留在“历史摘要”，没有系统级优化

---

## 2. 总体开发原则

### 2.1 架构原则

1. 保留 PySide6 UI，不重写前端壳
2. 保留 nanobot 作为底座，不推翻现有执行层
3. runtime 改造优先于玩法扩展
4. 所有跨层通信优先走事件，不直接绑 UI
5. 所有危险能力必须可审批

### 2.2 Token 原则

1. 默认不发上下文
2. 必须发时按需加载
3. 必须加载时只发最小版本
4. 所有大块工具输出 artifact 化
5. 所有记忆从“注入式”改为“检索式”
6. 所有 skill 从“全量注入”改为“懒加载”

### 2.3 子 Agent 原则

1. 轻量子 Agent 解决“快速委托、最小上下文、低成本”
2. 隔离子 Agent 解决“高风险、易阻塞、易崩溃任务”
3. 插拔式靠统一协议与注册机制，不靠必须新进程
4. 子 Agent 默认不回灌完整 transcript，只回结构化结果

---

## 3. 目标架构

## 3.1 Runtime 分层

- UI Layer
  - `PetWindow`
  - `TaskPanel`
  - `SettingsWindow`
  - `ApprovalDialog`
  - `StreamingMessageWidget`

- Application Layer
  - `TaskService`
  - `SessionService`
  - `MemoryService`
  - `SafetyService`
  - `TraceService`

- Runtime Layer
  - `TaskStateMachine`
  - `ContextPacker`
  - `ToolPolicy`
  - `SubagentRuntime`
  - `SkillSelector`
  - `ModelRouter`

- Protocol Layer
  - Native Tools
  - Skills
  - MCP Gateway
  - A2A Gateway（预留）

- Persistence Layer
  - SQLite
  - Artifact Store
  - Checkpoint Store
  - Trace Store

---

## 3.2 子 Agent 双通道架构

### A. 轻量子 Agent（In-Process）

定位：同进程、独立子会话、受限工具、最小输入、结构化输出、用完即销毁

适用任务：

- query rewrite
- classify
- summarize
- rank
- short plan
- retrieval planner
- 文档结构化抽取

特性：

- 同进程 `asyncio task`
- 独立 `sub_session_key`
- 不继承主会话完整 history
- 默认 `writeback_mode = result_only`
- 结果只作为 artifact 注回主 Agent

### B. 隔离子 Agent（Isolated Process）

定位：独立进程、独立配置、独立工作区、强隔离、用完即销毁

适用任务：

- image analysis
- code execution
- shell-heavy task
- 阻塞/高风险任务
- 可能污染/拖垮主进程的任务

特性：

- `multiprocessing.Process`
- 独立 Nanobot 实例
- 独立工作目录
- 独立配置项
- 结果通过文件/管道回传
- 保留现有图片分析方案，后续抽象化

---

## 3.3 子 Agent 协议

```python
class SubagentSpec(BaseModel):
    name: str
    runtime_type: Literal["in_process", "isolated_process"]
    purpose: str
    allowed_tools: list[str]
    input_schema: dict
    output_schema: dict
    writeback_mode: Literal["none", "summary_only", "result_only"]
    timeout_sec: int

class SubagentResult(BaseModel):
    subagent_name: str
    runtime_type: str
    success: bool
    artifact_id: str | None = None
    summary: str | None = None
    structured_output: dict | None = None
    error: str | None = None
```
````

### writeback_mode 规则

- `none`：结果不写回主会话，只供 runtime 内部使用
- `summary_only`：只写一句摘要
- `result_only`：只写结构化 artifact，不写完整 transcript

---

## 4. Token 优化总方案

## 4.1 必做的 8 项优化

### 1. Token 分账日志

每次 LLM 调用必须记录：

- system_tokens
- history_tokens
- skill_tokens
- memory_tokens
- tool_result_tokens
- user_input_tokens
- output_tokens
- total_tokens

### 2. Skill 懒加载

- 不允许一次性把全部 skills 塞给模型
- 改为：
  - 先读 skill index
  - 选 top-k
  - 再加载 skill 正文

### 3. 记忆检索化

- 不允许每次都注入全部长期记忆
- 改为：
  - recent turns
  - rolling summary
  - retrieved profile memory top-k
  - retrieved workflow memory top-k

### 4. 工具结果 artifact 化

- 原始 HTML / markdown / 大 JSON / 长日志不允许反复回灌
- 工具输出必须拆成：
  - raw artifact
  - compact projection
  - artifact pointer

### 5. 工具集按步骤收缩

- 不允许每轮都暴露全工具表
- 每步只给 1\~3 个相关工具

### 6. 子 Agent 不回灌 transcript

- 轻量子 Agent 默认只返回结构化结果
- 隔离子 Agent 默认只返回 artifact / summary

### 7. 小模型先路由，大模型做重任务

- 小模型做：
  - task classify
  - skill select
  - memory retrieve rerank
  - query rewrite
  - relevance judge
- 大模型做：
  - complex plan
  - final synthesis
  - difficult code / writing

### 8. 预算与止损

- `max_iterations`
- `max_tool_calls`
- `max_subagent_calls`
- `max_prompt_tokens`
- `max_failure_streak`
- 超预算后必须：
  - summarize
  - stop
  - ask human

---

## 4.2 ContextPacker 设计

每次主模型调用前，统一先过 `ContextPacker`：

```python
class PackedContext(BaseModel):
    core_system_prompt: str
    current_task: str
    selected_skills: list[str]
    recent_turns: list[dict]
    rolling_summary: str | None
    retrieved_memories: list[dict]
    projected_artifacts: list[dict]
```

### token budget 默认建议

- system: 800
- current_task: 400
- selected_skills: 1000
- recent_turns: 1200
- rolling_summary: 600
- retrieved_memories: 800
- projected_artifacts: 1200

总预算超限时，按顺序裁剪：

1. artifacts
2. retrieved memories
3. skills
4. recent turns
5. summary 永远保留最小版

---

## 4.3 Skill 设计

### 技能文件格式

`skills/*.md`

要求：

- YAML frontmatter
- description
- when_to_use
- allowed_tools
- input_schema
- output_schema
- examples

### 首批必须交付的 5 个 skills

1. document_summarizer
2. web_researcher
3. file_extractor
4. clipboard_rewriter
5. image_analyzer

---

## 5. 分阶段开发

# Phase 0：基线修复与可迭代底座

## 目标

先把当前项目从“能跑”修到“适合继续升级”。

## 开发任务

1. 修复当前已知高优先级 bug
2. 实现 `ui/settings_window.py`
3. 把任务状态和能力解锁持久化补完整
4. 建立统一 ID：
   - `run_id`
   - `task_id`
   - `session_id`
   - `agent_id`
5. 建 baseline benchmark 脚本

## 产出文件

- `core/services/task_service.py`
- `core/services/session_service.py`
- `core/services/settings_service.py`
- `ui/settings_window.py`
- `scripts/eval/baseline_run.py`

## 可验证点

1. `python -m app.main` 正常启动
2. 已有测试全部通过
3. 设置可修改、可持久化、重启后生效
4. task 状态与 ability 状态重启后不丢
5. 能生成 baseline token / latency 报告

## 验证方式

- `pytest -q`
- 手动创建任务，重启后检查 DB 与 UI 状态一致
- 跑 `python scripts/eval/baseline_run.py`
- 输出 `reports/baseline_metrics.json`

## Done Definition

- 所有高优先级 bug 修完
- 配置窗口可用
- 任务与能力持久化生效
- baseline 指标跑通

---

# Phase 1：子 Agent 混合架构

## 目标

完成轻量子 Agent + 隔离子 Agent 双通道架构。

## 开发任务

1. 抽象 `SubagentRuntime`
2. 实现：
   - `InProcessSubagentRuntime`
   - `IsolatedProcessSubagentRuntime`
3. 新增 `SubagentPolicyRouter`
4. 新增 `SubagentSpecRegistry`
5. 统一 `SubagentResult`
6. 轻量子 Agent 默认规则：
   - 独立 sub-session
   - 最小输入
   - 受限工具
   - 结构化输出
   - 不回灌 transcript

## 产出文件

- `core/agent/subagent_runtime.py`
- `core/agent/inprocess_runtime.py`
- `core/agent/isolated_runtime.py`
- `core/agent/subagent_policy.py`
- `core/agent/subagent_registry.py`
- `tests/test_subagent_runtime_mixed.py`

## 路由策略

- `rewrite/classify/summarize/rank/short_plan` -> `in_process`
- `image/code_exec/shell/heavy_blocking` -> `isolated_process`

## 可验证点

1. 文本总结任务走轻量子 Agent
2. 图片分析任务走隔离子 Agent
3. 两者都能将结果注入主任务流
4. 轻量任务平均启动延迟显著小于隔离任务
5. 子 Agent 失败不拖垮主进程

## 验证方式

- trace 中记录 `runtime_type`
- 用两组 demo 验证：
  - “总结这段文档”
  - “分析这张图片”
- 强制 kill 子进程，主应用仍可继续提交新任务

## Done Definition

- 双通道 runtime 可用
- 路由器可用
- 结果协议统一
- 基本回归测试通过

---

# Phase 2：任务流升级为可恢复状态机

## 目标

将现有队列执行流升级成可恢复状态机。

## 开发任务

1. 新建 `TaskStateMachine`
2. 定义统一状态：
   - PENDING
   - ROUTING
   - PLANNING
   - WAITING_APPROVAL
   - RUNNING_TOOL
   - RUNNING_SUBAGENT
   - SUMMARIZING
   - SUCCEEDED
   - FAILED
   - CANCELLED
3. 建 checkpoint store
4. 核心层用 EventBus 替代直接 Qt Signal
5. 支持 resume after crash
6. UI 仅消费事件

## 产出文件

- `core/runtime/task_state_machine.py`
- `core/runtime/checkpoint_store.py`
- `core/events/domain_events.py`
- `tests/test_task_state_machine.py`
- `tests/test_resume_after_crash.py`

## 可验证点

1. 每次状态转移可追踪
2. 中途崩溃后可恢复
3. 核心层测试不依赖 Qt
4. 事件日志可还原一次完整执行链

## 验证方式

- 在 `RUNNING_TOOL` 阶段强杀应用
- 重启后自动加载 checkpoint 并恢复
- trace 中能看到完整状态链

## Done Definition

- 状态机跑通
- checkpoint 生效
- UI 不再直绑核心执行流
- 崩溃恢复演示可用

---

# Phase 3：记忆系统升级

## 目标

把“聊天历史 + 自动摘要”升级为分层记忆系统。

## 开发任务

1. 建立四类 memory
   - `working_memory`
   - `rolling_summary`
   - `profile_memory`
   - `workflow_memory`
2. 建 memory write policy
3. 建 memory retrieve policy
4. 建 workflow experience store
5. 将 memory retrieval 接入 ContextPacker

## 产出文件

- `core/memory/profile_store.py`
- `core/memory/workflow_store.py`
- `core/memory/rolling_summary.py`
- `core/memory/memory_retriever.py`
- `tests/test_memory_retrieval.py`

## 写入策略

### hot path 直接写

- 用户明确偏好
- 审批结果
- 高价值任务结果
- 成功工具链

### background 异步写

- 对话摘要
- 失败经验
- 重复工作流模板

## 可验证点

1. 用户偏好可跨会话记住
2. 历史成功工作流可复用
3. 旧历史不再完整注入 prompt
4. memory retrieval 只返回相关 top-k

## 验证方式

- 多轮测试后重启应用，检查偏好召回
- 跑固定 workflow，第二次能复用已知路径
- trace 中查看 memory 注入体积

## Done Definition

- 分层 memory 可用
- 写入策略可用
- 检索策略可用
- 已接入 ContextPacker

---

# Phase 4：Token 优化主线

## 目标

将 token 消耗从“全量注入式”改为“按需最小上下文式”。

## 开发任务

1. 实现 token 分账
2. 上线 `ContextPacker`
3. skill 懒加载
4. memory 检索化
5. tool artifact 化
6. tool narrowing
7. model routing
8. iteration budget / stop-loss

## 产出文件

- `core/runtime/context_packer.py`
- `core/runtime/token_meter.py`
- `core/runtime/model_router.py`
- `core/tools/artifact_store.py`
- `core/skills/skill_index.py`
- `tests/test_context_packer.py`
- `tests/test_skill_lazy_loading.py`
- `tests/test_artifact_projection.py`

## 量化目标

1. 平均 prompt token 降低 >= 40%
2. 长会话场景 prompt token 降低 >= 50%
3. 平均延迟降低 >= 20%
4. 回答保真率不低于 baseline 的 85%

## 验证方式

- 设计固定 20 条 benchmark tasks
- 比较改造前后：
  - total tokens
  - prompt tokens
  - latency
  - task success rate
- 输出 `reports/token_optimization_report.json`

## Done Definition

- 4 个关键优化全部落地：
  - skill lazy loading
  - memory retrieval
  - artifact projection
  - model routing
- 指标达到目标

---

# Phase 5：流式输出 + Guardrails + HITL

## 目标

补齐 AI 应用最关键的可见性与安全性。

## 开发任务

1. 接入 nanobot 流式输出
2. 接入 AgentHook：
   - before_iteration
   - on_stream
   - on_stream_end
   - before_execute_tools
   - after_iteration
   - finalize_content
3. 新增桌宠细粒度状态：
   - THINKING
   - SEARCHING
   - READING
   - WAITING_APPROVAL
   - EXECUTING
4. 新增审批系统：
   - approve
   - reject
   - edit
5. 审批记录进入 memory

## 产出文件

- `core/hooks/runtime_hook.py`
- `core/safety/guardrails.py`
- `core/safety/approval_service.py`
- `ui/streaming_message_widget.py`
- `ui/approval_dialog.py`
- `tests/test_guardrails.py`
- `tests/test_human_approval_flow.py`

## 可验证点

1. 用户能看到流式文本/状态变化
2. 高风险工具调用必须弹审批
3. approve/reject/edit 三条路径都可走通
4. 审批结果影响后续决策

## 验证方式

- 普通搜索任务：验证流式输出
- 写文件任务：验证审批
- 拒绝后任务应优雅终止并说明原因
- 二次类似任务应体现历史审批偏好

## Done Definition

- streaming 可见
- 审批流程完整
- guardrails 生效
- 审批结果已入 memory

---

# Phase 6：工具、Skills、MCP 扩展

## 目标

让 Lobuddy 具备真正的 Agent 能力，而不只是聊天能力。

## 开发任务

1. 开放 nanobot 原生工具能力，但加安全边界
2. 完整接入 skills 系统
3. MCP Gateway 最小可用
4. A2A Gateway 留接口，不做重实现
5. 命令路由最小版：
   - `/new`
   - `/stop`
   - `/restart`

## 产出文件

- `core/tools/tool_policy.py`
- `core/protocols/mcp_gateway.py`
- `core/protocols/a2a_gateway.py`
- `skills/`
- `tests/test_tool_policy.py`
- `tests/test_mcp_smoke.py`

## 安全边界

- filesystem：仅 workspace allowlist
- shell：命令白名单 + 超时
- web：限制来源与抓取深度
- write_file：默认需审批

## 可验证点

1. 至少 5 个 skill 可调用
2. 至少 2 个原生工具真正可用
3. workspace 外文件访问被拦截
4. 危险 shell 命令被拒绝
5. MCP 至少能发现并调用一个外部工具

## 验证方式

- skill smoke tests
- tool policy tests
- MCP smoke test
- 手动验证危险路径被阻断

## Done Definition

- Lobuddy 可执行实际 agent 任务
- 内置工具可控开放
- skill 与 MCP 跑通

---

# Phase 7：Trace、评测、简历封装

## 目标

把能力变成可证明的结果，方便写简历与面试。

## 开发任务

1. 统一 trace schema
2. 统一指标统计
3. 建 benchmark 套件
4. 生成对外展示报告
5. 准备 3 个稳定 demo 场景

## 产出文件

- `core/observability/tracer.py`
- `scripts/eval/eval_tasks.py`
- `scripts/eval/eval_resume_metrics.py`
- `reports/lobuddy_v2_metrics.json`
- `reports/lobuddy_v2_demo.md`

## 核心指标

- task success rate
- avg latency
- first stream latency
- average prompt tokens
- token reduction rate
- memory hit rate
- resume success rate
- risky tool intercept rate
- subagent routing accuracy

## 必备 demo

1. 文档总结 + 回复草稿
2. 图片分析 + 结构化结论
3. 崩溃恢复任务继续执行

## 可验证点

1. 3 个 demo 稳定
2. benchmark 可重复跑
3. 指标文件可导出
4. 能沉淀简历话术

## 验证方式

- 连跑 20\~50 条 benchmark tasks
- 录制 3 段 demo
- 对指标设回归阈值

## Done Definition

- 指标可用
- trace 可用
- demo 可用
- 简历素材可用

---

## 6. 目录建议

```text
core/
  agent/
    subagent_runtime.py
    inprocess_runtime.py
    isolated_runtime.py
    subagent_policy.py
    subagent_registry.py
  runtime/
    task_state_machine.py
    checkpoint_store.py
    context_packer.py
    token_meter.py
    model_router.py
  memory/
    profile_store.py
    workflow_store.py
    rolling_summary.py
    memory_retriever.py
  hooks/
    runtime_hook.py
  safety/
    guardrails.py
    approval_service.py
  tools/
    tool_policy.py
    artifact_store.py
  protocols/
    mcp_gateway.py
    a2a_gateway.py
  services/
    task_service.py
    session_service.py
    settings_service.py
ui/
  settings_window.py
  approval_dialog.py
  streaming_message_widget.py
skills/
scripts/
  eval/
reports/
tests/
```

---

## 7. opencode 执行硬约束

1. 不允许直接重写整个项目
2. 不允许先做视觉/动画打磨
3. 每个 phase 必须：
   - 先产设计草案
   - 再改代码
   - 再补测试
   - 再跑验证
4. 任何新增核心模块都必须有：
   - 单元测试
   - 集成测试
   - smoke test
5. 任何 token 优化都必须有前后对比数据
6. 任何安全能力都必须有拒绝路径测试
7. 任何子 Agent 能力都必须明确：
   - runtime_type
   - allowed_tools
   - input_schema
   - output_schema
   - writeback_mode

---

## 8. 本计划最终验收标准

满足以下条件即视为 Lobuddy v2 核心完成：

1. 双通道子 Agent 架构可用
2. 可恢复任务状态机可用
3. 分层记忆系统可用
4. ContextPacker + token 优化链路可用
5. 流式输出 + 审批机制可用
6. 原生工具 / skills / MCP 最小链路可用
7. benchmark、trace、metrics、demo 全部可跑
8. 能产出简历级成果描述与量化指标

---

## 9. 简历导向成果目标

最终项目应能支撑以下方向的简历描述：

- 设计桌面常驻 Agent Runtime，支持轻量/隔离双形态子 Agent 混合调度
- 构建事件驱动、可恢复任务状态机，支持 checkpoint 与中断恢复
- 设计分层记忆系统与 token budget 驱动的上下文压缩策略
- 实现流式执行反馈、工具审批、guardrails 与协议化能力接入
- 通过 skill 懒加载、记忆检索化、artifact 投影等方案显著降低 token 消耗

---

```

这版 plan 的核心是两条主线：

第一条是 **子 Agent 混合架构**：当前项目已有多进程图片分析子 Agent，但 nanobot 原生还有更轻的 `SubagentManager`，而且你当前确实还没真正用上原生流式、原生工具集、Skills、长期记忆这些能力。:contentReference[oaicite:2]{index=2} :contentReference[oaicite:3]{index=3}

第二条是 **token 优化**：不是继续“更聪明地塞上下文”，而是默认不塞、按需加载、结果投影、skill 懒加载、记忆检索化、工具缩表和模型分层路由。这样才是这类 Agent 框架降耗最有效的方向。

你要是愿意，我下一条可以继续给你一版 **“opencode 执行任务拆解表”**，直接按 `Phase -> Task -> File -> 验收命令` 的形式展开。
```
