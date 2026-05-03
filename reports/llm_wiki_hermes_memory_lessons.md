# LLM Wiki 与 Hermes 记忆机制可借鉴点分析报告

生成日期：2026-05-03  
面向对象：Lobuddy / nanobot 记忆与技能边界设计  
来源：

- Karpathy gist: <https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f>
- Hermes 持久记忆文档: <https://hermesagent.org.cn/docs/user-guide/features/memory>
- Hermes 记忆提供者文档: <https://hermesagent.org.cn/docs/user-guide/features/memory-providers>
- Vectorize 对 Hermes 四层记忆的解析: <https://vectorize.io/articles/hermes-agent-memory-explained>
- 用户提供的 B 站视频: <https://www.bilibili.com/video/BV17KoFBBEqM/>

说明：B 站页面未能通过当前浏览工具直接获取视频正文或字幕。Hermes 部分基于视频标题中的“四层记忆系统”线索，并使用 Hermes 文档与 Vectorize 文章交叉验证。

## 1. 总体判断

Karpathy 的 LLM Wiki 和 Hermes 的记忆系统解决的是同一个核心问题：不要把“记忆”简单等同于聊天历史或向量检索。高质量 agent 记忆必须分层：

1. 有些信息应该始终在 prompt 中，数量少、密度高、强约束。
2. 有些信息应该完整保存，但只在需要时 recall。
3. 有些经验不是事实，而是流程，应沉淀为 skill。
4. 有些知识不是一次性摘要，而是持续编译后的结构化知识库。
5. 任何自动写入系统都必须有边界、审计和 lint，否则长期会漂移。

对 Lobuddy 来说，最值得借鉴的不是某个具体文件格式，而是分层原则和写入纪律：

- 短热记忆要小而稳定。
- 完整历史要可查但不常驻。
- 项目/知识记忆要编译成可读、可维护的 wiki，而不是每次 RAG 重算。
- skill 是 procedural memory，和用户事实、项目事实分开。
- 外部 recall 是增强层，不能替代内置权威记忆。

## 2. Karpathy LLM Wiki 的核心优点

### 2.1 从“检索原文”升级为“持续编译知识”

Karpathy 的关键点是：传统 RAG 每次问题都重新检索和拼接 raw chunks，知识没有积累；LLM Wiki 则让 LLM 在 ingest 时把新来源整合到已有 wiki 中，更新实体页、主题页、综合页、矛盾说明和交叉引用。

可借鉴点：

- 记忆不应只是“存下来”，而应被编译成可复用结构。
- 每次问答产生的高价值分析也应该能回写到知识库。
- 对复杂项目，长期价值来自已维护的综合视图，而不是原始片段堆积。

对 Lobuddy 的含义：

- 目前 `memory_item` 更像结构化事实库，但还缺“项目 wiki / 综合页”层。
- `project_memory` 不应只是一组 bullet；应能逐步生成：
  - 项目概览页
  - 架构页
  - 决策记录
  - 问题与绕行方案
  - 术语/模块索引
  - 近期进展

### 2.2 三层架构清晰：Raw sources / Wiki / Schema

LLM Wiki 的三层是：

- raw sources：用户收集的原始材料，不被 LLM 修改，是源头事实。
- wiki：LLM 生成和维护的 Markdown 页面，负责摘要、实体、概念、比较、综合。
- schema：类似 `AGENTS.md` / `CLAUDE.md` 的维护协议，约定目录、格式、工作流和 lint。

可借鉴点：

- 事实源和生成物必须分开。
- LLM 可以拥有 wiki 写权限，但不能改 raw sources。
- 需要一个“记忆维护协议”，约束 agent 怎么写、什么时候写、怎么引用、怎么处理冲突。

对 Lobuddy 的含义：

- SQLite 可以继续作为结构化权威主存。
- Markdown 不应只是 projection，也可以扩展出“人类可读 wiki 层”。
- 需要新增类似 `MEMORY_SCHEMA.md` 或 `workspace/memory/AGENTS.md` 的维护协议，明确：
  - 哪些事实进 USER
  - 哪些事实进 SYSTEM/SOUL
  - 哪些事实进 PROJECT/MEMORY
  - 哪些沉淀为 skill
  - 哪些只保留在 session archive
  - 写入前需要哪些验证

### 2.3 Ingest / Query / Lint 三种操作值得直接吸收

LLM Wiki 把知识库维护拆成三类操作：

- Ingest：处理新来源，写摘要页，更新相关页面和 index/log。
- Query：回答问题，并把有价值的比较、分析、发现回写为页面。
- Lint：周期性查矛盾、陈旧声明、孤儿页、缺交叉引用、缺来源。

可借鉴点：

- 记忆系统不能只有“写入”，还要有“体检”。
- 查询结果如果有长期价值，应能成为新的知识制品。
- lint 比定期摘要更重要，因为长期记忆的主要失败模式是矛盾、重复、失效、无来源。

对 Lobuddy 的含义：

- 现有 `MemoryMaintenance` 只做过期和简单冲突处理，强度不够。
- 应增加 `MemoryLintService`：
  - 重复事实检测
  - 用户身份冲突
  - 系统身份冲突
  - project memory scope 错配
  - stale task/project facts
  - 无来源或低置信度事实
  - skill 与 memory 内容重复

### 2.4 index.md / log.md 是低成本导航层

Karpathy 提出：

- `index.md`：内容索引，列出页面、摘要、分类、元数据。
- `log.md`：时间线，记录 ingest、query、lint。

可借鉴点：

- 中等规模下，索引文件本身就能大幅降低检索复杂度。
- log 是 agent 理解最近发生过什么的低成本方式。
- 格式应稳定，便于 grep / rg / shell 工具处理。

对 Lobuddy 的含义：

- 可以在 `workspace/memory/` 生成：
  - `index.md`
  - `log.md`
  - `decisions.md`
  - `open_questions.md`
- `MemoryProjection` 每次刷新时维护 `index.md`。
- 所有自动记忆更新 append 到 `log.md`，包括来源、动作、置信度、被合并/拒绝原因。

### 2.5 Git + Markdown 是可审计记忆的现实方案

LLM Wiki 强调 wiki 是 Markdown git repo，天然有版本历史、分支和协作。

可借鉴点：

- 记忆变更应该能 diff。
- 回滚能力比“相信 agent 写对了”更可靠。
- 对人类协作，Markdown 比数据库记录更容易审查。

对 Lobuddy 的含义：

- SQLite 仍是权威主存，但每次 `MemoryPatch` 应产生审计事件。
- Markdown projection 可被 git 跟踪，用于人类检查差异。
- 不建议让 git 成为主存；建议让它成为审计和回滚辅助。

### 2.6 评论区实践：引用校验和写入网关非常重要

gist 评论中有一个大型实践案例，强调每条 claim 必须链接真实 source，写入前 validator 检查链接是否存在；还提到语义过滤、统一 gateway、MCP server、多源 ingest 等。

可借鉴点：

- 自动写入必须经过机械校验，不能只靠 prompt。
- source link / span anchor 能显著降低幻觉污染。
- 所有入口应走同一个 gateway 和 validator。

对 Lobuddy 的含义：

- 新增 `MemoryWriteGateway`，所有写入都走这里：
  - strong signal
  - exit analysis
  - background update
  - user manual edit
  - future Dream rewrite
  - future external provider sync
- 每条 memory 增加或强化 provenance：
  - source_type
  - source_session_id
  - source_message_id
  - source_task_id
  - source_file
  - evidence_span
  - write_reason

## 3. Hermes 四层记忆的核心优点

### 3.1 热记忆：小容量、始终注入、冻结快照

Hermes 内置两个小文件：

- `MEMORY.md`：约 2,200 字符，保存 agent 工作笔记、项目约定、环境事实、经验教训。
- `USER.md`：约 1,375 字符，保存用户身份、偏好、沟通风格。

它们在会话开始时以冻结快照注入 system prompt。会话中写入会落盘，但不会进入当前 session 的 system prompt，直到下个 session 才生效。

可借鉴点：

- 热记忆必须有硬预算。
- 冻结快照能稳定 prompt prefix，有利于缓存和行为一致性。
- “始终在上下文中”的内容必须少而精。

对 Lobuddy 的含义：

- 现在 `MemorySelector` 有预算，但还不够明确区分 hot memory 和 recall memory。
- 建议把 hot memory 明确拆成：
  - `hot_user_profile`：最多 500 tokens
  - `hot_agent_profile`：最多 300 tokens
  - `hot_project_context`：最多 800 tokens
- `NanobotAdapter.run_task()` 开始时生成一次 frozen bundle，任务执行期间不动态变更注入内容。

### 3.2 memory tool 只有 add / replace / remove，没有 read

Hermes 的 memory tool 没有 read 操作。原因是记忆已经在会话开始时注入，agent 应把它当当前上下文的一部分。修改通过 add/replace/remove 完成；replace/remove 使用唯一子字符串匹配。

可借鉴点：

- 写工具越小，行为越可控。
- 不提供 read 可以避免 agent 每次浪费 token 读取热记忆。
- replace/remove 需要唯一匹配，能降低误删误改。

对 Lobuddy 的含义：

- 可以增加 `memory_patch` 工具/内部接口，而不是让 agent 直接写数据库或 Markdown。
- 操作限定为：
  - add
  - replace
  - merge
  - deprecate
  - remove
- replace/deprecate 应要求 `target_id` 或唯一 `old_text`，不能模糊更新。

### 3.3 保存/忽略规则明确

Hermes 文档明确区分应保存和应忽略：

应保存：

- 用户偏好
- 环境事实
- 修正信息
- 项目约定
- 已完成工作
- 明确要求记住的信息

应忽略：

- 琐碎信息
- 容易重新发现的通用事实
- 原始大段日志/代码
- 会话一次性信息
- 已在上下文文件中的信息

可借鉴点：

- 记忆质量主要取决于拒绝写入的能力。
- 保存规则需要产品化，而不是藏在 prompt 里。
- 用户应该能理解 agent 为什么记或不记。

对 Lobuddy 的含义：

- 现有 `MEMORY_UPDATE_PROMPT` 已有类似规则，但需要下沉成代码级 policy。
- 新增 `MemoryPolicy`：
  - `should_save(item)`
  - `target_type(item)`
  - `reject_reason(item)`
  - `requires_user_review(item)`

### 3.4 安全扫描是必须项

Hermes 在接收记忆前扫描提示注入、凭证外泄、SSH 后门、不可见 Unicode 等风险。

可借鉴点：

- 记忆会被注入 system prompt，因此它比普通聊天内容风险更高。
- 任何持久记忆写入都必须做安全扫描。
- 不能只过滤 API key；还要过滤 prompt injection 和行为劫持。

对 Lobuddy 的含义：

- 当前 `_sanitize_memory_text()` 主要过滤密钥/邮箱类模式，不够。
- 建议新增：
  - prompt injection pattern
  - tool exfiltration pattern
  - hidden unicode/control chars
  - shell backdoor snippets
  - “ignore previous instructions” 类持久注入
  - URL/文件路径风险标签

### 3.5 冷 recall：完整历史进 SQLite + FTS，按需搜索

Hermes 把所有 CLI 和消息会话存到 SQLite，并提供 `session_search` 工具。热记忆始终在 prompt 中；完整历史不常驻，只有需要时搜索并摘要。

可借鉴点：

- 完整历史和热记忆必须分离。
- 冷 recall 适合回答“之前是否讨论过 X”。
- FTS 是足够务实的第一版，不必一开始就上向量库。

对 Lobuddy 的含义：

- Lobuddy 已有 `ChatRepository`，这是天然 session archive。
- 需要补一个 `session_search` 工具给 nanobot：
  - 查询 Lobuddy `chat_message`
  - FTS5 或 LIKE fallback
  - 返回摘要而不是原始长历史
- 这样可以减少把太多 episodic memory 提前塞入 prompt。

### 3.6 技能是 procedural memory，不应混入事实记忆

Hermes 把 skills 作为第三层：复杂任务完成后写可复用 skill 文档，保存 approach、tools used、steps that worked。它和 prompt memory 的触发时机不同：skill 是任务完成后的反应式沉淀。

可借鉴点：

- “怎么做”不应写进 USER/MEMORY 事实区。
- 复杂工具流程应沉淀为 skill。
- skill 的评价指标应是复用成功率，而不是事实置信度。

对 Lobuddy 的含义：

- `procedural_memory` 与 `SkillManager` 当前有重叠风险。
- 建议定义：
  - `procedural_memory`：短事实，描述已有工作流偏好或经验。
  - `SkillRecord`：完整操作步骤、工具顺序、失败处理、适用条件。
- 任务完成后根据 `tools_used` 自动生成 `SkillCandidate`，但必须进入 review 或 validator。

### 3.7 外部 provider 是叠加层，不替代内置记忆

Hermes 外部 provider 的模式是：

- 内置 `MEMORY.md` / `USER.md` 始终启用。
- 外部 provider 作为增强层。
- 每轮前后台预取相关记忆。
- 每轮后同步对话。
- 会话结束时提取记忆。
- 镜像内置记忆写入。
- 添加 provider 特定工具。

可借鉴点：

- 外部记忆不要抢主存权威。
- 外部 provider 负责 recall / entity resolution / semantic search / graph。
- 内置热记忆保证离线、可解释、稳定。

对 Lobuddy 的含义：

- 如果未来接 Honcho/Mem0/Hindsight，不应让它直接改 Lobuddy SQLite。
- 应设计 `ExternalMemoryProvider` 接口：
  - `prefetch(query, context)`
  - `sync_turn(turn)`
  - `extract_session(session_id)`
  - `mirror_hot_memory(item)`
  - `recall(query)`
- 外部结果进入 prompt 时要标注来源和置信度。
- 外部 provider 建议只做 recall candidate，最终长期事实仍由 `MemoryWriteGateway` 批准。

## 4. 对 Lobuddy 当前架构的具体借鉴方案

### 4.1 建议目标分层

| 层 | 名称 | 内容 | 存储 | 是否常驻 prompt |
| --- | --- | --- | --- | --- |
| L0 | Hot profile | 用户偏好、agent 身份、当前项目最小上下文 | SQLite + frozen bundle | 是 |
| L1 | Structured facts | user/system/project/episodic/procedural memory items | SQLite | 按预算选择 |
| L2 | Session archive | 完整聊天历史、工具结果摘要 | SQLite `chat_message` + FTS | 否，按需 search |
| L3 | Project wiki | 项目概览、决策、模块、问题、索引、日志 | Markdown projection / git | 按需读 |
| L4 | Skills | 可复用流程和工具策略 | SQLite skill_record + `workspace/skills` | 摘要常驻，全文按需 |
| L5 | External recall | 语义搜索、实体关系、跨会话建模 | provider-specific | 预取摘要按需注入 |

这比单纯“SQLite memory + Markdown projection”更清晰，也比让 nanobot Dream 直接写文件更安全。

### 4.2 建议新增组件

#### MemoryWriteGateway

统一所有记忆写入：

- 输入：candidate patch
- 执行：
  - schema validation
  - policy classification
  - secret scan
  - prompt injection scan
  - duplicate/conflict detection
  - provenance check
  - budget check
  - review routing
- 输出：
  - accepted
  - rejected
  - needs_review
  - merged

#### MemoryLintService

周期性检查：

- 同一用户身份多版本冲突
- agent 名称冲突
- 项目事实过期
- scope 错误
- 低置信度长期驻留
- orphan wiki pages
- skill 与 memory 重复
- 无来源的高重要度事实

#### SessionSearchTool

给 nanobot 使用的冷 recall 工具：

- 查询 Lobuddy SQLite chat history。
- FTS5 优先，LIKE fallback。
- 返回摘要和消息定位。
- 不直接返回大量原文。

#### ProjectWikiProjection

把 `project_memory` 编译为 Markdown wiki：

```text
workspace/memory/
  index.md
  log.md
  overview.md
  decisions.md
  architecture.md
  open_questions.md
  modules/
  sources/
```

#### SkillLearningPipeline

任务完成后：

1. 判断是否值得沉淀 skill。
2. 提取工具顺序、关键步骤、失败点。
3. 生成 candidate。
4. validator 检查。
5. 写入 `skill_candidate`。
6. 审批后投影到 `workspace/skills`。
7. 使用后记录 success/failure。

### 4.3 建议改造 nanobot Dream

当前 nanobot Dream 的思路可借鉴，但写入方式不适合 Lobuddy。

建议：

- 保留 Dream 的两阶段思想：
  1. 分析历史，找出值得长期化的信息。
  2. 生成结构化 patch。
- 禁止 Dream 直接 `edit_file` 修改 `USER.md`、`SOUL.md`、`MEMORY.md`。
- 改为：

```text
nanobot Dream analysis
  -> MemoryPatch JSON
  -> MemoryWriteGateway
  -> SQLite authoritative memory
  -> Markdown/wiki projection
```

这能同时获得 Dream 的反思能力和 Lobuddy 的数据一致性。

## 5. 不建议照搬的地方

### 5.1 不建议让 Markdown 成为 Lobuddy 主存

Karpathy LLM Wiki 适合知识库，Markdown 是合理主存。但 Lobuddy 是桌面应用，有 UI、设置、状态、维护、加密和测试需求。SQLite 更适合作为权威数据层。

建议：Markdown 做 projection / review / wiki，不做唯一主存。

### 5.2 不建议只靠小文件记忆

Hermes 的小文件热记忆清晰，但 Lobuddy 已经有结构化 memory schema。只用 `MEMORY.md` / `USER.md` 会丢掉：

- status
- confidence
- importance
- source ids
- scope
- lifecycle
- review state

建议：学习 Hermes 的预算和冻结快照，而不是退化成两个文件。

### 5.3 不建议把外部 provider 作为第一阶段核心依赖

外部 provider 能力强，但会引入：

- 成本
- 隐私问题
- license 风险
- 网络依赖
- 数据迁移复杂度

建议：先把本地 SQLite + FTS + wiki projection 做扎实，再抽象 provider 接口。

### 5.4 不建议自动写 skill 直接生效

Hermes 的 skill 自进化很有价值，但对 Lobuddy 要加审批和安全校验。skill 本质上是 agent 行为扩展，错误 skill 会持续放大。

建议：自动生成 candidate，默认人工 review；后续再考虑高置信自动 approve。

## 6. 优先级建议

### P0：记忆边界和热记忆预算

1. 明确 Hot Memory Bundle：
   - user profile <= 500 tokens
   - system profile <= 300 tokens
   - active project context <= 800 tokens
2. Adapter 每次任务开始生成 frozen context。
3. 投影文件加 generated header。
4. 禁止 nanobot 直接写 Lobuddy 投影文件。

### P1：Session Search

1. 给 `chat_message` 加 FTS5。
2. 实现 `session_search` tool。
3. memory update prompt 中减少大段历史，改为必要时 recall。

### P2：Project Wiki Projection

1. 将 `project_memory` 投影到 `workspace/memory/MEMORY.md`。
2. 新增 `index.md` 和 `log.md`。
3. 记录每次 MemoryPatch 的时间线。

### P3：Memory Lint + Write Gateway

1. 所有写入统一走 gateway。
2. 增加 prompt injection / secret / duplicate / conflict 校验。
3. 周期性 lint，并输出 review 列表。

### P4：Skill Learning Pipeline

1. 接入任务完成后的 skill candidate 提取。
2. 审批后写入 `workspace/skills`。
3. 使用后记录成功率。
4. disabled/archive 同步移除文件投影。

### P5：External Provider Interface

1. 先定义接口，不先绑定具体厂商。
2. 本地优先：SQLite/FTS/可选向量索引。
3. provider 输出只作为 recall candidate。
4. 长期事实仍由 Lobuddy gateway 批准。

## 7. 对上一份 nanobot/Lobuddy 边界报告的补充修正

上一份报告建议 Lobuddy SQLite 为长期事实权威、nanobot 只读投影。结合 LLM Wiki 和 Hermes 后，可以补充三点：

1. 只做 SQLite 结构化 memory 不够。需要一个可读、可 lint、可 git diff 的 Project Wiki Projection。
2. 只做 prompt 注入不够。需要 session_search 作为冷 recall，避免把历史压进 hot context。
3. skill 不只是 UI 面板能力，而是 procedural memory。它应该有单独生命周期、候选生成、审批、使用统计和衰退机制。

因此最终方向应是：

```text
SQLite structured memory = authoritative facts
Markdown wiki projection = human/agent readable compiled knowledge
Session archive + search = full history recall
Skill manager = procedural memory
External provider = optional semantic/graph recall layer
Memory gateway + lint = write discipline
```

## 8. 关键落地判断

如果只做一件事，优先做 `MemoryWriteGateway`。因为后续无论接 Dream、skill learning、session_search 还是 external provider，都需要统一写入纪律。

如果做两件事，第二件是 `session_search`。它能立刻降低 hot memory 膨胀，解决“完整历史不该常驻但需要可找回”的问题。

如果做三件事，第三件是 `ProjectWikiProjection`。这是把 Karpathy LLM Wiki 的长期复利引入 Lobuddy 的关键。

