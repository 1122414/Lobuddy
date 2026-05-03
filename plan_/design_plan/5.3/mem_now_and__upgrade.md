# Lobuddy 记忆系统现状诊断与 5.3 可观测统一记忆升级方案

**生成日期：** 2026-05-03
**依赖报告：**
- `reports/nanobot_lobuddy_boundary_analysis.md` — nanobot/Lobuddy 系统边界分析
- `reports/llm_wiki_hermes_memory_lessons.md` — Karpathy LLM Wiki + Hermes 记忆机制借鉴

---

## 第零部分：审查结论与强制修订

### 0.1 审查结论

该 5.3 升级计划**总体可行**，方向也符合前述升级理论：

- 符合 Karpathy LLM Wiki 的核心思想：SQLite 作为权威事实层，Markdown/Wiki 作为可读、可 lint、可 diff 的编译知识层。
- 符合 Hermes 四层记忆思想：Hot Memory 小而冻结，完整历史通过 cold recall 搜索，skill 单独作为 procedural memory，外部 provider 只作为增强 recall 层。
- 符合 nanobot/Lobuddy 边界原则：Lobuddy 管长期事实和产品治理，nanobot 管执行循环、工具、provider、短期 session 上下文和 skill 消费。

但原计划存在几个需要立即补强的边界条件。若不补，实施后仍可能出现“看似统一、实际漂移”的问题：

1. `/dream` 不能只靠 tool hook 拦截，因为 nanobot slash command 在 tool call 前就会被 command router 处理。
2. `MemoryWriteGateway` 不能被塞进 `MemoryService.save_memory()` 内部形成循环依赖。正确边界是：Gateway 是外层写入门，MemoryService 是内层领域服务。
3. `session_search` 会把历史片段注入模型上下文，本质上是把本地聊天历史发送给 LLM provider，必须有用户可见开关、范围限制和脱敏。
4. 自定义 `session_search` 必须实现 nanobot `Tool` 协议，而不是普通 Python class。
5. 自动 skill 学习不能默认直接启用，应默认生成 candidate，经过 validator 和用户审批后再激活。

### 0.2 修改后的合规性判断

补齐本节约束后，5.3 计划可以成立。完成后的 Lobuddy 记忆系统会变得清晰：

```text
SQLite MemoryRepository      = 长期事实权威
MemoryWriteGateway           = 所有长期记忆写入纪律
MemorySelector Frozen Bundle = 热记忆注入
SessionSearchTool            = 冷历史 recall
ProjectWikiProjection        = 编译后的项目知识视图
SkillManager                 = procedural memory 生命周期
nanobot                      = 执行内核与上下文消费者
```

一句话边界：**Lobuddy 写长期记忆，nanobot 读投影和调用工具；nanobot 如果发现值得记住的内容，只能提交 patch/candidate，不能直接改长期事实文件。**

### 0.3 不得突破的硬边界

以下边界属于验收红线：

- 不允许 nanobot 直接写 `workspace/USER.md`、`workspace/SOUL.md`、`workspace/memory/MEMORY.md`。
- 不允许 Dream 直接编辑 Lobuddy 投影文件；若后续启用 Dream，只能输出 `MemoryPatch`。
- 不允许 disabled/archived skill 继续保留在 `workspace/skills/<name>/SKILL.md` 并被 nanobot 加载。
- 不允许任何长期记忆写入绕过 `MemoryWriteGateway`，但允许测试或迁移脚本显式使用底层 repository。
- 不允许 `session_search` 默认无限搜索全部历史；必须限制范围、结果长度、脱敏，并由设置项控制是否启用。
- 不允许外部 memory provider 直接写 Lobuddy SQLite；外部结果只能作为 recall candidate 或 patch candidate。

### 0.4 必须补充的工程边界条件

以下条件不改变总体方案，但必须进入实现验收：

| 边界条件 | 原因 | 验收方式 |
| --- | --- | --- |
| 写入幂等 | strong signal、exit analysis、background update 可能重复处理同一事实 | 同一输入重复执行不会生成重复 active memory |
| 并发写入锁 | UI 写入、后台更新、退出分析、maintenance 可能并发 | `MemoryWriteGateway` 使用 SQLite transaction，必要时按 memory type/scope 加锁 |
| 投影原子性 | Markdown 投影会被 nanobot 读取，半写文件会污染 prompt | 所有 projection 使用 atomic write，失败不替换旧文件 |
| FTS 同步 | `chat_message_fts` 若不维护触发器会漏数据 | 插入/更新/删除 chat_message 后 FTS 可检索一致 |
| 迁移可回滚 | 5.3 会移动/删除 disabled skill 文件、生成新投影 | Phase 1 前生成 migration report，不直接丢弃原始文件 |
| 低置信度处理 | 低置信记忆不能进入 hot prompt | low confidence 默认 `NEEDS_REVIEW` 或 rejected，不参与 hot bundle |
| prompt injection 持久化防护 | memory 会进入 system prompt，风险高于普通聊天 | gateway 对所有写入做 injection/secret/control char scan |
| 模型供应商隐私 | session_search 会将历史片段送入 LLM provider | 设置项可关闭，UI/配置说明明确，结果脱敏且限长 |
| 测试覆盖 | 该升级触碰记忆权威边界，回归风险高 | 新增 gateway、projection、dream block、session_search、skill lifecycle 测试 |

## 第一部分：现状诊断

### 1.1 当前记忆系统的三套并存

Lobuddy 当前存在 **三套记忆系统** 并行运行，彼此之间缺乏明确的单写者和统一的读写纪律：

| 系统 | 存储 | 角色 | 主要操作 |
|------|------|------|----------|
| **Lobuddy SQLite Memory** | `memory_item` 表（SQLite） | 产品层长期事实主存 | `MemoryService` 的 save/patch/apply_ai_response |
| **Lobuddy Markdown Projection** | `workspace/USER.md`, `SOUL.md`, `data/memory/*.md` | SQLite → Markdown 投影 | `MemoryProjection.project_all()` 每次刷新覆盖 |
| **nanobot File Memory** | `workspace/USER.md`, `SOUL.md`, `MEMORY.md`, `history.jsonl` | 执行内核的上下文消费 | `MemoryStore` 读/写, `Dream` 自动编辑长期文件 |

### 1.2 核心混乱点（按严重程度排序）

#### 🔴 P0：双重写者冲突（`workspace/USER.md` & `workspace/SOUL.md`）

```
Lobuddy MemoryProjection ──写入──> workspace/USER.md
                                    workspace/SOUL.md     <──写入── nanobot Dream/MemoryStore
                                    
Lobuddy SQLite ──不知道──> nanobot Dream 的修改
nanobot Dream ──不知道──> Lobuddy 投影会覆盖自己的修改
```

**实际后果：**
- Lobuddy 刷新投影时会覆盖 nanobot Dream 的修改
- 或者 Dream 修改被 nanobot 暂时读到，但 UI/设置/排错都看不到
- `workspace/USER.md` 和 `SOUL.md` 成为事实上的冲突区，无法确定哪个版本是权威

**代码证据：**
- Lobuddy 写：`memory_projection.py:84` → `workspace/USER.md`，`:90` → `workspace/SOUL.md`
- nanobot 写：`memory.py:48-49` → `write_soul()` / `write_user()` 直接文件写入
- nanobot Dream 写：`memory.py:519` → 通过 `edit_file` 直接修改长期文件

#### 🔴 P1：项目记忆投影路径不对齐

```
Lobuddy project_memory ──投影──> data/memory/PROJECT.md    ← nanobot 默认不读
                                
nanobot 默认读取 ──> workspace/memory/MEMORY.md            ← Lobuddy 不投影到这里
```

**实际后果：**
- nanobot 的 `ContextBuilder` 把 `workspace/memory/MEMORY.md` 读入 system prompt 作为 Long-term Memory
- 但 Lobuddy 的项目记忆从未投影到这个路径
- 导致 nanobot 执行任务时**看不到项目记忆**，除非通过 adapter 的 `Lobuddy Memory Context` 注入

#### 🟡 P2：nanobot Dream 拥有绕过 Lobuddy 写入纪律的**潜在能力**（latent risk）

**现状核实：** 当前 Lobuddy 流程中，Dream **未被主动触发**（`nanobot_adapter.py` 和 `config_builder.py` 均无 Dream 引用）。但 nanobot 的 Dream 作为 `MemoryStore` 的标准功能始终存在，一旦通过以下任一方式被触发，就会绕过所有 Lobuddy 写入纪律：
- 用户在聊天中输入 `/dream` 命令
- Heartbeat/Cron 机制周期性唤醒 Dream
- 程序化调用 `bot.memory_store.dream()`

```
nanobot Dream（如果被触发）
  ├── 分析 history.jsonl + 长期记忆文件
  ├── 直接 edit_file 修改 USER.md / SOUL.md / MEMORY.md  ← 绕过 Lobuddy SQLite
  └── 产生 GitStore commit                                ← 无法映射到 MemoryItem
```

**潜在风险：**
- Dream 写入不经过 `_sanitize_memory_text()` 安全扫描
- Dream 写入不经过 confidence/importance/scope 字段验证
- Dream 写入不会触发 `_refresh_projections()`
- GitStore 审计和 MemoryItem 审计是两条平行线
- **此为预防性修复**，当前尚未观测到实际冲突，但边界不清会导致未来难以排查的漂移

#### 🟡 P3：热记忆没有硬预算，动态注入不稳定

当前 `MemorySelector` 有 char budget（`memory_prompt_budget_chars`），但：
- 不区分 "hot"（始终注入）和 "cold"（按需检索）
- 不冻结注入快照 → 任务执行期间内存可能变化
- Hermes 和 LLM Wiki 都强调：热记忆必须**小且冻结**

#### 🟡 P4：没有冷 recall 机制（session search）

当前：
- Lobuddy 有 `ChatRepository`（完整会话历史）
- nanobot 有 `workspace/sessions/*.jsonl`（执行轨迹）
- **但 agent 执行时无法搜索这些历史**
- Hermes 的最佳实践：热记忆常驻 prompt，完整历史通过 `session_search` 工具按需检索

#### 🟡 P5：skill 可见性不完整

```
Lobuddy SkillManager ──disabled/archived──> SQLite skill_record.status 改变
                                            workspace/skills/<name>/SKILL.md 仍存在 ← nanobot 仍加载
```

**实际后果：**
- `SkillManager.disable_skill()` 只更新 SQLite 状态，不移除文件
- `archive_skill()` 复制到 archive 目录，但原文件仍在 workspace
- nanobot `SkillsLoader` 只看文件存在性，不查询 Lobuddy 状态

#### 🟡 P6：app 初始化未注入 SkillManager

```python
# app/main.py 现状
self.skill_maintenance = SkillMaintenance(settings)  # 没传 manager
# → maintenance 默认空跑，不变灰/过期/归档任何技能
```

#### 🟡 P7：无统一写入网关（MemoryWriteGateway）

当前写入路径分散在多个入口：
1. `_sync_strong_signal_memory()` → 直接 `upsert_identity_memory()`
2. `_run_memory_update()` → nanobot 生成 JSON → `apply_ai_response()` → `apply_patch()`
3. `save_memory()` / `save_memories()` → 直接 `_repo.save()`
4. nanobot Dream → `edit_file()` → 完全绕过 Lobuddy

每个入口的安全扫描、校验、审计日志强度不一致。

#### 🟡 P8：无记忆 lint/体检机制

`MemoryMaintenance` 只做过期清理和简单冲突检测。缺少：
- 重复事实检测
- 身份冲突（多个 user name 同时 active）
- 项目记忆 scope 错配
- 低置信度长期驻留
- skill 与 memory 内容重复

#### 🟡 P9：procedural_memory 与 SkillManager 重叠未定义

- `MemoryType.PROCEDURAL_MEMORY` schema 已存在但几乎不写入
- `SkillManager` 管理 procedure 但生命周期独立
- 两者边界未定义：什么进 `procedural_memory`，什么进 `SkillRecord`？

#### 🟡 P10：provenance 不完整

`MemoryItem` schema 有 `source_session_id` 和 `source_message_id` 字段，但：
- `_sync_strong_signal_memory()` 写入时不填充这些字段
- `apply_patch()` 写入时不记录来源 session
- 无法追溯 "这条记忆是从哪次对话来的"

---

### 1.3 当前数据流全景（问题标记版）

```
┌────────────────────────────────────────────────────────────────────┐
│                          当前数据流（问题版）                          │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  UI ──用户消息──> ChatRepository(SQLite)                            │
│  │                                                                 │
│  ▼                                                                 │
│  TaskManager ──> NanobotAdapter.run_task()                         │
│  │               │                                                 │
│  │               ├─① strong_signal → 直接写 MemoryItem           │
│  │               ├─② build_prompt_context → 动态选记忆注入 prompt  │
│  │               ├─③ nanobot 执行（读 workspace/SOUL.md 等）       │
│  │               │   └── ⚠️ Dream 有能力编辑投影文件（latent risk） │
│  │               └─④ 任务后 AI 生成 patch → apply_ai_response    │
│  │                                                                 │
│  MemoryService ──> MemoryRepository(SQLite)                        │
│  │                 ├── ❌ 不记录 provenance（session_id 等）        │
│  │                 └── MemoryProjection ──> workspace/{USER,SOUL}.md│
│  │                      └── ❌ project_memory 不到 workspace/memory/ │
│  │                                                                 │
│  nanobot ContextBuilder ──读──> workspace/{USER,SOUL}.md           │
│  │                              ❌ 不读 workspace/memory/MEMORY.md  │
│  │                                 （因为没有 Lobuddy 投影到这里）    │
│  │                                                                 │
│  nanobot Dream ──edit_file──> workspace/{USER,SOUL,MEMORY}.md     │
│                  ❌ 绕过 Lobuddy SQLite 和所有安全扫描                │
│                                                                     │
│  SkillManager ──写──> workspace/skills/<name>/SKILL.md            │
│  │                    ❌ disable/archive 不移除文件                 │
│  │                    ❌ SkillMaintenance 空跑                     │
│  │                                                                 │
│  nanobot SkillsLoader ──扫描──> workspace/skills/                  │
│                         ❌ 不知道 Lobuddy skill status              │
└────────────────────────────────────────────────────────────────────┘
```

---

## 第二部分：5.3 升级方案

### 2.1 目标架构

```
┌──────────────────────────────────────────────────────────────┐
│                     目标架构（5.3）                            │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────── 写入层 ────────────────────┐          │
│  │                                               │          │
│  │  所有入口 ──> MemoryWriteGateway               │          │
│  │              ├─ schema validation              │          │
│  │              ├─ _sanitize_memory_text()        │          │
│  │              ├─ prompt injection scan          │          │
│  │              ├─ duplicate/conflict detection    │          │
│  │              ├─ provenance 自动填充             │          │
│  │              ├─ budget check                   │          │
│  │              └─ review routing                 │          │
│  │                   │                            │          │
│  │                   ▼                            │          │
│  │         MemoryRepository(SQLite) ←权威主存      │          │
│  │                   │                            │          │
│  │                   ▼                            │          │
│  │         MemoryProjection → Markdown 投影        │          │
│  │         （所有投影文件加 generated header）       │          │
│  └───────────────────────────────────────────────┘          │
│                                                              │
│  ┌─────────────────── 消费层 ────────────────────┐          │
│  │                                               │          │
│  │  L0 Hot Context (frozen bundle)               │          │
│  │    ├── user_profile ≤ 500 tokens              │          │
│  │    ├── system_profile ≤ 300 tokens            │          │
│  │    └── active project context ≤ 800 tokens    │          │
│  │                                               │          │
│  │  L1 Structured Memory (budget-based)          │          │
│  │    └── episodic / procedural / additional     │          │
│  │        project_memory items                   │          │
│  │                                               │          │
│  │  L2 Session Archive (cold recall)             │          │
│  │    ├── ChatRepository FTS5 search             │          │
│  │    └── session_search tool for nanobot        │          │
│  │                                               │          │
│  │  L3 Project Wiki (readable projection)        │          │
│  │    ├── workspace/memory/MEMORY.md             │          │
│  │    ├── workspace/memory/index.md              │          │
│  │    └── workspace/memory/log.md                │          │
│  │                                               │          │
│  │  L4 Skills (procedural, lifecycle-managed)    │          │
│  │    ├── SkillManager SQLite → 状态权威          │          │
│  │    └── workspace/skills → active 投影          │          │
│  └───────────────────────────────────────────────┘          │
│                                                              │
│  ┌─────────────────── 体检层 ────────────────────┐          │
│  │  MemoryLintService                            │          │
│  │    ├─ 重复事实检测                              │          │
│  │    ├─ 身份冲突检测                              │          │
│  │    ├─ stale fact 检测                          │          │
│  │    ├─ 低置信度长期驻留告警                       │          │
│  │    └─ skill-memory 内容重复检测                 │          │
│  └───────────────────────────────────────────────┘          │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 落地方案总览

| 优先级 | 任务 | 类型 | 预估工作量 | 依赖 |
|--------|------|------|-----------|------|
| **P0-1** | 统一写入网关 MemoryWriteGateway | 新增组件 | 中 | 无 |
| **P0-2** | 投影文件加单写者声明 + 补 project→MEMORY.md | 修改现有 | 小 | 无 |
| **P0-3** | 禁用 Lobuddy 模式下 nanobot Dream 直接写文件 | 修改现有 | 小 | 无 |
| **P0-4** | Hot Memory Bundle + Frozen Snapshot | 修改现有 | 中 | 无 |
| **P1-1** | 创建 session_search tool | 新增组件 | 中 | 无 |
| **P1-2** | 补齐 skill 边界（disable/archive 移除文件） | 修改现有 | 小 | 无 |
| **P1-3** | app 初始化注入 SkillManager | 修改现有 | 小 | 无 |
| **P2-1** | 创建 MemoryLintService | 新增组件 | 中 | P0-1 |
| **P2-2** | Project Wiki Projection（index.md / log.md） | 新增组件 | 中 | P0-2 |
| **P2-3** | 强化内存写入 provenance | 修改现有 | 小 | P0-1 |
| **P3-1** | procedural memory + skill 边界定义 | 设计 + 实现 | 中 | 无 |
| **P3-2** | Skill 学习管线 | 新增组件 | 大 | P1-2, P1-3 |

---

### 2.3 P0 详细方案：先止血

#### P0-1：创建 MemoryWriteGateway

**文件：** `core/memory/memory_write_gateway.py`（新增）

**接口：**

```python
class MemoryWriteGateway:
    """统一记忆写入网关。所有长期记忆写入必须经过此网关。"""

    def __init__(self, memory_service: MemoryService, settings: Settings):
        ...

    async def submit_patch(self, patch: MemoryPatch, context: WriteContext) -> WriteResult:
        """
        统一入口。
        1. schema validation (Pydantic)
        2. secret scan (_sanitize_memory_text)
        3. prompt injection scan (新增)
        4. duplicate/conflict detection (_find_similar)
        5. provenance enrichment (填充 source_session_id 等)
        6. policy check (should_save / target_type / reject_reason)
        7. budget check
        8. review routing (high importance → needs_review, low confidence → pending)
        9. apply via MemoryService.apply_patch()
        """
        ...

class WriteContext(BaseModel):
    """写入上下文"""
    source: str  # "strong_signal" | "ai_patch" | "dream" | "manual" | "external_provider"
    session_id: str | None = None
    task_id: str | None = None
    message_id: str | None = None
    triggered_by: str  # "adapter" | "dream" | "skill_learning" | etc.

class WriteResult(BaseModel):
    accepted: list[MemoryItem]
    rejected: list[Rejection]
    needs_review: list[MemoryItem]

class Rejection(BaseModel):
    item_content: str
    reason: str  # "low_confidence" | "duplicate" | "secret_found" | "prompt_injection" | "policy_reject"
```

**改造接入点：**
- `NanobotAdapter._run_memory_update()` → `gateway.submit_patch()`
- `NanobotAdapter._sync_strong_signal_memory()` → `gateway.submit_patch()`
- `MemoryService.save_memory()` / `apply_patch()` 保持为底层领域服务，不反向依赖 gateway
- UI、adapter、exit analysis、manual edit、future Dream rewrite 等外部写入入口 → 统一调用 `gateway.submit_patch()`
- 未来 Dream 重写 → `gateway.submit_patch()`

**边界修正：**

`MemoryWriteGateway` 是外层写入门，不是 `MemoryService` 的内部依赖。否则会形成：

```text
Gateway -> MemoryService.apply_patch()
MemoryService.save_memory() -> Gateway
```

这种循环会让测试、迁移、bootstrap 和低层 repository 操作变得难以控制。正确分层：

```text
UI / Adapter / ExitAnalyzer / Future Dream / Manual Review
  -> MemoryWriteGateway
  -> MemoryService
  -> MemoryRepository
```

允许的例外：

- 单元测试可直接构造 `MemoryService` 或 `MemoryRepository`。
- 一次性迁移脚本可直接调用 repository，但必须记录迁移日志。
- `MemoryService._ensure_bootstrap_memories()` 可保留内部 bootstrap 写入，但写入内容必须固定、可重复、可覆盖。

**新增验收标准：**

- 搜索代码时，除 gateway、tests、migration/bootstrap 外，不应存在新增的 `MemoryService.save_memory()` 直接业务调用。
- `gateway.submit_patch()` 必须返回 accepted/rejected/needs_review 的结构化结果。
- rejected 必须包含机器可读 reason，不能只写日志。

#### P0-2：投影文件加单写者声明 + 补 project → workspace/memory/MEMORY.md

**文件：** `core/memory/memory_projection.py`（修改）

**改动 1：所有投影文件加生成声明**

在 `_write_atomic` 或每个 `_project_*` 方法中，文件顶部添加：

```markdown
<!-- Generated by Lobuddy MemoryService at 2026-05-03T14:30:00.
     SQLite memory_item is authoritative. DO NOT EDIT this file directly.
     Changes will be overwritten on next projection refresh. -->
```

**改动 2：`_project_project_memory()` 同步写 `workspace/memory/MEMORY.md`**

```python
def _project_project_memory(self, items: list[MemoryItem]) -> None:
    # 1. 写 data/memory/PROJECT.md（现有逻辑，不改）
    self._write_atomic(self.memory_dir / "PROJECT.md", ...)

    # 2. 同步写 workspace/memory/MEMORY.md（新增）
    workspace_memory = self.workspace_path / "memory"
    workspace_memory.mkdir(parents=True, exist_ok=True)
    self._write_atomic(workspace_memory / "MEMORY.md", ...)
```

**改动 3：`_project_to_workspace()` 增加 MEMORY.md 投影**

```python
def _project_to_workspace(self, items: list[MemoryItem]) -> None:
    # 现有：USER.md, SOUL.md
    ...
    # 新增：memory/MEMORY.md
    project_items = [i for i in items
                     if i.memory_type == MemoryType.PROJECT_MEMORY
                     and i.status.value == "active"]
    if project_items:
        ...
        self._write_atomic(
            self.workspace_path / "memory" / "MEMORY.md",
            content + "\n",
        )
```

#### P0-3：禁用 Lobuddy 模式下 nanobot Dream 的所有触发路径

**策略：** 不修改 nanobot 源码（保持子模块干净），而是在 Lobuddy adapter 层面多层拦截。

**第一步：调查 Dream 触发路径（Phase 1 前置任务）**

在实施拦截前，需确认 Dream 在 Lobuddy 配置下的所有可能触发方式：

```python
# 需检查的触发路径：
# 1. 用户聊天中 /dream、/dream-log、/dream-restore 命令（nanobot 内置 slash command）
# 2. Heartbeat/Cron 周期性唤醒（nanobot gateway heartbeat）
# 3. 程序化调用 bot.memory_store.dream()
# 4. nanobot 内置 tool 调用（如 exec /dream）
```

**验证方法：** 在 `build_nanobot_config()` 中检查 nanobot 是否支持 `dream.enabled: false` 配置项；在 `config_builder.py` 中设置该项。

**文件：** `core/agent/nanobot_adapter.py`（修改）+ `core/agent/config_builder.py`（修改）

**方案 A（推荐）：** 多层拦截

**A1：Adapter 入口拦截 slash command（必须做）**

`_ToolTracker.before_execute_tools()` 只能拦截 tool call，拦不住 nanobot command router。`/dream`、`/dream-log`、`/dream-restore` 是 slash command，会在 agent tool loop 前被处理。因此必须先在 `NanobotAdapter.run_task()` 使用原始用户输入拦截：

```python
DREAM_COMMANDS = ("/dream", "/dream-log", "/dream-restore")

def _preflight_lobuddy_memory_boundary(self, prompt: str) -> AgentResult | None:
    raw = prompt.strip().lower()
    if any(raw == cmd or raw.startswith(cmd + " ") for cmd in DREAM_COMMANDS):
        now = datetime.now()
        return AgentResult(
            success=False,
            raw_output="",
            summary=(
                "Lobuddy 已接管长期记忆管理，nanobot Dream 命令在 Lobuddy 模式下禁用。"
                "需要整理记忆时，请使用 Lobuddy 的记忆维护或审查入口。"
            ),
            error_message="Dream command disabled in Lobuddy mode",
            started_at=now,
            finished_at=now,
        )
    return None
```

调用位置必须在 `bot.run()` 之前，并且使用 `original_prompt`，不能使用已经拼接 `Lobuddy Memory Context` 后的 prompt。

**A2：Command router 层禁用（如果可访问则做）**

如果 `NanobotGateway` 能访问 `gateway._loop.commands`，优先 unregister 或 override dream 命令处理器：

```python
def disable_dream_commands(gateway: NanobotGateway) -> None:
    commands = getattr(gateway._loop, "commands", None)
    if commands is None:
        return
    # 具体实现按 nanobot CommandRouter API 调查后确定：
    # commands.unregister("/dream")
    # commands.unregister("/dream-log")
    # commands.unregister("/dream-restore")
```

这一步是防御层，不替代 A1。

**A3：Tool hook 拦截 exec 中的 dream 字符串（补充防线）**

```python
class _ToolTracker:
    async def before_execute_tools(self, context: Any) -> None:
        for tc in context.tool_calls:
            # 新增：拦截 dream 相关命令
            if tc.name == "exec" and isinstance(tc.arguments, dict):
                command = tc.arguments.get("command", "")
                if any(dream_cmd in command for dream_cmd in [
                    "/dream", "/dream-log", "/dream-restore"
                ]):
                    raise RuntimeError(
                        "Dream commands are disabled in Lobuddy mode. "
                        "Memory management is handled by Lobuddy MemoryService."
                    )
            ...
```

**方案 B（补充）：** 在 `build_nanobot_config()` 中配置禁用 Dream

如果 nanobot 支持配置禁用 Dream，在 config builder 中设置。若 nanobot 不支持该配置项，方案 A + C 组合即可全覆盖。

**方案 C（补充）：** 在 Lobuddy AGENTS.md / system prompt 注入中明确告知 agent

**额外：** 在 `AGENTS.md` 或 system prompt 注入中明确告知 agent：

```
## Memory Management Policy
Lobuddy manages all long-term memory through its SQLite-based MemoryService.
You MUST NOT use /dream, /dream-log, /dream-restore commands.
You MUST NOT edit workspace/USER.md, workspace/SOUL.md, or workspace/memory/MEMORY.md directly.
When you want to remember something, use the memory_patch tool instead.
```

**新增验收标准：**

- 用户直接输入 `/dream`、`/dream-log`、`/dream-restore` 时，返回 Lobuddy 禁用说明，不进入 nanobot command router。
- 包含 `exec` 的工具调用尝试执行 dream 相关命令时，被 `_ToolTracker` 拦截。
- 如果 nanobot 后续新增 Dream 触发 API，默认视为不可信入口，必须接入 `MemoryWriteGateway` 后才能启用。

#### P0-4：Hot Memory Bundle + Frozen Snapshot

**文件：** `core/memory/memory_selector.py`（修改）

**改动：**

1. 先扩展 `PromptContextBundle` schema，再在 `select_for_prompt()` 中区分 hot 和 cold：

```python
class PromptContextBundle(BaseModel):
    user_profile: str = ""
    system_profile: str = ""
    project_context: str = ""      # 新增：hot project memory
    session_summary: str = ""
    retrieved_memories: str = ""   # cold recall / query-relevant memories
    active_skills: str = ""
    total_chars: int = 0
```

如果不扩展 schema，直接在 selector 中返回 `project_context` 会被 Pydantic 拒绝或丢弃，导致 hot project memory 设计落空。

```python
HOT_BUDGETS = {
    "user_profile": 500,    # tokens
    "system_profile": 300,
    "project_context": 800,
}

def select_for_prompt(self, user_message: str, session_id: str = "") -> PromptContextBundle:
    # Step 1: Hot memory（始终注入，硬预算）
    hot_user = self._select_hot(MemoryType.USER_PROFILE, HOT_BUDGETS["user_profile"])
    hot_system = self._select_hot(MemoryType.SYSTEM_PROFILE, HOT_BUDGETS["system_profile"])
    hot_project = self._select_hot_project(HOT_BUDGETS["project_context"])

    # Step 2: Cold memory（按需检索，填充剩余预算）
    remaining = max_budget - (len(hot_user) + len(hot_system) + len(hot_project))
    cold = self._select_cold(user_message, remaining)

    # Step 3: 组装 frozen bundle
    return PromptContextBundle(
        user_profile=hot_user,
        system_profile=hot_system,
        project_context=hot_project,
        retrieved_memories=cold,
        ...
    )
```

2. 在 `NanobotAdapter.run_task()` 开始时调用一次 `select_for_prompt()`，生成 frozen bundle，整个任务执行期间不重新计算。

---

### 2.4 P1 详细方案：补齐关键能力

#### P1-1：创建 session_search 冷 recall 工具

**文件：**

- `core/memory/session_search.py`（新增）：纯搜索服务，不依赖 nanobot。
- `core/agent/tools/session_search_tool.py`（新增）：nanobot `Tool` wrapper，负责 schema、参数校验、结果裁剪和脱敏。

**功能：** 给 nanobot 提供一个工具，使其能在执行时搜索 Lobuddy 的聊天历史。

```python
from nanobot.agent.tools.base import Tool

class SessionSearchTool(Tool):
    """Cold recall via Lobuddy ChatRepository FTS search."""

    def __init__(self, search_service: "SessionSearchService"):
        self._search = search_service

    async def search(self, query: str, session_id: str | None = None, limit: int = 5) -> list[dict]:
        """
        搜索聊天历史。
        - FTS5 优先（需先在 chat_message 表建 FTS5 索引）
        - LIKE fallback
        - 返回摘要（每条结果最多 300 chars）
        - 不返回完整原始消息（防止上下文爆炸）
        """
        ...
```

**协议要求：**

`SessionSearchTool` 必须实现 nanobot `Tool` 协议，包括：

- `name`
- `description`
- `parameters` / schema
- `execute()`
- 参数校验和类型转换

不能只提供普通 `search()` 方法后直接 `gateway.register_tool(search_tool)`，否则 tool registry 无法生成稳定 schema，模型也无法可靠调用。

**接入：** 作为自定义 tool 注册到 nanobot：

```python
# 在 NanobotAdapter.run_task() 中
from core.memory.session_search import SessionSearchTool
search_tool = SessionSearchTool(chat_repo)
gateway.register_tool(search_tool)  # agent 可见 session_search(tool)
```

**前置条件：** 在 `chat_message` 表上建 FTS5 索引：

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS chat_message_fts
USING fts5(content, content='chat_message', content_rowid='rowid');
```

**隐私边界（必须做）：**

`session_search` 会把本地聊天历史片段放入 tool result，随后进入 LLM 上下文。对用户来说，这等价于把相关历史片段发送给当前 LLM provider。因此必须具备以下边界：

- 新增设置项：`memory_session_search_enabled`，默认建议为 `False`，或首次使用时在 UI 中明确说明。
- 默认只搜索当前 session；跨 session 搜索需要额外参数和设置项允许。
- 每条结果最多返回固定长度摘要，例如 300 chars。
- 总返回字符数必须受预算限制，例如 1500 chars。
- 结果必须经过 secret/prompt-injection/control-character 脱敏。
- 工具结果必须标注来源：session_id、message_id、created_at，但不要默认返回完整原文。
- 不允许返回 image_path 等本地文件路径，除非用户明确启用调试模式。

**新增验收标准：**

- 关闭 `memory_session_search_enabled` 时，工具不注册。
- 开启后，默认搜索范围为当前 session。
- 搜索结果不会包含 API key、Bearer token、邮箱等敏感模式。
- 单次 tool result 不超过配置的总字符预算。

#### P1-2：补齐 skill 边界

**文件：** `core/skills/skill_manager.py`（修改）

**改动 1：`disable_skill()` 同步移除文件**

```python
def disable_skill(self, skill_id: str) -> bool:
    record = self.get_skill(skill_id)
    if not record:
        return False
    # 新增：移除 workspace skill 文件
    skill_file = Path(record.path)
    if skill_file.exists():
        skill_file.unlink()
    # 清理空目录
    parent = skill_file.parent
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()
    # 更新状态
    ok = self._update_status(skill_id, SkillStatus.DISABLED)
    if ok:
        self._log_event(skill_id, "disable", "Skill disabled, file removed")
    return ok
```

**改动 2：`archive_skill()` 同步移除文件（已有 copy，补 remove）**

```python
def archive_skill(self, skill_id: str) -> bool:
    record = self.get_skill(skill_id)
    if not record:
        return False
    src = Path(record.path)
    if src.exists():
        dst = self._archive_dir / f"{record.name}_v{record.version}.md"
        shutil.copy2(src, dst)
        src.unlink()  # 新增：移除原文件
        parent = src.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    self._update_status(skill_id, SkillStatus.ARCHIVED)
    self._log_event(skill_id, "archive", f"Archived to {self._archive_dir}")
    return True
```

**改动 3：`delete_skill()` 保持不变（已有 unlink）**

#### P1-3：app 初始化注入 SkillManager

**文件：** `app/main.py`（修改）

**改动：**

```python
# 在 Application 初始化中
from core.skills.skill_manager import SkillManager
from core.skills.skill_maintenance import SkillMaintenance  # 假设存在

self.skill_manager = SkillManager(settings)
self.skill_maintenance = SkillMaintenance(settings, manager=self.skill_manager)
self.skill_registry = SkillRegistry(manager=self.skill_manager)

# 传给 adapter（如果 adapter 需要做 skill candidate 提取）
self.adapter.set_skill_manager(self.skill_manager)
```

---

### 2.5 P2 详细方案：体检 + 可视化

#### P2-1：创建 MemoryLintService

**文件：** `core/memory/memory_lint.py`（新增）

```python
class MemoryLintService:
    """周期性记忆体检"""

    def __init__(self, repo: MemoryRepository):
        self._repo = repo

    def run_all_checks(self) -> list["LintFinding"]:
        findings = []
        findings.extend(self._check_duplicates())
        findings.extend(self._check_identity_conflicts())
        findings.extend(self._check_stale_facts())
        findings.extend(self._check_low_confidence_lingering())
        findings.extend(self._check_orphan_items())
        findings.extend(self._check_skill_memory_overlap())
        return findings

    def _check_duplicates(self) -> list["LintFinding"]:
        """检测同一 memory_type 中 content 相似度 >80% 的条目"""
        ...

    def _check_identity_conflicts(self) -> list["LintFinding"]:
        """检测 user_profile 中多个不同的 name 同时 active"""
        ...

    def _check_stale_facts(self) -> list["LintFinding"]:
        """检测超过 N 天未更新且 importance < threshold 的条目"""
        ...

    def _check_low_confidence_lingering(self) -> list["LintFinding"]:
        """检测 confidence < 0.6 但已存留超过 M 天的 active 条目"""
        ...

    def _check_orphan_items(self) -> list["LintFinding"]:
        """检测无 source_session_id 且 source 不是 bootstrap/manual 的条目"""
        ...

    def _check_skill_memory_overlap(self) -> list["LintFinding"]:
        """检测 skill 描述和 procedural_memory 内容高度重叠"""
        ...

class LintFinding(BaseModel):
    severity: str  # "error" | "warning" | "info"
    category: str
    item_ids: list[str]
    description: str
    suggestion: str
```

**调度：** 在 `MemoryMaintenance` 中加入 lint 检查调度（每次维护时运行）。

#### P2-2：Project Wiki Projection

**文件：** `core/memory/memory_projection.py`（修改）

在 `project_all()` 中加入 wiki 层生成：

```python
def project_all(self, items: list[MemoryItem]) -> None:
    # 现有投影逻辑
    self._project_user_profile(items)
    self._project_system_profile(items)
    self._project_project_memory(items)
    self._project_to_workspace(items)

    # 新增：Project Wiki 层
    self._project_wiki_index(items)
    self._project_wiki_log(items)

def _project_wiki_index(self, items: list[MemoryItem]) -> None:
    """生成 workspace/memory/index.md - 记忆索引"""
    lines = [
        "<!-- Generated by Lobuddy MemoryService. DO NOT EDIT. -->",
        "# Memory Index",
        "",
        f"Generated at {datetime.now().isoformat()}",
        f"Total active items: {len([i for i in items if i.status.value == 'active'])}",
        "",
        "## By Type",
    ]
    by_type: dict[str, list[MemoryItem]] = {}
    for item in items:
        if item.status.value == "active":
            by_type.setdefault(item.memory_type.value, []).append(item)
    for mt, items_list in sorted(by_type.items()):
        lines.append(f"\n### {mt} ({len(items_list)} items)")
        for item in items_list:
            lines.append(f"- [{item.title}] {item.content[:80]}... (confidence: {item.confidence:.2f})")
    self._write_atomic(self.workspace_path / "memory" / "index.md", "\n".join(lines))

def _project_wiki_log(self, items: list[MemoryItem]) -> None:
    """追加每次 projection 刷新到 workspace/memory/log.md"""
    # 如果文件不存在则创建
    # 否则追加时间戳 + 统计
```

#### P2-3：强化 provenance

**文件：** `core/memory/memory_write_gateway.py`（新增）

在 `submit_patch()` 中自动填充：

```python
def _enrich_provenance(self, item: MemoryPatchItem, context: WriteContext) -> MemoryPatchItem:
    """自动补充来源信息"""
    # 这些字段在 MemoryItem 中，但 MemoryPatchItem 没有
    # 需要在 apply_patch 时传递 context
    ...
```

**同步修改：** `MemoryService.apply_patch()` 接受 `WriteContext` 参数并填充到创建的 `MemoryItem` 上。

**字段映射：**

| WriteContext 字段 | MemoryItem 字段 |
|---|---|
| `context.source` | `source` |
| `context.session_id` | `source_session_id` |
| `context.task_id` | `source_task_id`（需新增 schema 字段） |
| `context.message_id` | `source_message_id` |

---

### 2.6 P3 详细方案：技能与程序记忆统一

#### P3-1：procedural memory + skill 边界定义

**定义文件：** `plan_/design_plan/5.3/memory_skill_boundary.md`（新建设计文档）

**核心规则：**

| 类别 | procedural_memory | SkillRecord |
|------|-------------------|-------------|
| 内容 | "这个项目中我们偏好用 pytest + monkeypatch" | 完整的 SKILL.md 步骤，含工具序列 |
| 粒度 | 偏好/经验，1-2 句 | 可重复执行的操作手册 |
| 注入方式 | hot context 或 budget-based | skill summary → system prompt |
| 生命周期 | active → deprecated | draft → active → needs_review → disabled → archived |
| 评价指标 | confidence, importance | success_count, failure_count, failure_rate |
| 写入触发 | 对话中自然表达偏好 | 复杂任务完成后自动提取候选 |

#### P3-2：Skill 学习管线

**管线流程：**

```
TaskManager 任务完成
  │
  ├── 判断条件：tools_used ≥ 3 且结果 success
  │
  ├── SkillCandidateExtractor.extract(task_result, tools_used, session_context)
  │     └── 生成 SkillCandidate（proposed_name, rationale, proposed_content）
  │
  ├── SkillValidator.validate(candidate)
  │     ├── 安全检查（prompt injection, secret, 命令白名单）
  │     ├── 格式检查（有效 SKILL.md 结构）
  │     └── 重复检查（与现有 skill 相似度）
  │
  ├── SkillManager.create_candidate(candidate)
  │     └── 写入 skill_candidate 表，status=pending
  │
  └── 默认进入 pending review
        ├── 用户审批后：SkillManager.approve_candidate(candidate_id)
        │     ├── 创建 SkillRecord（status=active）
        │     ├── 写入 workspace/skills/<name>/SKILL.md
        │     └── 记录 event
        └── 可选自动 approve：仅在显式开启且通过更严格安全阈值时执行
```

**边界修正：**

自动 skill 学习默认不能直接激活。skill 是 agent 行为扩展，不是普通记忆条目；错误 skill 会持续影响后续任务。默认策略：

- `skill_candidate_auto_approve_enabled = False`
- 高置信度只影响 review 排序，不直接激活
- 自动 approve 需要同时满足：
  - 用户显式开启
  - validator 无警告
  - 不包含 shell/网络/文件删除等高风险步骤
  - proposed skill 不覆盖 builtin skill 或已有 active skill
  - proposed content 不含任何会诱导 agent 绕过 Lobuddy 记忆边界的指令

**新增验收标准：**

- 默认配置下，复杂任务完成后最多产生 `skill_candidate(status=pending)`，不会直接写入 `workspace/skills`。
- 用户审批后才创建 active `SkillRecord` 和 `SKILL.md`。
- disabled/archive/delete 后，workspace skill 文件必须被移除或移动，nanobot 不再列出。

---

## 第三部分：可观测性

### 3.1 记忆仪表盘（Memory Dashboard）

**目标：** 让用户能看到 "现在系统记住了什么"

**实现方案：** 扩展 `PromptContextBundle`，在每次任务完成后返回 summary：

```python
class MemoryContextSummary(BaseModel):
    """任务记忆上下文摘要（用于 UI 展示）"""
    hot_user_profile: str  # "用户名叫 Zhixiang，偏好简洁回复"
    hot_system_profile: str  # "宠物名 Lobuddy，角色 AI 桌面助手"
    hot_project_context: str  # "当前在 Lobuddy 项目..."
    cold_memories_used: int  # 本次任务使用了 N 条冷记忆
    memory_updates_applied: int  # 本次任务产生了 N 条记忆更新
```

### 3.2 写入审计日志

每次 `MemoryWriteGateway.submit_patch()` 写入 → 产生结构化日志：

```json
{
  "timestamp": "2026-05-03T14:30:00",
  "action": "apply_patch",
  "context": {
    "source": "ai_patch",
    "session_id": "ses_abc123",
    "task_id": "task_xyz"
  },
  "result": {
    "accepted": 3,
    "rejected": 1,
    "needs_review": 0
  },
  "details": [
    {"id": "mem_001", "action": "add", "type": "project_memory", "content": "..."},
    {"id": "mem_002", "action": "update", "type": "user_profile", "content": "..."},
    {"rejected": {"content": "...", "reason": "prompt_injection_detected"}}
  ]
}
```

### 3.3 Lint 体检报告

`MemoryLintService.run_all_checks()` 返回结构化 findings 列表，可在 UI 中以卡片形式展示。
定期（每次应用启动、每天一次）运行并输出到日志。

---

## 第四部分：执行路线图

### Phase 1（止血，1-2 天）

```
□ P0-1a: MemoryWriteGateway 骨架 + 禁止新增绕过 gateway 的业务写入
□ P0-2: 投影文件加 generated header + 补 MEMORY.md 投影
□ P0-3: 禁用 Dream 直接写文件（拦截 /dream* 命令）
□ P1-2: disable/archive skill 同步移除文件
□ P1-3: app 初始化注入 SkillManager
```

**验证标准：**
- `workspace/USER.md`, `SOUL.md` 头部有 `<!-- Generated by Lobuddy... -->`
- `workspace/memory/MEMORY.md` 包含 project memory 内容
- agent 执行期间 `/dream` 命令被拦截
- disabled skill 的 `workspace/skills/<name>/SKILL.md` 不存在
- 新增业务写入入口不得直接调用 `MemoryService.save_memory()`，必须走 gateway

### Phase 2（统一写入 + 冷 recall，2-3 天）

```
□ 前置：确认 chat_message 表 schema 支持 content_rowid='rowid' FTS5 模式
□ P0-1b: 将既有写入路径迁移到 MemoryWriteGateway
□ P0-4: Hot Memory Bundle + Frozen Snapshot
□ P1-1: 创建 session_search tool（含 FTS5 索引）
□ P2-3: provenance 补全
```

**验证标准：**
- `chat_message` 表使用标准 rowid（非 WITHOUT ROWID），FTS5 外部内容表创建成功
- 所有 memory 写入经过 gateway
- `run_task()` 开始时生成 frozen context，执行期间不变
- nanobot 能通过 `session_search` 搜索历史
- 所有新 memory 有 `source_session_id`

### Phase 3（体检 + Wiki，1-2 天）

```
□ P2-1: MemoryLintService
□ P2-2: Project Wiki Projection（index.md + log.md）
```

**验证标准：**
- `workspace/memory/index.md` 和 `log.md` 存在且内容正确
- lint 报告无严重问题

### Phase 4（Skill 学习管线，3-5 天）

```
□ P3-1: procedural_memory + skill 边界文档
□ P3-2: Skill 学习管线（candidate 提取 → 校验 → 审批 → 投影）
```

**验证标准：**
- 复杂任务完成后自动产生 `skill_candidate`
- 审批后 skill 正确投影到 `workspace/skills`
- 使用后 `success_count` / `failure_count` 正确更新

---

## 第五部分：文件变更清单

| 文件 | 操作 | 所属 Phase |
|------|------|-----------|
| `core/memory/memory_write_gateway.py` | 新建骨架 Phase 1，迁移写入路径 Phase 2 | Phase 1, 2 |
| `core/memory/memory_projection.py` | 修改 | Phase 1 |
| `core/memory/memory_selector.py` | 修改 | Phase 2 |
| `core/memory/memory_service.py` | 修改 | Phase 2 |
| `core/memory/memory_lint.py` | 新建 | Phase 3 |
| `core/memory/session_search.py` | 新建搜索服务 | Phase 2 |
| `core/agent/tools/session_search_tool.py` | 新建 nanobot Tool wrapper | Phase 2 |
| `core/agent/nanobot_adapter.py` | 修改 | Phase 1, 2 |
| `core/agent/config_builder.py` | 修改（如 nanobot 支持 dream.enabled=false，则写入配置） | Phase 1 |
| `core/skills/skill_manager.py` | 修改 | Phase 1 |
| `core/skills/skill_learning_pipeline.py` | 新建 | Phase 4 |
| `core/config/settings.py` | 修改（新增 session_search / skill auto approve / gateway 相关设置） | Phase 2, 4 |
| `app/config.py` | 修改（新增 env 映射） | Phase 2, 4 |
| `app/main.py` | 修改 | Phase 1 |
| `core/storage/chat_repo.py` | 修改（加 FTS5） | Phase 2 |
| `tests/test_memory_write_gateway.py` | 新建 | Phase 2 |
| `tests/test_session_search.py` | 新建 | Phase 2 |
| `tests/test_projection_boundaries.py` | 新建 | Phase 1 |
| `tests/test_skill_lifecycle_boundary.py` | 新建/补充 | Phase 1, 4 |

---

## 第六部分：数据迁移策略

### 6.1 现有记忆数据迁移

实施 P0-1（MemoryWriteGateway）和 P2-3（provenance）后，数据库中的现有 `memory_item` 行需要进行处理：

| 场景 | 现状 | 升级后处理 |
|------|------|-----------|
| `source_session_id` 为 NULL | 大部分旧数据未填充 | 保留 NULL，不强制回填；仅新写入通过 gateway 保证填充 |
| `source_task_id` 不存在 | schema 中无此字段 | Phase 2 新增字段，旧数据默认为 NULL，通过 `_ensure_column` 安全添加 |
| `source` 值为 "ai" | 旧默认值 | 保留；新写入的 source 为 gateway context 中的具体来源 |
| `workspace/memory/MEMORY.md` 不存在 | 旧 projection 不写 | Phase 1 首次 `project_all()` 时自动创建，从 SQLite 读取现有 active project_memory |
| `workspace/skills/` 中有 disabled skill 文件 | disable 未移除文件 | Phase 1 启动时执行一次性清理：遍历 SQLite disabled/archived 技能，删除对应 workspace 文件 |

### 6.2 投影文件平滑切换

**P0-2（补 MEMORY.md 投影）的兼容策略：**

1. **不删除旧路径：** `data/memory/PROJECT.md` 继续生成。`workspace/memory/MEMORY.md` 作为额外输出同时生成。
2. **首次生成时机：** `MemoryService.__init__()` 中的初始化流程已包含 `_refresh_projections()`，升级后首次启动即自动生成。
3. **内容一致性：** `PROJECT.md` 和 `MEMORY.md` 来源相同（均为 active `project_memory`），内容保证一致。

### 6.3 Skill 文件一次性清理

**P1-2（disable/archive 移除文件）的存量处理：**

在 `SkillManager.__init__()` 中增加一次性清理逻辑：

```python
def _cleanup_orphan_files(self) -> int:
    """Phase 1 migration: remove workspace skill files for disabled/archived skills."""
    cleaned = 0
    for skill in self.list_skills(limit=1000):
        if skill.status in (SkillStatus.DISABLED, SkillStatus.ARCHIVED):
            skill_file = Path(skill.path)
            if skill_file.exists():
                skill_file.unlink()
                cleaned += 1
            parent = skill_file.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
    return cleaned
```

---

## 第七部分：可观测性缺口说明

### 7.1 当前计划可观测性范围

| 层级 | 当前方案覆盖 | 缺口 |
|------|------------|------|
| 后端审计日志 | ✅ Section 3.2 — 结构化 JSON 写入审计 | — |
| 后端体检报告 | ✅ Section 3.3 — MemoryLintService 自动检测 | — |
| 后端上下文摘要 | ✅ Section 3.1 — MemoryContextSummary 程序化输出 | **仅后端可见，无 UI 展示** |
| 用户可见仪表盘 | ❌ 未规划 | 用户无法直观看到 "系统记住了什么" |
| 手动记忆管理 UI | ❌ 未规划 | 用户无法手动编辑/删除/审批记忆 |
| 实时冲突告警 | ❌ 未规划 | 写入冲突发生时用户不知情 |

### 7.2 延期到 Phase 5 的 UI 层可观测性

以下功能依赖前端开发，建议在 Phase 4 完成后作为独立 UI 升级：

1. **设置面板 → 记忆 Tab：** 展示 active memory items 列表（按类型分组），支持查看详情、手动废弃
2. **"清理我的记忆" 按钮：** 一键将所有 user_profile 记忆标记为 needs_review，让用户选择性恢复
3. **记忆审批队列：** 展示 needs_review 状态的记忆，支持批量接受/拒绝
4. **Skill 状态面板：** 展示所有 skill 的状态、成功率、最后使用时间

这些功能的实现依赖当前 Phase 1-4 打下的后端基础（统一 gateway、分类 lint、wiki projection），可以在后端完成后作为纯 UI 增量开发。

---

## 第八部分：风险与注意事项

1. **nanobot 子模块修改风险：** 所有 nanobot 侧修改通过 adapter 层拦截实现，不直接修改 `lib/nanobot/`，保持子模块干净可更新。
2. **向后兼容：** `MemoryService.save_memory()` 保留现有接口，内部调用 gateway。旧代码无需立即迁移。
3. **FTS5 索引：** SQLite FTS5 可能在某些环境中不可用（如 Python 编译时未包含）。需保留 LIKE fallback。
4. **project_memory 文件路径兼容：** 同时写 `data/memory/PROJECT.md` 和 `workspace/memory/MEMORY.md`，不删除旧路径。
5. **测试覆盖：** 每个新增组件需配套单元测试（MemoryWriteGateway test, LintService test, session_search test）。
