# Lobuddy v2 可行版升级计划（极致版：记忆系统与Token降本做到极致）

> 基于 `resume_updata.md` 和 `now.md` 当前状态总结的现实可行版本
> 适用对象：opencode / Sisyphus
> 核心原则：**先让用户感知到价值，再逐步完善基础设施**
> **本次极致化重点**：
> - **记忆系统**：从"关键词匹配 + 四重分层"升级为"语义检索 + 冲突检测 + 跨会话关联 + 遗忘算法 + 激活抑制 + nanobot原生能力整合"
> - **Token降本**：从"六项策略30%降低"升级为"硬门槛>=35%（普通场景）/>=50%（长会话场景），力争>=40%（普通场景stretch goal）"
> - **约束**：不增加Phase数量（保持4个Phase），保持文档可执行性
>
> **⚠️ 文档性质声明**：本文档是**实现计划（Implementation Plan）**，而非当前可运行手册。文档中列出的测试文件、脚本、模块均为**待创建**目标，需在 4 个 Phase 执行期间逐步落地。

---

## 0. 为什么需要"更可行"的版本

原 `resume_updata.md` 共 8 个 Phase，覆盖子 Agent 混合架构、可恢复状态机、四重记忆系统、8 项 Token 优化、流式输出 + 审批 + Guardrails、Skills + MCP、Trace + 评测。这是一个**优秀的架构蓝图**，但作为执行计划存在以下问题：

1. **Phase 数量过多**（8 个），即使每个 Phase 2-3 天，也需要 2-3 周全职开发
2. **Phase 2 可恢复状态机** 在单用户桌面应用中属于过度设计——用户强杀应用后通常不会期望任务继续
3. **Phase 5 审批系统** 对于个人桌宠过于重型，用户更关心的是"Agent 能做什么"而非"每步都要审批"
4. **大量目录和文件需要从零创建**，与现有代码的兼容成本被低估

**本次增强策略**：
- 保留 4 Phase 结构（不增加数量）
- **Phase 1 和 Phase 2 基本不变**（基线修复 + 子 Agent 双通道）
- **Phase 3 大幅增强**：从"纯流式输出"升级为"流式输出 + 记忆系统极致四重分层 + Token 优化十七项极致策略"
- **Phase 4 增强评测维度**：加入记忆命中率和 Token 降低率指标

## 0.2 Definition of Done（端到端验证命令）

本计划完成的判定标准不是"文档写完"，而是以下端到端命令全部通过：

```bash
# 1. 安装依赖（含 memory extra）
pip install -e ".[memory]"

# 2. 启动应用
python -m app.main

# 3. 验证记忆系统：提交"我喜欢Python"，再提交"帮我写段代码"，验证输出包含Python
# （手动测试，需人工确认）

# 4. 验证 Token 优化：运行 benchmark，对比 baseline
python scripts/eval/baseline_run.py        # 生成 reports/baseline_metrics.json
python scripts/eval/eval_tasks.py          # 生成 reports/after_metrics.json
python scripts/eval/compare_metrics.py \
  --before reports/baseline_metrics.json \
  --after reports/after_metrics.json \
  --output reports/comparison_report.md

# 5. 验证指标：
# - token 降低率 >= 35%（普通场景硬门槛），>= 50%（长会话硬门槛），力争 >= 40%（普通场景 stretch goal）
# - 记忆命中率 >= 70%（Top-5 包含相关记忆的任务比例）
# - 以上指标通过对比报告自动计算

# 6. 验证 DB migration
sqlite3 data/lobuddy.db "SELECT * FROM schema_version ORDER BY applied_at DESC LIMIT 1;"
# 预期输出：version=2, checksum=xxx

# 7. 验证回滚（如需）
cp data/backup/lobuddy_v1.db data/lobuddy.db
# 应用应能正常启动，但记忆系统功能降级
```

---

## 0.3 v2.0 验收矩阵（单页速查）

| 维度 | v2.0 必做（阻塞验收） | v2.1 延期（不阻塞） |
|------|---------------------|-------------------|
| **记忆系统** | P0: `embedding_engine` + `memory_retriever` + `working_memory_repo` + `profile_memory`（基础设施）<br>P1: `rolling_summary` + `workflow_memory`（功能层） | P2: `session_linker` + `embedding_quantizer` + `temporal_parser` |
| **Token优化** | A层 12 项全部落地（阻塞项，缺一不可） | C层 4 项实验验证（可选，失败不阻塞） |
| **Token优化** | B层可用项条件实施（可用则 v2.0，不可用则 v2.1） | B层不可用项跳过（不阻塞 v2.0） |
| **指标** | 记忆命中率 >= 70% | 量化压缩 Recall@k >= 95% |
| **指标** | token 降低 >= 35%（普通），>= 50%（长会话） | 力争 >= 40%（stretch goal） |
| **基础设施** | DB migration + schema_version + 备份 | 归档清理自动化 |
| **测试** | A层全部 + B层可用项通过（不可用项需附 Provider 能力验证记录） | C层 + v2.1 项测试可选（失败不阻塞） |
| **依赖** | `pip install -e ".[memory]"` 可安装 | 无 |

**硬门槛（缺一不可）**：
1. A层 12 项 Token 优化全部可用
2. P0 记忆文件全部可用（embedding + retriever + working + profile）
3. 记忆命中率 >= 70%
4. token 降低 >= 35%（普通场景）且 >= 50%（长会话场景），二者需同时满足
5. DB migration 可执行且可回滚

---

## 0.1 不可删除的最小核心（原版中必须保留的底线能力）

### 最小可恢复任务状态
- 任务状态（QUEUED/RUNNING/SUCCESS/FAILED/CANCELLED）必须**实时持久化到 SQLite**
- 应用重启后能看到上次未完成任务列表（QUEUED/RUNNING/FAILED）
- 强杀后未完成任务状态标记为 FAILED，可手动重试
- 用户主动取消后状态变为 CANCELLED

### 四重记忆系统（极致版：从关键词匹配到语义智能）
| 层级 | 定位 | 存储内容 | 检索方式 | 核心升级 |
|------|------|---------|---------|---------|
| **Working Memory** | 显式偏好 | 用户明确声明的偏好 | **语义检索** + 关键词 fallback | 冲突检测：用户说"我喜欢A"后又说"我讨厌A"→自动标记冲突并提示 |
| **Rolling Summary** | 对话摘要 | 当前会话的滚动摘要 | 时间衰减权重 | 跨会话关联："上次那个脚本"能关联到历史会话的摘要 |
| **Profile Memory** | 用户画像 | 推断的用户属性 | **Embedding相似度**检索 | 画像演化：confidence动态调整，长期验证 |
| **Workflow Memory** | 工作流复用 | 成功任务执行模式 | **意图匹配** + 参数泛化 | 工作流参数化："查[X]资料→总结→写[Y]代码" |

### 记忆系统极致化特性（新增）
| 特性 | 说明 | 实现方式 |
|------|------|---------|
| **语义检索** | 用embedding替代关键词匹配 | 本地轻量模型（ sentence-transformers/all-MiniLM-L6-v2，22MB） |
| **冲突检测** | 检测矛盾偏好并提示用户 | 语义反义检测 + 显式确认机制 |
| **跨会话关联** | "上次那个脚本"关联历史 | Session Linker：维护跨会话实体索引 |
| **遗忘算法** | 防止记忆无限增长 | LRU + 时间衰减 + 访问频率 + 重要性评分综合算法 |
| **激活/抑制** | 相关记忆激活，无关记忆抑制 | Attention机制：当前任务与记忆的注意力权重 |
| **时序感知** | 支持"昨天提到的方案"等时间查询 | 时间表达式解析 + temporal_tags索引 |
| **Embedding量化** | int8量化减少75%存储（实验性） | 量化器（计算min/max→scale/zero-point）+ int8存储 + 反量化回float32检索，需验证Recall@k损失<5% |
| **分层存储** | Hot/Warm/Cold三层存储策略 | 内存缓存 + SQLite + 归档文件 |
| **nanobot整合** | 复用Memory/Consolidator/Dream | 适配nanobot原生记忆钩子 |

### Token 优化极致化策略（十七项，分层实施）

> **⚠️ 重要声明**：以下策略按可落地性分为 A/B/C 三层，收益**不可简单叠加**（存在互斥和重叠），最终降本目标是**综合效果**：硬门槛普通场景>=35%、长会话>=50%，力争普通场景>=40%（stretch goal）。

#### A层：当前Provider可直接落地（高置信度）
| # | 策略 | 目标 | 预期降本 | 置信度 |
|---|------|------|---------|--------|
| A1 | **Token 分账** | 精确记录各模块token消耗 | 可观测 | 100% |
| A2 | **ContextPacker动态预算** | 根据模型上下文窗口动态分配预算 | -10~15% prompt | 95% |
| A3 | **Skill 懒加载** | 只加载相关skill | -15~20% skill tokens | 95% |
| A4 | **记忆语义检索** | 只检索相关记忆，降低噪音 | -10~15% memory tokens | 90% |
| A5 | **Tool Artifact 化** | 工具结果压缩存储 | -20~25% tool result tokens | 95% |
| A6 | **Tool Narrowing** | 每轮暴露1-3个最相关工具 | -8~10% tool schema tokens | 95% |
| A7 | **上下文去重** | 去除重复上下文 | -5~10% prompt | 90% |
| A8 | **响应缓存** | 高频查询零token成本（带freshness策略） | -100% (命中时) | 85% |
| A9 | **max_output_tokens动态上限** | 根据任务类型限制输出长度 | -20~30% 简单任务 | 95% |
| A10 | **命令型请求本地 bypass** | 本地规则直接响应，不走LLM | -100% (命中时) | 90% |
| A11 | **Query Normalization缓存** | 语义等价查询共享缓存 | -100% (命中时) | 80% |
| A12 | **Tool Schema按需注入** | 非全量暴露，按轮次动态注入 | -5~8% tool schema | 90% |

#### B层：依赖Provider特性，条件实施（中置信度）
| # | 策略 | 目标 | 预期降本 | 前提条件 |
|---|------|------|---------|---------|
| B1 | **Prompt Caching** | 复用system prompt/skills的KV Cache | -15~25% prompt (重复调用) | Provider支持（OpenRouter Claude/OpenAI GPT-4o） |
| B2 | **模型分层路由** | 小模型分类路由，大模型执行复杂任务 | -30~40% 简单任务成本 | 配置多模型API Key |
| B3 | **自适应工具压缩** | 根据预算动态调整摘要长度 | -10~15% tool result | 实现AdaptiveCompressor |

**B层不可用项 WONTFIX 规范**：
若 B 层某项因 Provider 不支持而无法实施，需按以下流程标记 WONTFIX：
1. **验证记录**：`reports/provider_capability_{strategy_name}.md`
   - 测试的 Provider 名称和 API 版本
   - 不支持的功能点（如 "Prompt Caching header 返回 400"）
   - 测试时间戳和请求/响应摘要（脱敏）
2. **降级方案**：文档化回退行为（如 "Prompt Caching 不可用时，全量传递 system prompt"）
3. **审批**：WONTFIX 需至少 1 名维护者确认并签字（Git commit message 或 PR review）
4. **产出文件**：`reports/provider_capability_prompt_caching.md`（示例）

#### C层：实验性/需验证（低置信度，PoC后决定是否投入）
| # | 策略 | 目标 | 预期降本 | 风险提示 |
|---|------|------|---------|---------|
| C1 | **KV Cache复用** | 对话历史增量更新，不重复编码 | -10~20% prompt (长会话) | ⚠️ 大多数托管API不提供可控KV key，需验证Provider能力 |
| C2 | **Embedding int8量化** | 减少75%存储，CPU检索加速 | 存储降本，检索延迟不确定 | ⚠️ 需验证量化后Recall@k损失<5% |
| C3 | **增量更新** | 只传递新增消息，不重复完整历史 | -5~10% prompt | ⚠️ 与B1(Prompt Caching)有重叠，需互斥计算 |
| C4 | **Prompt模板压缩** | 去除冗余空白/换行/长变量名 | -3~5% system prompt | ⚠️ 收益有限，不影响可读性前提下实施 |

> **综合目标**：A层全部落地 + B层条件实施 = **35~45% token降本**（长会话≥50%）
> 
> **统计口径**：同一任务集、同一模型、同温度、同工具可用性下，对比Phase 1 baseline的prompt tokens中位数

### 新增依赖声明
以下依赖需在 `pyproject.toml` 中声明：

```toml
[project.optional-dependencies]
memory = [
    "sentence-transformers>=2.2.0",  # Embedding引擎（22MB模型，CPU可用）
    "dateparser>=1.1.0",             # 时序表达式解析
    "numpy>=1.24.0",                 # 量化压缩（开发环境已通常包含）
]
```

> **安装方式**：`pip install -e ".[memory]"` 启用记忆系统极致化特性
> 
> **降级方案**：若 `sentence-transformers` 安装失败，自动回退到关键词匹配（功能降级，不影响主流程）

### 最小核心 → Phase 映射（1:1 闭环）

| 最小核心 | 所在 Phase | 产出文件 | 验证命令 |
|---------|-----------|---------|---------|
| 任务状态实时持久化 | Phase 2.6 | `core/runtime/task_checkpoint.py` | `pytest tests/test_task_checkpoint.py -v` |
| 四重记忆系统 | Phase 3.5 | `core/memory/` 四文件 | `pytest tests/test_memory_system.py -v` |
| Token 优化十七项 | Phase 3.5 | `core/runtime/context_packer.py` 等 | `pytest tests/test_token_optimization.py -v` |

---

## 1. 当前项目状态（精简版）

### 已具备（可直接使用）
- ✅ 可运行的桌宠 UI（PySide6）+ 聊天面板 + 系统托盘 + 快捷键
- ✅ 任务管理 + SQLite 持久化 + 聊天历史 + 历史自动压缩
- ✅ 个性系统 + 能力系统（但未持久化）+ 多模态图片分析
- ✅ 独立进程子 Agent（图片分析）+ 基础测试覆盖
- ✅ nanobot 底座完整可用

### 关键缺口（阻碍价值释放）
1. `app/main.py` 有未定义变量 Bug，部分信号未连接
2. 无设置窗口 UI，用户无法修改配置
3. 能力解锁状态重启后丢失（未持久化）
4. **未启用 nanobot 内置工具集**——Lobuddy 目前只是个聊天机器人
5. **未使用流式输出**——用户盲等，无进度反馈
6. **子 Agent 只有隔离进程一种方案**——简单任务启动开销过大
7. **记忆系统仅停留在"聊天历史"，无分层、无检索、无画像**
8. **Token 消耗无控制，全量注入导致长会话成本指数增长**

---

## 2. 简化后的 4 个 Phase

```
Phase 1: 基线修复与价值解锁（修bug + 设置窗口 + 工具开放 + 最小安全拦截）
Phase 2: 子Agent双通道（轻量 + 隔离 + 任务状态持久化）
Phase 3: 智能上下文引擎（流式输出 + 极致四重记忆系统 + 十七项Token优化）
Phase 4: Skills、评测与简历沉淀
```

---

# Phase 1: 基线修复与价值解锁

## 目标
让用户能真正感受到 Lobuddy 是个 Agent，而不只是聊天机器人。

## 核心任务

### 1.1 修复现有高优先级 Bug
- [ ] 修复 `app/main.py:120` `on_pet_level_up` 中未定义 `pet` 变量
- [ ] 修复 `core/models/chat.py:28` `ChatSession.messages` 可变默认列表
- [ ] 修复 `core/storage/pet_repo.py` `get_or_create_pet` 忽略传入 `pet_id`
- [ ] 修复 `core/tasks/task_manager.py` 任务状态/时间戳未持久化
- [ ] 连接 `pet_window` / `system_tray` 中未连接的 `settings_requested` / `about_requested` / `close_requested` 信号

**产出**: 代码修复，现有测试通过

### 1.2 实现 `ui/settings_window.py`
- [ ] 表单展示当前配置（宠物名称、LLM API Key / Base URL / Model、任务超时、弹层时长）
- [ ] 修改后保存到 `settings_repo`（SQLite），同时导出到 `.env` 做备份
- [ ] **配置真源**: `settings_repo` 是唯一真源，`.env` 仅作启动备份和外部编辑器兼容
- [ ] **启动加载顺序**：`bootstrap.py` 启动时先从 `.env` 加载默认值，再用 `settings_repo` 覆盖（若 DB 中有值）
- [ ] 重启后配置保持
- [ ] 从托盘 "Settings" 菜单可打开

**产出文件**: `ui/settings_window.py`

### 1.3 能力解锁持久化
- [ ] 在 SQLite 中新增 `unlocked_abilities` 表
- [ ] `ability_system.py` 加载/保存解锁状态
- [ ] 重启后能力状态不丢失

**产出**: `core/storage/ability_repo.py` 或扩展 `settings_repo`

### 1.4 开放 nanobot 内置工具集（核心价值）
这是本 Phase **最重要的任务**——让 Lobuddy 从聊天机器人变成真正的 Agent。

当前 `NanobotAdapter` 限制工具注册的做法：
```python
# 当前代码：只注册 custom_tool，限制了 Agent 能力
bot._loop.tools.register(custom_tool)
```

改为：
```python
# 保留现有 AnalyzeImageTool
# 根据配置选择性注册 nanobot 内置工具：
# - filesystem 工具（read_file/write_file/edit_file/list_dir/glob_dir/grep_file）
# - web 工具（web_search/web_fetch）
# - shell 工具（exec，默认关闭，需用户显式开启）
```

**安全边界（Phase 1 必须同时落地，不能推迟到 Phase 3）**：
- `restrictToWorkspace=True` — 所有文件操作限制在工作区
- shell 工具默认关闭，设置窗口可开启
- write_file 操作默认限制在工作区
- **危险命令拦截**：`rm -rf /`、`format`、`del /s /q` 等直接拒绝
- **工作区外拦截**：任何访问 `workspace` 外路径的操作拒绝并提示

**产出文件**: 
- `core/tools/tool_policy.py` — 工具启用策略
- `core/safety/guardrails.py` — 最小安全拦截（危险命令 + 路径越界）

### 1.5 Token 计量基础（Phase 1 先落地记录能力）
- [ ] 每次 LLM 调用记录 token 消耗（prompt / completion / total）
- [ ] 按模块分账：system / history / skill / memory / tool_result / user_input / output
- [ ] 工具结果超过 2000 tokens 时自动截取前 2000 + "...[truncated]"
- [ ] 聊天历史超过 10 轮时触发滚动摘要（复用现有历史压缩逻辑）

**产出文件**: `core/runtime/token_meter.py`

**验证方式**:
```bash
# 测试 1：token 分账（验证每次 LLM 调用后 7 个模块都有记录）
pytest tests/test_token_meter.py::test_token_accounting -v

# 测试 2：工具结果截断（输入 3000 tokens 工具结果，验证输出为 2000 + truncated）
pytest tests/test_token_meter.py::test_tool_result_truncation -v

# 测试 3：长会话滚动摘要（模拟 12 轮对话，验证触发摘要且历史长度下降）
pytest tests/test_token_meter.py::test_rolling_summary_trigger -v
```

## Pre-step：Baseline Benchmark（必须在任何代码改动前执行）

> **时序要求**：必须在 Phase 1 任何代码改动之前执行，否则 baseline 数据会被污染。

- [ ] 设计 10 条固定测试任务（覆盖：简单问答、工具调用、长会话、图片分析）
- [ ] 记录 token 消耗（prompt / completion / total）、延迟、成功率
- [ ] 输出 `reports/baseline_metrics.json`

**产出文件**: `scripts/eval/baseline_run.py`

**验证方式**:
```bash
python scripts/eval/baseline_run.py
type reports/baseline_metrics.json  # Windows; bash 用户用: cat reports/baseline_metrics.json
```

## 验收标准
- [ ] `pytest -q` 全部通过
- [ ] `python -m app.main` 正常启动
- [ ] 设置窗口可打开、修改、保存、重启后生效
- [ ] 能力解锁状态重启后不丢失
- [ ] Agent 能使用 web_search / read_file 等工具完成实际任务
- [ ] 危险命令被拦截，工作区外访问被拒绝
- [ ] token 分账数据可查询（`token_meter.get_last_call_stats()`）
- [ ] baseline benchmark 可跑通并输出 `reports/baseline_metrics.json`

---

# Phase 2: 子 Agent 双通道 + 任务状态持久化

## 目标
让简单任务快起来，让高风险任务不拖垮主进程，让任务状态可恢复。

## 核心任务

### 2.1 抽象 SubagentRuntime 接口
```python
class SubagentRuntime(ABC):
    @abstractmethod
    async def run(self, spec: SubagentSpec) -> SubagentResult: ...
```

**产出文件**: `core/agent/subagent_runtime.py`

### 2.2 实现轻量子 Agent（In-Process）
**实现路径判定（量化标准）**：
1. **主路径**：检查 nanobot 的 `SubagentManager` 是否可用（`from nanobot.agent.subagent import SubagentManager` 可导入且 `spawn()` 方法签名匹配）
2. **fallback 条件**：仅当以下任一成立时才使用自建 asyncio Task：
   - `SubagentManager` 导入失败（ImportError）
   - `spawn()` 方法不存在或签名不匹配（缺少 `task`/`label`/`session_key` 参数）
   - 运行时发现 `SubagentManager` 依赖的 `MessageBus` 未初始化
3. **默认优先级**：主路径优先，fallback 仅在主路径不可用时自动切换

- [ ] 利用 nanobot 现有的 `SubagentManager`（`agent/subagent.py`）
- [ ] 独立 `sub_session_key`，不继承主会话完整 history
- [ ] 受限工具集（只允许 read_file/web_search，不允许 write_file/exec）
- [ ] 结构化输出，不回灌完整 transcript
- [ ] 适用：文本总结、分类、query rewrite、short plan

**产出文件**: `core/agent/inprocess_runtime.py`

### 2.3 保留并抽象隔离子 Agent（Isolated Process）
- [ ] 将现有 `SubagentFactory` 抽象为 `IsolatedProcessRuntime`
- [ ] 保留多进程方案用于图片分析、代码执行等高风险任务
- [ ] 统一结果返回格式（`SubagentResult`）

**产出文件**: `core/agent/isolated_runtime.py`

### 2.4 实现路由策略
```python
# 简单规则路由
if task_type in ("summarize", "classify", "rewrite", "rank"):
    return InProcessRuntime()
else:
    return IsolatedProcessRuntime()
```

**产出文件**: `core/agent/subagent_policy.py`

### 2.5 统一 SubagentSpec / SubagentResult
```python
@dataclass
class SubagentSpec:
    name: str
    runtime_type: Literal["in_process", "isolated_process"]
    prompt: str
    allowed_tools: list[str]
    timeout_sec: int
    writeback_mode: Literal["none", "summary_only", "result_only"]

@dataclass
class SubagentResult:
    success: bool
    summary: str | None
    structured_output: dict | None
    error: str | None
```

**产出文件**: 扩展现有 `core/agent/subagent_spec.py`

### 2.6 任务状态实时持久化
- [ ] 任务状态（QUEUED/RUNNING/SUCCESS/FAILED/CANCELLED）实时持久化到 SQLite
- [ ] 每次状态变更立即写入 DB（不等到任务结束）
- [ ] 应用重启后显示未完成任务列表（QUEUED/RUNNING/FAILED）
- [ ] 强杀后未完成任务状态标记为 FAILED，可手动重试
- [ ] 用户主动取消后状态变为 CANCELLED

**产出文件**: `core/runtime/task_checkpoint.py`

## 验收标准
- [ ] 文本总结任务走轻量子 Agent（延迟 < 500ms 启动）
- [ ] 图片分析任务走隔离子 Agent
- [ ] 两者结果统一为 `SubagentResult`
- [ ] 任务状态实时持久化，重启后可见未完成任务
- [ ] 提交任务后强杀应用，重启后任务状态为 FAILED，可重试
- [ ] `tests/test_subagent_runtime_mixed.py` 通过
- [ ] `tests/test_task_checkpoint.py` 通过

---

# Phase 3: 智能上下文引擎（流式输出 + 极致四重记忆 + 十七项Token优化）

## 目标
这是 v2 的**核心差异化能力**：让 Agent 记得住、省得多、响应快。

## 核心任务

### 3.1 接入 nanobot 流式输出
- [ ] 在 `NanobotAdapter` 中使用 `on_stream` 钩子
- [ ] 将流式增量实时推送到 `TaskPanel`
- [ ] 实现打字机效果（逐步显示文本）

**产出文件**: `ui/streaming_message_widget.py`

### 3.2 接入 AgentHook 扩展
利用 nanobot 的 6 个生命周期钩子：
```python
class LobuddyHook(AgentHook):
    async def on_stream(self, ctx, delta):      # 实时推送到 UI
    async def before_execute_tools(self, ctx):  # 显示"正在使用工具..."
    async def after_iteration(self, ctx):       # 更新 token 统计
```

**产出文件**: `core/hooks/lobuddy_hook.py`

### 3.3 桌宠细粒度状态
当前只有 idle/running/success/error 四种状态，新增：
- `THINKING` — LLM 正在生成回复
- `SEARCHING` — 正在使用 web_search
- `READING` — 正在读取文件
- `WRITING` — 正在写入/编辑文件
- `USING_TOOL` — 正在执行工具
- `REMEMBERING` — 正在检索记忆（新增）
- `PACKING` — 正在压缩上下文（新增）

**修改文件**: `ui/pet_window.py` 状态机扩展

---

### 3.4 四重记忆系统（极致版：从关键词匹配到语义智能）

#### 3.4.1 Working Memory（显式偏好 + 冲突检测）
- [ ] 在 SQLite 中新增 `working_memory` 表（key, value, updated_at, **embedding**, **conflict_flag**）
- [ ] 任务完成后提取用户明确偏好（"我喜欢用 Python"、"请用中文回答"）
- [ ] **冲突检测**：当用户新偏好与已有偏好语义相反时（"我喜欢A"后说"我讨厌A"），标记 `conflict_flag=True` 并提示用户确认
- [ ] 冲突解决策略：用户确认后更新，否则保留原偏好并记录争议
- [ ] 每次任务执行前通过**语义检索**注入相关偏好（上限 5 条，总计 < 300 tokens）
- [ ] 偏好提取规则：语义模式匹配（"我喜欢/我要/不要/请用/讨厌/避免"等）

**产出文件**: `core/memory/working_memory_repo.py`, `core/memory/conflict_detector.py`

#### 3.4.2 Rolling Summary（对话摘要）【v2.0必做】
- [ ] 每 10 轮对话自动生成滚动摘要（复用现有历史压缩逻辑）
- [ ] 摘要生成后，原始 10 轮历史被替换为 1 条摘要消息
- [ ] 摘要格式："用户询问了 X，助手完成了 Y，关键结论是 Z"
- [ ] 保留最近 2 轮原始对话 + 所有摘要

**产出文件**: `core/memory/rolling_summary.py`

#### 3.4.2b 跨会话关联（Session Linker）【v2.1延期，不阻塞v2.0】
- [ ] 维护 `session_linker` 索引表，记录跨会话的实体关联
  - 例：Session-5提到"写了个爬虫脚本"→ Session-8用户说"上次那个脚本"→自动关联
  - 实现：提取命名实体（文件名、项目名称、技术栈）→建立实体-会话索引
- [ ] 当检测到跨会话引用时，自动加载关联会话的摘要作为上下文

**产出文件**: `core/memory/session_linker.py`

#### 3.4.3 Profile Memory（用户画像 + Embedding检索）
- [ ] 在 SQLite 中新增 `profile_memory` 表（trait, value, confidence, updated_at, **embedding**）
- [ ] 从对话中推断用户属性：
  - 技术水平（`technical_level`: beginner/intermediate/advanced）
  - 沟通风格（`communication_style`: concise/detailed/tutorial）
  - 常用语言（`preferred_language`: zh/en）
  - 关注领域（`interests`: ["python", "web", "data"]）
- [ ] **画像演化**：confidence 不是静态的，根据后续对话验证动态调整
  - 验证命中：confidence += 0.05（上限 0.95）
  - 验证失败：confidence -= 0.1（下限 0.3）
- [ ] 每次任务执行前通过**Embedding相似度**检索相关画像（上限 3 条，总计 < 200 tokens）
- [ ] confidence < 0.7 的画像不注入，避免误判

**产出文件**: `core/memory/profile_memory.py`, `core/memory/profile_extractor.py`

#### 3.4.4 Workflow Memory（工作流复用 + 参数泛化）
- [ ] 在 SQLite 中新增 `workflow_memory` 表（pattern, steps, success_count, last_used, **param_slots**）
- [ ] 识别成功的任务执行模式：
  - 例："查资料→总结→写代码" 模式
  - 例："分析图片→提取文字→翻译" 模式
- [ ] **参数泛化**：将具体参数抽象为槽位
  - "查[Python]资料→总结→写[爬虫]代码" → pattern: "查[topic]资料→总结→写[task]代码"
- [ ] 当用户提交类似任务时，提示"您上次用 X 方式完成了类似任务，是否复用？"
- [ ] success_count >= 2 的工作流才提示复用

**产出文件**: `core/memory/workflow_memory.py`, `core/memory/workflow_extractor.py`

#### 3.4.5 记忆写入门禁（写入极致化）
检索极致化之外，写入质量同样关键。实现 `MemoryWriteGate`：

- [ ] **显式确认机制**：
  - 用户明确声明的偏好（"我喜欢 Python"）→ 直接写入，confidence=1.0
  - 系统推断的画像（"用户技术水平：advanced"）→ confidence < 0.8 时**不自动写入**，仅标记为"待确认"
  - 待确认记忆存入 `pending_memory` 隔离区，不参与检索，等待后续对话验证
- [ ] **反证衰减**：
  - 画像推断后，若后续 3 轮对话中出现反证（如推断"advanced"但用户问基础问题），confidence 衰减 50%
  - 衰减至 < 0.3 时，从 Profile Memory 删除，移至 `disproved_memory` 归档
- [ ] **污染隔离区**：
  - `pending_memory`：未验证的推断，不注入 prompt
  - `disproved_memory`：已证伪的记忆，保留用于避免重复误判
  - `working_memory`：用户显式确认，唯一直接注入 prompt 的记忆
- [ ] **写入审计**：
  - 所有记忆写入记录 trace（时间、来源、confidence、用户反馈）
  - 支持人工回查："为什么系统认为我喜欢 Python？"

**产出文件**: `core/memory/memory_write_gate.py`, `core/memory/pending_memory.py`

#### 3.4.6 记忆真源定义（Source of Truth）
⚠️ **核心原则**：SQLite 是记忆的唯一真源，nanobot Memory/Dream 是**派生缓存/优化层**。

| 系统 | 角色 | 数据流向 | 冲突解决 |
|------|------|---------|---------|
| **SQLite 四层记忆** | 唯一真源 | 所有记忆写入先落库 | 以 SQLite 为准 |
| **nanobot Memory** | 短期缓存 | 从 SQLite 加载当前会话相关记忆 | 不独立持久化 |
| **nanobot Consolidator** | 合并优化器 | 读取 SQLite → 合并相似项 → 写回 SQLite | 写回前需确认 |
| **nanobot Dream** | 离线整理器 | 定期读取 SQLite → 优化 embedding/清理 → 写回 SQLite | 写回前需确认 |

- [ ] **写入顺序**：任何记忆变更必须先写 SQLite，再同步到 nanobot 缓存
- [ ] **读取顺序**：优先读 SQLite，nanobot 缓存仅作加速
- [ ] **冲突检测**：若 nanobot 派生层与 SQLite 不一致，以 SQLite 为准，清除 nanobot 缓存
- [ ] **回滚能力**：SQLite 支持事务回滚，误写入的记忆可撤销

**产出文件**: `core/memory/memory_source_of_truth.py`

#### 3.4.7 统一记忆检索器（语义检索 + 激活抑制）
- [ ] 实现 `MemoryRetriever`，统一查询四类记忆
- [ ] **语义检索引擎**：
  - 本地轻量模型：`sentence-transformers/all-MiniLM-L6-v2`（22MB，CPU可用）
  - 所有记忆条目预计算 embedding，存入 SQLite（`memory_embeddings` 表）
  - 检索时：当前任务文本 → embedding → 余弦相似度排序
  - fallback：embedding模型加载失败时回退到关键词匹配
- [ ] **激活/抑制机制**：
  - 激活：与当前任务相似度 > 0.75 的记忆标记为"激活"，优先注入
  - 抑制：相似度 < 0.3 的记忆标记为"抑制"，本轮不注入
  - 中间态：相似度 0.3-0.75 的记忆按相关性排序，有限注入
- [ ] **遗忘算法**（防止记忆无限增长）：
  - 综合评分 = 0.4 × 最后访问时间衰减 + 0.3 × 访问频率 + 0.2 × confidence + 0.1 × 创建时间衰减
  - 每周期（每天）清理评分最低的后 5% 记忆
  - Working Memory 不参与遗忘（用户显式偏好永不过期）
- [ ] 输入：当前任务描述
- [ ] 输出：按激活度排序的记忆列表（上限 8 条，总计 < 500 tokens）

**产出文件**: `core/memory/memory_retriever.py`, `core/memory/embedding_engine.py`, `core/memory/forgetting_engine.py`

#### 3.4.8 nanobot原生记忆整合
- [ ] 适配 nanobot 的 `Memory` / `Consolidator` / `Dream` 能力：
  - `Memory`：将 nanobot 的短期记忆接入 Rolling Summary 生成
  - `Consolidator`：利用 nanobot 的记忆整合机制，定期合并相似记忆条目
  - `Dream`：空闲时触发记忆整理，优化 embedding 和清理过期记忆
- [ ] 实现 `LobuddyMemoryHook`，在 nanobot 的 `after_iteration` 钩子中同步记忆状态

**产出文件**: `core/memory/nanobot_memory_bridge.py`

#### 3.4.9 记忆极致化进阶（重要性评分 + 分层存储）【v2.0必做】
- [ ] **记忆重要性评分**（防止关键记忆被遗忘）：
  - 在遗忘算法基础上增加 `importance_score`（1-10）
  - 用户显式确认过的偏好 → importance = 10（永不过期）
  - 工作流成功执行 5 次以上 → importance = 8
  - 画像 confidence > 0.9 → importance = 7
  - 遗忘公式修正：`final_score = base_score × (1 + importance/10)`（重要性越高越难被遗忘）
- [ ] **记忆分层存储策略**：
  - Hot Memory（最近 7 天）：内存缓存，检索延迟目标 < 50ms（实测为准）
  - Warm Memory（7-30 天）：SQLite 本地存储
  - Cold Memory（>30 天）：归档到 `data/memory_archive/` 目录，按需加载

**产出文件**: `core/memory/importance_scorer.py`, `core/memory/tiered_storage.py`

#### 3.4.9b Embedding量化压缩（实验性）【v2.1延期，不阻塞v2.0】
- [ ] 将 float32 embedding 量化为 int8（存储减少 75%）
- [ ] 使用量化/反量化尺度（计算 min/max → scale/zero-point）
- [ ] **验证基准**：量化前后 Recall@k 一致性 >= 95%
- [ ] 若 Recall@k 损失 > 5%，回退到 float32

**产出文件**: `core/memory/embedding_quantizer.py`（实验性）

#### 3.4.9c 时序感知检索（Temporal Parser）【v2.1延期，不阻塞v2.0】
- [ ] 支持时间范围查询："昨天提到的方案"、"上周的脚本"
- [ ] 在 `memory_embeddings` 表中增加 `temporal_tags` 字段
- [ ] 时间表达式解析：使用 `dateparser` 库解析相对时间

**产出文件**: `core/memory/temporal_parser.py`（v2.1）

**验证方式**:
```bash
# 测试 1：Working Memory 偏好提取与冲突检测
pytest tests/test_memory_system.py::test_working_memory -v
pytest tests/test_memory_system.py::test_conflict_detection -v

# 测试 2：Rolling Summary
pytest tests/test_memory_system.py::test_rolling_summary -v

# 测试 3：Profile Memory Embedding检索
pytest tests/test_memory_system.py::test_profile_memory -v
pytest tests/test_memory_system.py::test_profile_embedding_retrieval -v

# 测试 4：Workflow Memory 参数泛化
pytest tests/test_memory_system.py::test_workflow_memory -v

# 测试 5：语义检索器（输入"帮我写段 Python"，应返回 Python 相关偏好 + 画像，无关记忆被抑制）
pytest tests/test_memory_system.py::test_semantic_retrieval -v
pytest tests/test_memory_system.py::test_activation_suppression -v

# 测试 6：遗忘算法 + 重要性评分（模拟100条记忆，验证低评分记忆被清理，高importance记忆保留）
pytest tests/test_memory_system.py::test_forgetting_algorithm -v
pytest tests/test_memory_system.py::test_importance_protection -v

# 测试 7：分层存储（验证 hot/warm/cold 三层检索延迟梯度）
pytest tests/test_memory_system.py::test_tiered_storage -v

# --- v2.1 可选测试（失败不阻塞 v2.0 验收）---
# 测试 8：跨会话关联（v2.1）
pytest tests/test_memory_system.py::test_cross_session_link -v

# 测试 9：时序感知检索（v2.1）
pytest tests/test_memory_system.py::test_temporal_retrieval -v

# 测试 10：Embedding量化（验证 int8 量化后相似度排序与 float32 一致率 > 95%）【C层：可选，失败不阻塞验收】
pytest tests/test_memory_system.py::test_embedding_quantization -v

# v2.0 手动验证（阻塞验收）：
# - 提交"以后给我写 Python 代码"，重启后提交"帮我写段代码"，验证输出为 Python
# - 提交"我喜欢深色模式"后再说"我讨厌深色模式"，验证冲突检测提示
# - 进行 12 轮对话，验证第 11 轮触发滚动摘要，历史长度下降
# - 多次执行"查资料→总结"模式，验证第 3 次提示"是否复用上次工作流？"
# - 模拟 30 天后的记忆查询，验证 cold memory 正确加载

# v2.1 手动验证（不阻塞 v2.0）：
# - 问"上次那个脚本呢"，验证跨会话关联加载历史摘要
# - 提交"昨天我要的脚本能再发一下吗"，验证时序检索返回昨日记忆
```

#### DB Migration 策略（新增表迁移方案）
新增以下表，需提供 migration + backfill + rollback 策略：

#### v2.0 必做 Migration（阻塞验收）
| 新表 | Migration 方式 | Backfill 策略 | Rollback |
|------|---------------|--------------|---------|
| `working_memory` | 新建表 + 索引 | 从现有聊天历史提取显式偏好 | 删除表即可 |
| `profile_memory` | 新建表 + 索引 | 空表启动，对话中逐步积累 | 删除表即可 |
| `workflow_memory` | 新建表 + 索引 | 空表启动，任务成功后逐步积累 | 删除表即可 |
| `memory_embeddings` | 新建表 + 索引 | 空表启动，写入记忆时同步生成 | 删除表即可 |
| `pending_memory` | 新建表 | 空表启动 | 删除表即可 |
| `disproved_memory` | 新建表 | 空表启动 | 删除表即可 |
| `artifact_store` | 新建表 | 空表启动 | 删除表即可 |

#### v2.1 可选 Migration（不阻塞 v2.0）
| 新表 | Migration 方式 | Backfill 策略 | Rollback | 说明 |
|------|---------------|--------------|---------|------|
| `session_linker` | 新建表 + 索引 | 扫描现有历史，提取实体关联 | 删除表即可 | v2.1 跨会话关联 |
| `temporal_tags` | 新增字段 | 空表启动 | 回滚字段即可 | v2.1 时序感知 |

- [ ] **幂等性保证**：Migration 脚本使用 `CREATE TABLE IF NOT EXISTS`，可重复执行不报错
- [ ] **版本表**：新建 `schema_version` 表记录当前 migration 版本（version, applied_at, checksum）
- [ ] **启动检查**：`bootstrap.py` 启动时读取 `schema_version`，低于 v2 则自动执行 migration
- [ ] **备份策略**：执行 migration 前自动备份 `data/lobuddy.db` 到 `data/backup/lobuddy_v{current_version}.db`
- [ ] **回滚策略**：
  - 方式1：执行 rollback SQL 脚本删除新增表
  - 方式2：直接恢复备份的 db 文件（推荐，100%还原）
- [ ] **校验命令**：
  ```bash
  # 验证 migration 成功（bash）
  sqlite3 data/lobuddy.db ".tables" | grep -E "working_memory|profile_memory|memory_embeddings"
  # 验证 migration 成功（PowerShell）
  sqlite3 data/lobuddy.db ".tables" | Select-String -Pattern "working_memory|profile_memory|memory_embeddings"
  
  # 验证 schema_version 记录
  sqlite3 data/lobuddy.db "SELECT * FROM schema_version ORDER BY applied_at DESC LIMIT 1;"
  
  # 回滚（如需，bash）
  cp data/backup/lobuddy_v1.db data/lobuddy.db
  # 回滚（如需，PowerShell）
  Copy-Item data/backup/lobuddy_v1.db data/lobuddy.db -Force
  ```

**产出文件**: 
- `scripts/migrations/v2_memory_system.sql`
- `scripts/migrations/v2_memory_system_rollback.sql`
- `core/storage/schema_manager.py`（自动检测 + 执行 migration）

---

### 3.5 十七项 Token 优化策略（极致版：硬门槛 >=35%/50%，力争 >=40%）

#### 3.5.1 Token 分账（Phase 1 已落地，Phase 3 增强可视化）
- [ ] 在流式输出面板显示当前任务的 token 消耗（实时更新）
- [ ] 分账维度：system / history / skill / memory / tool_result / user_input / output
- [ ] 超过预算时 UI 显示警告色

**产出文件**: `ui/token_display_widget.py`

#### 3.5.2 ContextPacker动态预算（上下文自适应分配）
- [ ] 定义 `PackedContext` 结构：
```python
class PackedContext(BaseModel):
    system_prompt: str        # 固定 800 tokens
    current_task: str         # 固定 400 tokens
    selected_skills: list     # 预算 1000 tokens，超限时只保留 top-3
    recent_turns: list        # 预算 1200 tokens，超限时触发滚动摘要
    rolling_summary: str      # 预算 600 tokens
    retrieved_memories: list  # 预算 800 tokens，超限时只保留 top-5
    projected_artifacts: list # 预算 1200 tokens
    # 总预算：动态调整，见下方
```
- [ ] **动态预算算法**：
  - 根据当前使用的模型上下文窗口（4k/8k/16k/32k/128k）按比例分配
  - 公式：`total_budget = model_context_window × 0.6`（保留40%给输出和冗余）
  - 各模块预算按比例缩放，优先保证 system_prompt + current_task + rolling_summary
  - 当检测到长会话（>20轮）时，自动降低 recent_turns 预算，提升 rolling_summary 预算
- [ ] 裁剪优先级：artifacts → memories → skills → recent turns → summary 永远保留
- [ ] 每次 LLM 调用前必须先过 ContextPacker

**产出文件**: `core/runtime/context_packer.py`

#### 3.5.3 Prompt Caching（System Prompt复用）
- [ ] **适用条件**：使用支持 prompt caching 的 Provider（OpenRouter Anthropic Claude / OpenAI GPT-4o 等）
- [ ] 实现 `PromptCacheManager`：
  - 将 system_prompt + skills + 固定记忆标记为 `cache_control: { type: "ephemeral" }`
  - 同一会话中后续调用复用已缓存的 prompt tokens，只计费增量部分
  - 缓存命中率目标：system_prompt 和 skills 的 >=90% 命中（非100%，首次调用必然未命中）
- [ ] 自动检测 Provider 是否支持 caching（通过 API 版本或配置标志）
- [ ] 不支持 caching 的 Provider  gracefully degrade（不报错，正常走全量）

**产出文件**: `core/runtime/prompt_cache_manager.py`

#### 3.5.4 KV Cache复用（对话历史增量更新）【C层：实验性，条件实施】
> ⚠️ **风险声明**：大多数托管 API（OpenAI/Anthropic/OpenRouter）**不提供可控 KV Cache key**。此策略仅当使用本地 vLLM/llama.cpp 或特定企业 API 时有效。作为实验项，先实现 PoC 验证，再根据结果决定是否投入。

- [ ] 实现 `KVCacheManager`（实验性）：
  - 维护对话历史的 KV Cache 状态（turn_id → kv_cache_key）
  - 新消息只传递增量：已有历史的 KV Cache 不重复编码
  - 当 Rolling Summary 替换历史时，重置 KV Cache（Summary 作为新的 Cache 起点）
- [ ] 与 nanobot 的 `on_stream` / `after_iteration` 钩子集成，在每次迭代后更新 KV Cache 状态
- [ ] **托管 API 降级方案**：Provider 不支持 KV Cache 时，自动降级为增量文本传递（只传递新增消息，不重复传递完整历史）
- [ ] **PoC 验证项**：
  - 测试环境：本地 llama.cpp 或 vLLM
  - 验证指标：相同对话历史重复调用时，prompt tokens 是否减少 >=10%
  - 失败标准：若 3 种主流 Provider 均不支持，则标记为 `WONTFIX` 并文档化

**产出文件**: `core/runtime/kv_cache_manager.py`（实验性）

#### 3.5.5 模型分层路由（大小模型协同）
- [ ] 实现 `ModelRouter`，根据任务复杂度选择模型：
```python
class ModelRouter:
    # 小模型（轻量、便宜）：分类、路由、简单提取
    LIGHT_MODEL = "gpt-4o-mini"  # 或其他轻量模型
    # 大模型（强力、昂贵）：复杂推理、代码生成、多步任务
    HEAVY_MODEL = "gpt-4o"       # 或其他强力模型
    
    def route(self, task: str, context: dict) -> str:
        # 先用小模型做意图分类
        intent = classify_intent(task)  # "simple_qa" / "code" / "research" / "creative"
        if intent in ("simple_qa", "classification", "routing"):
            return self.LIGHT_MODEL
        return self.HEAVY_MODEL
```
- [ ] **分类规则**：
  - `simple_qa`：纯问答、问候、简单事实查询 → 小模型
  - `classification`：任务分类、意图识别 → 小模型
  - `code`：代码生成、代码审查、调试 → 大模型
  - `research`：网络调研、多源信息整合 → 大模型
  - `creative`：创意写作、复杂推理 → 大模型
- [ ] Token 节省估算：简单任务占 60%+，使用小模型可节省 40-60% 成本

**产出文件**: `core/runtime/model_router.py`

#### 3.5.6 Skill 懒加载
- [ ] 不再一次性加载全部 skills
- [ ] 实现 `SkillSelector`：
  1. 读取 skill index（只加载标题 + 关键词，不加载正文）
  2. 用关键词匹配当前任务，选 top-3 相关 skill
  3. 只加载这 3 个 skill 的完整内容
- [ ] 若当前任务无匹配 skill，则不加载任何 skill

**产出文件**: `core/skills/skill_selector.py`

#### 3.5.7 记忆语义检索（与 3.4.5 配合）
- [ ] 不再全量注入所有记忆
- [ ] 使用 `MemoryRetriever` 按需检索：
  - 输入：当前任务描述
  - 输出：最多 8 条相关记忆（总计 < 500 tokens）
- [ ] **语义检索**：使用 embedding 相似度排序，非关键词匹配
- [ ] 无关记忆不注入，降低噪音

**产出文件**: 与 `core/memory/memory_retriever.py` 共用

#### 3.5.8 Tool Artifact 化
- [ ] 工具结果不再直接回灌到对话历史
- [ ] 改为 Artifact 模式：
  - `raw_artifact`：完整结果存入 SQLite（`artifact_store` 表）
  - `compact_projection`：200 字摘要注入对话历史
  - `artifact_pointer`："详见 artifact #12345"
- [ ] 当用户追问"详细点"时，再加载完整 artifact

**产出文件**: `core/tools/artifact_store.py`

#### 3.5.9 Tool Narrowing（工具集收缩）
- [ ] 不再每轮暴露全部工具
- [ ] 实现 `ToolNarrower`：
  1. 分析当前任务意图（关键词匹配 + 小模型分类）
  2. 选择最相关的 1-3 个工具
  3. 只将这 1-3 个工具注册到当前轮次
- [ ] 例：用户说"查一下天气"→只暴露 web_search；用户说"帮我改文件"→只暴露 read_file/write_file

**产出文件**: `core/tools/tool_narrower.py`

#### 3.5.10 上下文去重（A7：v2.0必做）
- [ ] 实现 `ContextDeduplicator`：
  - 检测重复上下文（system prompt 重复、技能描述重复、历史消息重复）
  - 去重策略：保留第一次出现，后续用指针引用
  - 工具结果去重：同一文件多次 read_file，只保留最新结果
- [ ] 与 Prompt Caching 协同：去重后的上下文更适合 caching（重复内容减少）

> **注**：此条目仅含"去重"，不含"增量更新"。增量更新（C3）是独立实验项，见下方。

**产出文件**: `core/runtime/context_deduplicator.py`

#### 3.5.10b 增量更新（C3：v2.1实验，条件实施）
- [ ] 在上下文去重基础上，实现增量传递：只传递自上次调用以来新增/变更的上下文
- [ ] 与 Prompt Caching 和 KV Cache 协同：增量更新减少 KV Cache 无效化
- [ ] **前提条件**：Provider 支持增量 API 或本地推理框架
- [ ] **验证方式**：若 3 种主流 Provider 均不支持，标记 WONTFIX

**产出文件**: `core/runtime/incremental_context.py`（实验性）

#### 3.5.11 响应缓存（高频查询零成本）
- [ ] 实现 `ResponseCache`，缓存高频查询的完整响应：
  - 缓存键：任务embedding + 工具签名哈希
  - 命中条件：相似度 > 0.95 且工具签名一致
  - 缓存内容：完整 response 文本 + token 消耗记录
- [ ] **适用场景**：
  - "今天天气怎么样" → 直接返回缓存（0 token 消耗）
  - "我的宠物等级是多少" → 直接返回缓存
  - "Python 的 list 怎么排序" → 直接返回缓存
- [ ] **缓存失效策略（Freshness 保证）**：
  - TTL：默认 1 小时（天气等动态信息）或 24 小时（静态知识）
  - 主动失效：检测到相关记忆/偏好变更时清除关联缓存
  - **动态 freshness 标记**：
    - 天气/股价/宠物状态 → `freshness=volatile`，TTL=15分钟，超期必须重新查询
    - 技术知识/代码示例 → `freshness=stable`，TTL=7天
    - 用户偏好 → `freshness=persistent`，TTL=永久，但偏好变更时主动失效
  - **Stale 数据保护**：超期缓存返回前，UI 显示"[缓存数据，可能已过时]"并附带"刷新"按钮
- [ ] 缓存命中率目标：>= 15% 的常见查询（避免过度缓存导致 stale 数据风险）

**产出文件**: `core/runtime/response_cache.py`

#### 3.5.12 Prompt模板压缩（去除冗余token）
- [ ] 实现 `PromptMinifier`：
  - 去除 system prompt 中的冗余空白和换行（每处节省 1-3 tokens）
  - 使用短变量名替代长描述（如 `usr_pref` 替代 `user_preference_setting`）
  - 合并重复的 JSON 结构（工具 schema 去重字段）
  - 使用 symbolic reference 替代长文本重复（如 `[SYS_PROMPT]` 指针）
- [ ] 与 Prompt Caching 协同：压缩后的 prompt 更易命中 cache
- [ ] 目标：system prompt 部分节省 5-10% tokens

**产出文件**: `core/runtime/prompt_minifier.py`

#### 3.5.13 自适应工具结果压缩（动态摘要长度）
- [ ] 升级 Tool Artifact 化，从固定 200 字摘要改为**自适应长度**：
  - 根据当前上下文剩余预算动态调整摘要长度
  - 预算紧张时：50 字超短摘要
  - 预算充裕时：500 字详细摘要
  - 根据工具类型调整：read_file → 保留关键行号；web_search → 保留 URL 和标题
- [ ] 实现 `AdaptiveCompressor`：
  ```python
  def compress(self, tool_result: str, remaining_budget: int, tool_type: str) -> str:
      if remaining_budget < 500: return ultra_short_summary(tool_result)
      if remaining_budget < 1500: return short_summary(tool_result)
      return detailed_summary(tool_result)
  ```

**产出文件**: `core/tools/adaptive_compressor.py`

#### 3.5.14 max_output_tokens 动态上限（输出侧控本）
- [ ] 根据任务类型动态设置 `max_output_tokens`：
  - 简单问答/问候：`max_tokens=150`（通常只需 50-100 tokens 即可回答）
  - 代码生成：`max_tokens=2000`（允许完整函数/类）
  - 文档总结：`max_tokens=1000`
  - 创意写作：`max_tokens=4000`
- [ ] 与模型分层路由协同：小模型任务默认设置更保守的 `max_tokens`
- [ ] 实现 `OutputTokenLimiter`：根据历史输出长度统计，自适应调整上限
  - 若某类任务连续 5 次实际输出 < 上限的 50%，则降低该类任务的上限

**产出文件**: `core/runtime/output_token_limiter.py`

#### 3.5.15 命令型请求本地 bypass（零 token 成本）
- [ ] 实现 `LocalCommandRouter`，本地规则直接响应，不走 LLM：
  - "打开设置" → 直接触发 `settings_window.show()`
  - "退出" / "关闭" → 直接触发退出流程
  - "宠物等级" → 直接查询 `pet_repo` 返回
  - "清空历史" → 直接调用 `chat_session.clear()`
  - "切换主题" → 直接修改配置并应用
- [ ] 使用关键词/正则匹配识别命令型请求（无需 LLM 分类）
- [ ] 命中率目标：常见命令型请求 100% 本地处理，零 token 消耗

**产出文件**: `core/runtime/local_command_router.py`

#### 3.5.16 Query Normalization 缓存（语义等价查询共享）
- [ ] 实现 `QueryNormalizer`：
  - 规范化查询文本：去除语气词、统一同义词、标准化句式
  - 例："今天天气咋样" → "今天天气"
  - 例："帮我查一下明天北京的温度" → "北京明天温度"
- [ ] 规范化后的查询作为缓存键，语义等价查询共享同一缓存条目
- [ ] 与响应缓存协同：规范化后的查询先查缓存，未命中再走 LLM

**产出文件**: `core/runtime/query_normalizer.py`

#### 3.5.17 Tool Schema 按需注入（非全量暴露）
- [ ] 升级 Tool Narrowing：不仅按轮次选择工具，还**按需注入 schema**：
  - 只暴露当前轮次选中工具的 schema（而非全部工具的 schema）
  - schema 描述精简：去除未使用的参数描述、示例值
  - 动态 schema 生成：根据上下文生成最小可用 schema
- [ ] 与 Tool Narrowing 协同：
  - Tool Narrower 选择工具 → Tool Schema Injector 只注入这些工具的 schema
  - 相比全量 schema，每轮节省 10-20% tool schema tokens

**产出文件**: `core/tools/tool_schema_injector.py`

**验证方式**:

#### v2.0 阻塞测试（必须全部通过）

**验收映射表**（策略ID → 测试用例 → 阻塞级别）：

| 策略ID | 测试用例 | 阻塞级别 | 说明 |
|--------|---------|---------|------|
| A1 | `test_token_accounting` | 阻塞 | Token 分账基础能力 |
| A2 | `test_context_packer_dynamic_budget` | 阻塞 | 动态预算分配 |
| A3 | `test_skill_lazy_loading` | 阻塞 | Skill 懒加载 |
| A4 | `test_semantic_retrieval` | 阻塞 | 记忆语义检索 |
| A5 | `test_tool_artifact` | 阻塞 | Tool Artifact 化 |
| A6 | `test_tool_narrowing` | 阻塞 | Tool Narrowing |
| A7 | `test_context_deduplication` | 阻塞 | 上下文去重 |
| A8 | `test_response_cache` | 阻塞 | 响应缓存 |
| A9 | `test_output_token_limiter` | 阻塞 | 输出token上限 |
| A10 | `test_local_command_router` | 阻塞 | 本地命令bypass |
| A11 | `test_query_normalizer` | 阻塞 | 查询规范化 |
| A12 | `test_tool_schema_injector` | 阻塞 | Schema按需注入 |
| B1 | `test_prompt_caching` | 条件阻塞 | Provider支持则必须通过 |
| B2 | `test_model_routing` | 条件阻塞 | 多模型配置则必须通过 |
| B3 | `test_adaptive_compression` | 条件阻塞 | 实现则必须通过 |
| E2E | `test_token_reduction` | 阻塞 | 普通场景 >=35% |
| E2E | `test_long_session_token_reduction` | 阻塞 | 长会话 >=50% |

```bash
# A层全部测试（12项，缺一不可）
pytest tests/test_token_optimization.py::test_token_accounting -v
pytest tests/test_token_optimization.py::test_context_packer_dynamic_budget -v
pytest tests/test_token_optimization.py::test_skill_lazy_loading -v
pytest tests/test_memory_system.py::test_semantic_retrieval -v
pytest tests/test_token_optimization.py::test_tool_artifact -v
pytest tests/test_token_optimization.py::test_tool_narrowing -v
pytest tests/test_token_optimization.py::test_context_deduplication -v
pytest tests/test_token_optimization.py::test_response_cache -v
pytest tests/test_token_optimization.py::test_output_token_limiter -v
pytest tests/test_token_optimization.py::test_local_command_router -v
pytest tests/test_token_optimization.py::test_query_normalizer -v
pytest tests/test_token_optimization.py::test_tool_schema_injector -v

# B层条件测试（可用项必须通过）
pytest tests/test_token_optimization.py::test_prompt_caching -v
pytest tests/test_token_optimization.py::test_model_routing -v
pytest tests/test_token_optimization.py::test_adaptive_compression -v

# 端到端指标测试（硬门槛）
pytest tests/test_token_optimization.py::test_token_reduction -v      # >= 35%
pytest tests/test_token_optimization.py::test_long_session_token_reduction -v  # >= 50%
```

#### v2.1 / 实验可选测试（失败不阻塞 v2.0 验收）
```bash
# C层实验测试
pytest tests/test_token_optimization.py::test_kv_cache_reuse -v       # C1
pytest tests/test_token_optimization.py::test_prompt_minification -v   # C4 (原B3)

# B层不可用项（标记 WONTFIX 时需附 Provider 能力验证记录）
# 例：若 Provider 不支持 Prompt Caching，记录 API 版本和测试结果后标记 WONTFIX
```

---

### 3.6 记忆与Token协同优化（极致化核心）
记忆系统和Token优化不是独立工作的，而是相互增强的协同系统：

| 协同点 | 记忆系统贡献 | Token优化贡献 | 协同效果 |
|--------|-------------|--------------|---------|
| **语义检索 → 精准注入** | 只召回与当前任务相关的记忆 | 无关记忆不占用prompt预算 | 记忆token降低 60%+ |
| **Rolling Summary → KV Cache** | 10轮历史压缩为1条摘要 | KV Cache只需编码摘要，不重复编码10轮 | 长会话prompt降低 50%+ |
| **Working Memory → Prompt Cache** | 用户偏好稳定不变 | System prompt + 偏好可被缓存 | 重复调用降低 25%+ |
| **响应缓存 → 记忆增强** | 缓存键包含记忆状态哈希 | 相同记忆状态下的相同查询直接返回 | 高频查询降低 100% |
| **分层存储 → 冷数据零成本** | 旧记忆归档到cold tier | Cold memory不进入prompt | 历史数据无token负担 |
| **遗忘算法 → 上下文稳定** | 低价值记忆自动清理 | 上下文不再无限增长 | 长会话token增长从指数变为亚线性 |

**关键协同机制**：
- `MemoryRetriever` 的输出直接输入 `ContextPacker`，记忆检索预算和上下文预算联动调整
- `RollingSummary` 触发时同步更新 `KVCacheManager` 的起点，避免历史重新编码
- `WorkingMemory` 的冲突检测更新会主动失效 `ResponseCache` 中关联的缓存条目
- `ForgettingEngine` 清理记忆时通知 `EmbeddingEngine` 回收embedding存储

**产出文件**: `core/runtime/memory_token_orchestrator.py`（协同调度器）

**验证方式**:
```bash
# 测试：记忆与Token协同（模拟20轮对话+记忆注入，验证token增长曲线为对数而非指数）
pytest tests/test_token_optimization.py::test_memory_token_synergy -v
```

---

### 3.7 Guardrails 增强
Phase 1 已落地最小拦截（危险命令 + 路径越界），Phase 3 增强：
- [ ] 超长命令确认（超过 10 行的 shell 命令提示确认）
  - **实现承载**：复用现有 `result_popup.py` 弹层组件，显示命令摘要 + "确认执行 / 取消" 按钮
- [ ] 敏感操作记录（所有 write_file/exec 操作记录到 trace）
- [ ] **Token 预算告警**：当单次 LLM 调用 prompt tokens > 4000 时，弹层提示"上下文较长，建议开启新会话"

**修改文件**: `core/safety/guardrails.py`

## 验收标准
- [ ] 用户提交任务后能看到实时文本流
- [ ] 桌宠状态随 Agent 行为变化（THINKING -> SEARCHING -> REMEMBERING -> PACKING -> SUCCESS）
- [ ] 四重记忆系统可用（偏好/摘要/画像/工作流）
- [ ] 记忆检索只返回相关结果（无关记忆不注入）
- [ ] ContextPacker 预算控制有效（超限自动裁剪）
- [ ] Skill 懒加载有效（未匹配 skill 不加载）
- [ ] Tool Artifact 化有效（历史只保留摘要）
- [ ] Tool Narrowing 有效（不同任务暴露不同工具集）
- [ ] **端到端 token 降低 >= 35%**（对比 Phase 1 baseline，长会话 >= 50%，力争 >= 40%）
- [ ] 流式输出不增加整体延迟（总 latency <= baseline + 10%，first token latency <= 2s）

---

# Phase 4: Skills、评测与简历沉淀

## 目标
建立可扩展的能力体系，并沉淀可量化的工程成果。

## 核心任务

### 4.1 建立 Skills 系统（最小可用版）
- [ ] 创建 `skills/` 目录
- [ ] 定义 skill 文件格式（YAML frontmatter + markdown）
- [ ] 实现 `SkillLoader` 读取和注册 skill
- [ ] 首批 3 个 skill：
  1. `document_summarizer` — 文档总结
  2. `web_researcher` — 网络调研
  3. `code_assistant` — 代码辅助

**产出文件**: 
- `skills/document_summarizer.md`
- `skills/web_researcher.md`
- `skills/code_assistant.md`
- `core/skills/skill_loader.py`

### 4.2 MCP / A2A 预留接口
不要求完整实现，但要求预留最小占位：
- [ ] `core/protocols/mcp_gateway.py` — 空实现 + 接口定义 + 测试桩
- [ ] `core/protocols/a2a_gateway.py` — 空实现 + 接口定义 + 测试桩
- [ ] 在 `config.py` 中预留 `mcp_servers` / `a2a_endpoints` 配置项

**产出文件**: 
- `core/protocols/mcp_gateway.py`
- `core/protocols/a2a_gateway.py`
- `app/config.py`（新增 `mcp_servers` / `a2a_endpoints` 配置项）

### 4.3 统一 Trace 与指标
- [ ] 定义 `Trace` schema（task_id, timestamp, events, tokens, latency, memory_hits）
- [ ] 每次任务执行自动记录 trace（含记忆命中情况）
- [ ] 输出 `reports/trace_{task_id}.json`

**产出文件**: `core/observability/tracer.py`

### 4.4 扩展 Benchmark（改造后对比）
- [ ] 从 Pre-step 的 10 条扩展到 20 条
- [ ] 覆盖工具使用、子 Agent、流式输出、记忆系统、Token 优化等场景
- [ ] 输出改造后指标 `reports/after_metrics.json`
- [ ] **生成对比报告**（依赖 Pre-step 的 `reports/baseline_metrics.json`）
  - 对比维度：total tokens / prompt tokens / latency / task success rate / **memory hit rate** / **token reduction rate**
  - 输出 `reports/comparison_report.md`

#### 指标定义（统计口径）
**记忆命中率（Memory Hit Rate）**：
- 定义：在需要记忆的测试任务中，`MemoryRetriever` 返回的 Top-5 结果包含至少 1 条相关记忆的任务比例
- 计算公式：`hit_rate = (相关记忆被召回的任务数) / (需要记忆的任务总数)`
- 判定标准：人工标注任务与返回记忆的相关性（相关/不相关）
- 目标：>= 70%

**Token 降低率（Token Reduction Rate）**：
- 定义：同一任务集、同一模型、同温度、同工具可用性下，改造后 prompt tokens 中位数 相对 Phase 1 baseline 的降低比例
- 计算公式：`reduction_rate = (baseline_prompt_tokens - after_prompt_tokens) / baseline_prompt_tokens × 100%`
- 统计方法：排除缓存命中任务（避免 100% 降低的极端值），计算中位数而非平均值
- 目标：普通场景 >= 35%（硬门槛），力争 >= 40%（stretch goal）；长会话场景（20+轮）>= 50%（硬门槛）

**收益不可叠加声明**：
- 各策略的降本收益**不可算术相加**（存在重叠和互斥）
- 实际总降本通过端到端 benchmark 测量，非分项求和
- 例：Prompt Caching（-20%）+ 上下文去重（-10%）≠ -30%，实际可能只有 -22%（因部分去重内容已被缓存）

**产出文件**: 
- `scripts/eval/eval_tasks.py`
- `scripts/eval/compare_metrics.py`（新增）

### 4.5 简历素材沉淀
整理可写入简历的工程成果：

**可写简历的亮点**：
1. **子 Agent 双通道架构**
   - "设计并实现了轻量/隔离双形态子 Agent 混合调度机制，简单任务通过同进程 asyncio Task 秒级启动，高风险任务通过独立进程隔离，保障主应用稳定性"

2. **Agent 能力开放**
   - "将桌面宠物从纯聊天应用升级为具备文件操作、网络搜索、代码执行能力的 Agent Runtime，通过工具策略与安全边界控制风险"

3. **极致记忆系统**
   - "设计并实现极致四重记忆架构：Working Memory（显式偏好+冲突检测）、Rolling Summary（对话摘要，跨会话关联v2.1）、Profile Memory（用户画像+Embedding演化）、Workflow Memory（工作流参数泛化），配合语义检索、遗忘算法、激活抑制、记忆写入门禁、分层存储策略，实现记忆命中率 >=70% 的智能召回体系（时序感知v2.1、Embedding量化v2.1）"

4. **Token 极致优化体系**
   - "构建 A层12项直接落地 + B层3项条件实施 + C层4项实验验证的十七项极致策略（含Prompt Caching、KV Cache复用、模型分层路由、ContextPacker动态预算、上下文去重、响应缓存、本地命令bypass、查询规范化缓存、Schema按需注入、输出动态上限、Prompt压缩、自适应工具压缩），实现 prompt tokens 降低 35~50%（长会话场景 >=50%），高频查询零成本，达到生产级成本控制能力"

5. **流式执行反馈**
   - "集成 Agent 生命周期钩子系统，实现流式输出与细粒度状态反馈（THINKING/SEARCHING/REMEMBERING/PACKING），将用户等待时的信息黑盒变为透明过程"

6. **可观测性**
   - "建立统一 trace 与 benchmark 体系，量化评估 Agent 任务成功率、token 消耗、记忆命中率与延迟指标"

**产出文件**: `reports/lobuddy_v2_resume.md`

## 验收标准
- [ ] 3 个 skill 可正常注册和调用
- [ ] MCP/A2A 接口文件存在，测试桩通过
- [ ] 每次任务执行后生成 trace（含记忆命中记录）
- [ ] benchmark 可重复跑，输出改造前后对比报告
- [ ] **token 降低率 >= 35%**（长会话场景 >= 50%，力争 >= 40%）
- [ ] **记忆命中率 >= 70%**（语义检索确保相关记忆优先召回）
- [ ] 简历素材文档完成

**验证方式**:
```bash
# 1. Skill 测试
pytest tests/test_skills.py -v

# 2. MCP/A2A 测试桩
pytest tests/test_mcp_gateway.py -v
pytest tests/test_a2a_gateway.py -v

# 3. Benchmark
python scripts/eval/eval_tasks.py
# 输出 reports/after_metrics.json

# 4. 对比报告
python scripts/eval/compare_metrics.py \
  --before reports/baseline_metrics.json \
  --after reports/after_metrics.json \
  --output reports/comparison_report.md

# 5. 查看简历素材
type reports/lobuddy_v2_resume.md  # Windows; bash 用户用: cat reports/lobuddy_v2_resume.md
```

---

## 3. 与原版的主要差异

| 方面 | 原版 (8 Phase) | 本极致版 (4 Phase) |
|------|---------------|-------------------|
| **Phase 数量** | 8 个 | 4 个 |
| **可恢复状态机** | Phase 2 完整实现 checkpoint/恢复 | ⚠️ 缩小为"任务状态实时持久化 + 重启后可见未完成任务" |
| **记忆系统** | 4 类记忆 + write/retrieve policy | ✅ **极致四重记忆**：语义检索 + 冲突检测 + 遗忘算法 + 激活/抑制 + 分层存储 + nanobot原生整合 + 写入门禁（跨会话关联v2.1 + 时序感知v2.1 + Embedding量化v2.1） |
| **Token 优化** | 8 项优化 + ContextPacker + model router | ✅ **十七项极致策略**：A层12项直接落地 + B层3项条件实施 + C层4项实验验证（含本地bypass、查询规范化、Schema按需注入、输出动态上限） |
| **审批系统** | approve/reject/edit 完整流程 | ❌ 改为简单 guardrails（危险命令拦截 + 超长命令确认 + Token 预算告警） |
| **MCP/A2A** | Phase 6 完整实现 MCP Gateway | ⚠️ 预留接口 + 测试桩，不做重实现 |
| **工具开放** | Phase 6 | ✅ Phase 1——这是最大的用户价值 |
| **流式输出** | Phase 5 | ✅ Phase 3——与记忆/Token优化融合 |
| **Skills** | 5 个 skill | ✅ 3 个 skill（够用即可） |
| **评测维度** | 基础指标 | ✅ 增加 memory hit rate (>=70%)、token reduction rate (>=35%，力争>=40%) |

---

## 4. 目录结构（极致版）

```text
core/
  agent/
    subagent_runtime.py       # 抽象接口
    inprocess_runtime.py      # 轻量子 Agent
    isolated_runtime.py       # 隔离子 Agent
    subagent_policy.py        # 路由策略
    subagent_spec.py          # 扩展现有
    subagent_factory.py       # 保留现有
    nanobot_adapter.py        # 修改以支持流式、记忆、Token优化
  runtime/
    token_meter.py            # Token 分账
    context_packer.py         # 上下文预算分配（动态预算）
    prompt_cache_manager.py   # Prompt Caching管理（极致版新增）
    kv_cache_manager.py       # KV Cache复用（极致版新增，实验性）
    model_router.py           # 模型分层路由（极致版新增）
    context_deduplicator.py   # 上下文去重+增量（极致版新增）
    response_cache.py         # 响应缓存（极致版新增）
    prompt_minifier.py        # Prompt模板压缩（极致版新增）
    output_token_limiter.py   # 输出token动态上限（极致版新增）
    local_command_router.py   # 本地命令bypass（极致版新增）
    query_normalizer.py       # 查询规范化（极致版新增）
    task_checkpoint.py        # 任务状态持久化
  memory/
    working_memory_repo.py    # 显式偏好存储
    conflict_detector.py      # 冲突检测（极致版新增）
    memory_write_gate.py      # 记忆写入门禁（极致版新增）
    pending_memory.py         # 待确认记忆隔离区（极致版新增）
    memory_source_of_truth.py # 记忆真源定义（极致版新增）
    rolling_summary.py        # 对话滚动摘要
    session_linker.py         # 跨会话关联（v2.1延期，不阻塞v2.0）
    profile_memory.py         # 用户画像存储
    profile_extractor.py      # 画像推断器
    workflow_memory.py        # 工作流存储
    workflow_extractor.py     # 工作流识别器
    memory_retriever.py       # 统一记忆检索器（语义检索）
    embedding_engine.py       # Embedding引擎（极致版新增）
    embedding_quantizer.py    # Embedding量化压缩（v2.1延期，不阻塞v2.0）
    temporal_parser.py        # 时序表达式解析（v2.1延期，不阻塞v2.0）
    importance_scorer.py      # 记忆重要性评分（极致版新增）
    tiered_storage.py         # 分层存储（极致版新增）
    forgetting_engine.py      # 遗忘算法（极致版新增）
    nanobot_memory_bridge.py  # nanobot记忆整合（极致版新增）
  hooks/
    lobuddy_hook.py           # AgentHook 实现
  safety/
    guardrails.py             # 安全拦截
  skills/
    skill_loader.py           # Skill 加载器
    skill_selector.py         # Skill 懒加载选择器
  protocols/
    mcp_gateway.py            # MCP 预留接口
    a2a_gateway.py            # A2A 预留接口
  observability/
    tracer.py                 # Trace 记录
  storage/
    ability_repo.py           # 能力持久化
  tools/
    artifact_store.py         # 工具结果 Artifact 存储
    tool_narrower.py          # 工具集收缩器
    adaptive_compressor.py    # 自适应工具压缩（极致版新增）
    tool_schema_injector.py   # Tool Schema按需注入（极致版新增）
ui/
  settings_window.py          # 设置窗口
  streaming_message_widget.py # 流式消息组件
  token_display_widget.py     # Token 消耗显示
skills/
  document_summarizer.md
  web_researcher.md
  code_assistant.md
scripts/
  eval/
    baseline_run.py           # 改造前 baseline
    eval_tasks.py             # 改造后 benchmark
    compare_metrics.py        # 对比报告生成
  migrations/
    v2_memory_system.sql      # DB migration脚本
    v2_memory_system_rollback.sql  # DB rollback脚本
reports/
  baseline_metrics.json       # 改造前指标
  after_metrics.json          # 改造后指标
  comparison_report.md        # 对比报告
  lobuddy_v2_resume.md        # 简历素材
tests/
  test_subagent_runtime_mixed.py
  test_skills.py
  test_mcp_gateway.py
  test_a2a_gateway.py
  test_memory_system.py       # 四重记忆系统测试（含语义检索、冲突检测、写入门禁、遗忘算法；量化压缩v2.1、时序检索v2.1可选）
  test_token_optimization.py  # 十七项Token优化测试（含Prompt Caching、KV Cache、模型路由、响应缓存、本地bypass、自适应压缩）
  test_task_checkpoint.py
```

---

## 5. 执行约束

1. **每个 Phase 先修 bug，再增功能**
2. **任何新模块必须有测试**
3. **工具开放必须先有安全边界**（Phase 1 同时落地 Guardrails）
4. **不追求一步到位，追求可交付**
5. **记忆系统按层实现**：先 Working，再 Rolling，再 Profile，最后 Workflow
6. **记忆极致化按优先级**：先语义检索（Embedding引擎），再冲突检测，再工作流记忆，最后遗忘算法（跨会话关联v2.1、时序感知v2.1不纳入v2.0优先级）
7. **Token 优化按项实现**：先分账，再 Packer（动态预算），再 Prompt Caching，再 KV Cache，再模型路由，再响应缓存，再 Prompt压缩/自适应压缩，再懒加载/检索化/Artifact/Narrowing/去重
8. **每个 Phase 必须有可复现的验证命令**
9. **v2.0 范围冻结**：只交付 P0/P1 优先级文件 + A层全部 + B层可用项，P2/P3/C层统一延期到 v2.1

---

## 6. 最终验收标准

1. [ ] 基线 bug 修复完成，设置窗口可用
2. [ ] Agent 能使用工具完成实际任务（非聊天）
3. [ ] 双通道子 Agent 可用
4. [ ] 流式输出可见
5. [ ] **四重记忆系统可用**（偏好/摘要/画像/工作流全部可用，但跨会话关联/时序感知可延期到 v2.1）
6. [ ] **Token 优化 A层全部落地 + B层条件实施**
   - C层实验项不阻塞验收，PoC 失败可标记 WONTFIX
   - **B层不可用项可标记 WONTFIX，但必须附 Provider 能力验证记录**
7. [ ] **端到端 token 降低 >= 35%**（长会话 >= 50%，力争 >= 40%）
8. [ ] **记忆命中率 >= 70%**（语义检索确保相关记忆优先召回）
9. [ ] 3 个 skill 可调用
10. [ ] MCP/A2A 接口预留完成
11. [ ] benchmark 可跑，trace 可生成，改造前后对比报告可用
12. [ ] 简历素材可用

---

## 附录 B：Phase 排期与阻塞项分析

### 文件优先级矩阵

| 优先级 | 文件 | 阻塞项 | 可删减 |
|--------|------|--------|--------|
| **P0-阻塞** | `core/memory/embedding_engine.py` | 无 embedding 则语义检索不可用 | ❌ 不可删 |
| **P0-阻塞** | `core/memory/memory_retriever.py` | 无检索器则记忆系统不可用 | ❌ 不可删 |
| **P0-阻塞** | `core/runtime/context_packer.py` | 无 Packer 则 Token 优化无基础 | ❌ 不可删 |
| **P1-重要** | `core/memory/conflict_detector.py` | 无冲突检测则记忆质量下降 | ⚠️ v2.0必做 |
| **P1-重要** | `core/runtime/model_router.py` | 无路由则 B2 策略不可用 | ⚠️ v2.0必做 |
| **P1-重要** | `core/runtime/response_cache.py` | 无缓存则 A8 策略不可用 | ⚠️ v2.0必做 |
| **P2-增强** | `core/memory/session_linker.py` | 无跨会话关联则用户体验下降 | ✅ 延期到 v2.1，不阻塞 v2.0 |
| **P2-增强** | `core/memory/embedding_quantizer.py` | 无量化则存储多 400MB | ✅ 延期到 v2.1，不阻塞 v2.0 |
| **P2-增强** | `core/runtime/kv_cache_manager.py` | 实验性，失败不影响主流程 | ✅ 延期到 v2.1，可标记 WONTFIX |
| **P3- nice** | `core/runtime/prompt_minifier.py` | 仅节省 3-5% tokens | ✅ 延期到 v2.1，不阻塞 v2.0 |
| **P3- nice** | `core/memory/temporal_parser.py` | 无时序则"昨天"查询不可用 | ✅ 延期到 v2.1，不阻塞 v2.0 |

### 最小可交付集（MVP）
若时间/资源受限，优先保证以下子集：
1. **记忆 MVP**：`embedding_engine` + `memory_retriever` + `working_memory_repo` + `profile_memory`
2. **Token MVP**：`context_packer` + `token_meter` + `skill_selector` + `tool_narrower`
3. **安全 MVP**：`guardrails.py`（Phase 1 已完成）

### Phase 排期建议
- **Phase 1**（1 周）：Bug 修复 + 设置窗口 + 工具开放 + Guardrails + Token 分账
- **Phase 2**（1 周）：子 Agent 双通道 + 任务状态持久化
- **Phase 3**（2 周）：流式输出 + 记忆系统（P0+P1）+ Token 优化（A层+B层）
- **Phase 4**（0.5 周）：Skills + Benchmark + 简历素材
- **延期到 v2.1**：C层实验项 + P2/P3 增强项

---

## 附录 C：删减项声明（原版能力 → 当前处理）

| 原版能力 | 当前处理 | 说明 |
|---------|---------|------|
| 可恢复任务状态机（checkpoint + 崩溃恢复） | **缩小为"任务状态实时持久化 + 重启后可见未完成任务"** | 不实现自动恢复，但保留手动重试/取消 |
| 完整审批系统（approve/reject/edit + HITL） | **替换为简单 guardrails（危险命令拦截 + 超长命令确认 + Token 预算告警）** | 完整审批流延期到未来版本 |
| 8 项 Token 优化（model router） | **升级为十七项极致策略**（A层12项直接落地 + B层3项条件实施 + C层4项实验验证） | 不仅保留 model router，还新增 9 项前沿优化，含本地bypass/查询规范化/Schema按需注入 |
| MCP Gateway 完整实现 | **预留接口 + 测试桩** | 不做重实现，但保留扩展位 |
| A2A Gateway 完整实现 | **预留接口 + 测试桩** | 不做重实现，但保留扩展位 |
| 完整 Skills 系统（5 个 skill） | **最小可用版（3 个 skill）** | 其余 skill 后续按需添加 |
| 完整 Benchmark（50 条任务） | **20 条任务 + 前后对比** | 规模缩小但保留可比性 |

**关键原则**：以上删减项均为"延期"而非"放弃"。当前版本聚焦"可运行、可验证、可写简历"的最小闭环，删减项在后续迭代中按优先级逐步补齐。

---

## 附录 D：v2.0 单命令验收清单（实现完成后执行）

> **前提**：以下命令需在 Phase 1-4 全部完成后执行。当前仓库中这些测试文件、脚本**尚未存在**，它们是本文档的实现目标。

```bash
# 1. 安装依赖
pip install -e ".[memory]"

# 2. 启动应用
python -m app.main

# 3. v2.0 阻塞测试（全部通过 = v2.0 验收通过）
# 以下测试文件待创建（tests/test_token_optimization.py, tests/test_memory_system.py）
pytest tests/test_token_optimization.py::test_token_accounting -v
pytest tests/test_token_optimization.py::test_context_packer_dynamic_budget -v
pytest tests/test_token_optimization.py::test_skill_lazy_loading -v
pytest tests/test_memory_system.py::test_semantic_retrieval -v
pytest tests/test_token_optimization.py::test_tool_artifact -v
pytest tests/test_token_optimization.py::test_tool_narrowing -v
pytest tests/test_token_optimization.py::test_context_deduplication -v
pytest tests/test_token_optimization.py::test_response_cache -v
pytest tests/test_token_optimization.py::test_output_token_limiter -v
pytest tests/test_token_optimization.py::test_local_command_router -v
pytest tests/test_token_optimization.py::test_query_normalizer -v
pytest tests/test_token_optimization.py::test_tool_schema_injector -v
pytest tests/test_token_optimization.py::test_prompt_caching -v || echo "B1 unavailable, mark WONTFIX"
pytest tests/test_token_optimization.py::test_model_routing -v || echo "B2 unavailable, mark WONTFIX"
pytest tests/test_token_optimization.py::test_adaptive_compression -v || echo "B3 unavailable, mark WONTFIX"
pytest tests/test_token_optimization.py::test_token_reduction -v
pytest tests/test_token_optimization.py::test_long_session_token_reduction -v

# 4. 指标验证（脚本待创建：scripts/eval/compare_metrics.py）
python scripts/eval/compare_metrics.py \
  --before reports/baseline_metrics.json \
  --after reports/after_metrics.json \
  --output reports/comparison_report.md
# 检查：普通场景 >=35%，长会话 >=50%，记忆命中率 >=70%

# 5. DB migration 验证
sqlite3 data/lobuddy.db "SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1;"
# 预期：version = 2
```

---

## 附录 E：文档一致性自检摘要

| 检查项 | 结果 |
|--------|------|
| `session_linker` 全部引用 | 7/7 处标注 "v2.1延期" |
| `temporal_parser` 全部引用 | 5/5 处标注 "v2.1延期" |
| `embedding_quantizer` 全部引用 | 5/5 处标注 "v2.1延期" |
| `C层 3 项` 残留 | 0 处（已统一为 C层 4 项） |
| `40-50%` 残留 | 0 处（已统一为硬门槛35%/50%） |
| `B层4项` 残留 | 0 处（已统一为 B层3项） |
| `或 >=50%` 残留 | 0 处（已统一为"且"） |
| A1 测试名统一 | `test_token_accounting` |
| A4 测试名统一 | `test_semantic_retrieval` |
| v2.0/v2.1 边界冲突 | 0 处 |

---

*本极致版由 resume_updata.md 精简并增强而来。文档版本：v2.0-final（1453行）。本文档为**实现计划（Implementation Plan）**，所列测试文件、脚本、模块均为**待创建**目标，需在 4 个 Phase 执行期间逐步落地。核心改进：在不增加 Phase 数量的前提下，将记忆系统从"关键词匹配+四重分层"升级为"语义检索 + 冲突检测 + 跨会话关联(v2.1) + 遗忘算法 + 激活抑制 + 时序感知(v2.1) + Embedding量化压缩(v2.1) + 分层存储 + 记忆写入门禁 + 真源定义 + nanobot原生整合"的极致架构；将 Token 优化从"六项策略30%降低"升级为"A层12项直接落地 + B层3项条件实施 + C层4项实验验证"的十七项极致策略（含本地命令bypass、查询规范化缓存、Schema按需注入、输出动态上限），目标硬门槛35%/50%降本（力争40%），并提供明确的分层实施路径、DB迁移方案、指标统计口径与Phase排期。*
