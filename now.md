# Lobuddy 系统状态文档

**生成时间**: 2026-04-24  
**对应 plan.md 版本**: v2.0 (2026-04-24)

---

## 1. 整体状态概述

**当前阶段**: Stage 8 打磨中，但核心功能远超 plan.md 原始范围  
**可运行状态**: ✅ 可完整运行（python -m app.main）  
**健康检查**: ✅ 通过（配置/工作区/数据库/Pillow/Nanobot）  

> **关键发现**: 项目实际实现远超 plan.md 中 Stage 1-6 的规划，包含大量计划外功能（聊天历史、个性系统、能力系统、多模态图片分析）。settings_window.py 已实现，但 core/game/ 仍为空包，部分 P2 功能（成长反馈 UI、任务难度判定、首次引导）尚未实现。

---

## 2. 各 Stage 完成度对照

| Stage | 计划内容 | 实际状态 | 完成度 |
|-------|---------|---------|--------|
| **Stage 1** | 工程骨架与 nanobot 集成 | ✅ 全部完成 | 100% |
| **Stage 2** | 数据模型与持久化 | ✅ 全部完成（+聊天/个性扩展） | 100%+ |
| **Stage 3** | 桌宠基础 UI | ✅ 全部完成（+GIF支持/系统托盘/快捷键） | 100%+ |
| **Stage 4** | 任务编排与执行流 | ✅ 全部完成（+历史压缩） | 100%+ |
| **Stage 5** | 成长系统 | ⚠️ 功能完成但分散在 models/，core/game/ 为空包 | 80% |
| **Stage 6** | 事件总线与状态联动 | ⚠️ EventBus 实现但 UI 层仍主要用 Qt Signal | 60% |
| **Stage 7** | 设置系统 | ✅ 配置模型+Repo+设置窗口 UI 基础实现完成 | 70% |
| **Stage 8** | 容错、日志、打磨 | 🔄 进行中（退出可靠性已修复，code-simplifier 重构完成） | 80% |

---

## 3. 已实现功能清单

### 3.1 基础工程 (app/)
- ✅ 应用入口 `app/main.py` — Qt + asyncio 双事件循环，完整 UI 启动
- ✅ 启动引导 `app/bootstrap.py` — 配置加载、loguru 日志、健康检查
- ✅ 配置管理 `app/config.py` — Pydantic Settings，支持 .env，含 LLM/多模态/历史压缩配置
- ✅ 健康检查 `app/health.py` — CLI 依赖验证

### 3.2 数据模型 (core/models/)
- ✅ `PetState` — 等级(1-10)、经验、进化阶段(1-3)、心情、皮肤、个性
- ✅ `TaskRecord` / `TaskResult` — 任务全生命周期模型
- ✅ `ChatMessage` / `ChatSession` — 聊天历史（计划外）
- ✅ `PetPersonality` — 五维个性系统（友好/好奇/技术/创造/勤奋，计划外）
- ✅ 枚举定义 — TaskStatus, TaskDifficulty, EvolutionStage

### 3.3 持久化层 (core/storage/)
- ✅ `db.py` — SQLite 单例，含 pet_state / task_record / task_result / app_settings 表
- ✅ `pet_repo.py` — 宠物 CRUD，自动创建默认宠物，支持个性 JSON 序列化
- ✅ `task_repo.py` — 任务与结果持久化，支持最近/待处理查询
- ✅ `chat_repo.py` — 会话与消息持久化（计划外）
- ✅ `settings_repo.py` — 应用设置键值存储

### 3.4 AI 适配器 (core/agent/)
- ✅ `nanobot_adapter.py` — 完整的 Nanobot 封装，支持：
  - 动态临时配置生成
  - 超时控制
  - 工具使用追踪
  - 聊天历史自动压缩（超阈值时）
- ✅ `config_builder.py` — Nanobot 配置构建器
- ✅ `subagent_factory.py` — 子 Agent 工厂
- ✅ **多模态图片分析**（计划外重大功能）:
  - `tools/analyze_image_tool.py` — 独立子进程图片分析工具
  - `image_validation.py` — 图片验证
  - 超大图片自动 Pillow 压缩（>5MB）
  - 支持独立多模态模型配置

### 3.5 任务系统 (core/tasks/)
- ✅ `task_manager.py` — 完整任务编排：
  - 任务提交 → 队列 → 执行 → 结果保存
  - EXP 奖励发放
  - 个性进化触发
  - 能力解锁检查
- ✅ `task_queue.py` — FIFO 串行异步队列，支持取消/停止
- ✅ Qt Signal 驱动的状态流转（task_started / task_completed / pet_exp_gained / pet_level_up / ability_unlocked）

### 3.6 成长系统（分散实现）
- ✅ 经验/等级 — `PetState.add_exp()`，完整 1-10 级 EXP 阈值表
- ✅ 三阶段进化 — `get_evolution_stage_for_level()`
- ✅ **能力解锁系统**（计划外）— `core/abilities/ability_system.py`:
  - 7 种内置能力（Advanced Chat / Multi-Tasking / Code Assist / Creative Mode / Social Butterfly / 进化形态×2）
  - 基于等级/阶段/个性/任务数的解锁条件
- ✅ **个性引擎**（计划外）— `core/personality/personality_engine.py`:
  - 关键词分析任务内容
  - 自动调整五维个性属性

### 3.7 事件总线 (core/events/)
- ✅ `bus.py` — 轻量异步事件总线（subscribe/publish/publish_and_wait）
- ⚠️ 当前 UI 层主要直接使用 Qt Signal，EventBus 未完全取代 Signal/Slot

### 3.8 UI 层 (ui/)
- ✅ `pet_window.py` — 无边框置顶窗口，支持：
  - 鼠标拖拽移动
  - 左键点击打开任务面板
  - 右键设置菜单（信号已连接）
  - 状态切换动画（idle/running/success/error，支持 GIF）
  - EXP 进度条显示
- ✅ `settings_window.py` — 设置窗口（144行，基础实现）：
  - 表单展示当前配置（API Key / Base URL / Model / 宠物名称 / 超时）
  - 保存到 SQLite，同时导出到 .env
  - 从托盘 "Settings" 菜单可打开
- ✅ `task_panel.py` — 聊天/任务面板（522 行，最大 UI 文件）：
  - 会话历史侧边栏
  - 多行输入框 + 图片附件
  - Markdown 渲染助手回复
  - 消息气泡布局
- ✅ `system_tray.py` — 系统托盘图标与菜单（Show/Settings/About/Exit）
- ✅ `hotkey_manager.py` — 全局快捷键 `Ctrl+Shift+L`（pynput）
- ✅ `result_popup.py` — 自动关闭结果弹层（5秒）
- ✅ `asset_manager.py` — 资源查找、缓存、占位图生成
- ✅ UI 资源 — `ui/assets/` 含 idle/running/success/error PNG/GIF + 托盘图标

### 3.9 测试覆盖 (tests/)
- ✅ `test_nanobot_adapter.py` — 冒烟测试
- ✅ `test_pet.py` — 宠物模型测试
- ✅ `test_storage.py` — 存储层测试
- ✅ `test_event_bus.py` — 事件总线测试
- ✅ `test_task_manager_session.py` — 任务管理器测试
- ✅ `test_shutdown_regression.py` — 退出可靠性回归测试
- ✅ `test_exit_wiring.py` — 退出信号连接测试
- ✅ `test_image_analysis_integration.py` — 图片分析集成测试
- ✅ `test_analyze_image_tool.py` — 图片分析工具单元测试
- ✅ `test_image_validation.py` — 图片验证测试
- ✅ `test_subagent_factory.py` — 子 Agent 工厂测试
- ✅ `test_config_builder.py` — 配置构建器测试
- ✅ `test_ui_gif_support.py` — UI GIF 支持测试
- ✅ `test_bootstrap.py` — 启动引导测试

---

## 4. 待办事项 (TODO)

### 🔴 高优先级
1. **修复已知 Bug**（✅ 已全部修复）
   - ✅ `app/main.py:120` — `on_pet_level_up` 中 `pet` 变量已正确定义
   - ✅ `core/models/chat.py:28` — `ChatSession.messages` 已改为 `Field(default_factory=list)`
   - ✅ `core/storage/pet_repo.py` — `get_or_create_pet(pet_id)` 已正确使用传入的 `pet_id`
   - ✅ `core/tasks/task_manager.py` — 任务状态/时间戳已持久化回数据库

2. **基础设施状态**
   - `core/game/` — 当前仅 `__init__.py`，成长逻辑仍分散在 `models/pet.py`（P2 待办 #15）
   - `core/services/` — 当前仅 `__init__.py`
   - ✅ `ui/settings_window.py` — 已实现（144行，支持配置修改与保存）

3. **能力系统持久化**（✅ 已完成）
   - ✅ `ability_system.py` — 解锁状态已接入 SQLite（`tests/test_ability_persistence.py` 通过）

### 🟡 中优先级
4. **事件总线替换 Signal**
   - 当前 UI-核心层耦合依赖 Qt Signal（`task_manager.task_started.connect()` 等）
   - 计划要求通过 EventBus 解耦，降低 Qt 对核心层的侵入

5. **设置窗口实现**
   - 托盘菜单 "Settings" 信号已发出但无接收器
   - 需实现 `ui/settings_window.py` 表单界面
   - 需连接 LLM API Key / Base URL / Model / 宠物名称 / 超时等配置项的实时修改

6. **任务难度自动判定**
   - 当前 `submit_task` 固定设置 `TaskDifficulty.SIMPLE`，未根据输入内容判定难度

### 🟢 低优先级 / 打磨
7. **首次引导优化**
   - 首次运行自动创建默认宠物（Lv1, Stage 1）— ✅ 已有，但可添加欢迎对话框
   - 演示任务按钮（"帮我写一段 Python 代码"）— 未实现

8. **UI 完善**
   - `pet_window` 右键 `settings_requested` 信号未连接处理
   - `system_tray` 的 Settings / About 信号未连接处理
   - `close_requested` 信号未连接处理

9. **成长反馈 UI 增强**
   - plan.md 规划的 `ui/growth_feedback.py`（+EXP 浮动提示 / Level Up 升级动画 / Evolution 进化特效）— 未实现
   - 当前仅通过 EXP 进度条和 print 提示反馈

10. **日志完善**
    - 部分模块使用 stdlib `logging` 而非 `loguru`
    - 可考虑统一日志格式和级别

---

## 5. 已知问题与风险

| 问题 | 位置 | 风险等级 | 说明 |
|------|------|---------|------|
| ✅ 变量未定义 | `app/main.py:120` | ✅ 已修复 | `pet` 变量已正确定义 |
| ✅ 可变默认参数 | `core/models/chat.py:28` | ✅ 已修复 | 已改为 `Field(default_factory=list)` |
| ✅ 能力状态丢失 | `core/abilities/ability_system.py` | ✅ 已修复 | 解锁状态已接入 SQLite |
| ✅ 任务状态未持久化 | `core/tasks/task_manager.py` | ✅ 已修复 | 状态变更已持久化 |
| ✅ 宠物 ID 忽略 | `core/storage/pet_repo.py` | ✅ 已修复 | `create_default_pet` 已正确使用 `pet_id` |
| 依赖内部 API | `core/agent/nanobot_adapter.py` | 🟡 中 | 直接访问 `bot._loop.sessions` / `bot._loop.tools` 等内部属性，nanobot 升级可能破坏 |
| 难度固定 | `core/tasks/task_manager.py` | 🟢 低 | 所有任务固定为 SIMPLE 难度，EXP 奖励无差异（P2 待办 #17） |

---

## 6. 超出计划的功能（已交付）

以下功能未在 plan.md v1.0 中规划，但已实现：

1. **聊天历史系统** — 多会话管理、消息持久化、历史加载
2. **聊天历史自动压缩** — 超阈值后自动摘要旧对话
3. **个性进化系统** — 五维个性属性，基于任务内容自动调整
4. **能力解锁系统** — 7 种可解锁能力，基于等级/阶段/个性/任务数
5. **多模态图片分析** — 子 Agent 独立进程视觉分析，超大图自动压缩
6. **应用退出可靠性** — 托盘 Exit 彻底清理（asyncio 任务/队列/热键线程），超时保护

---

## 7. 文件统计

| 类别 | 文件数 | 主要文件 |
|------|--------|---------|
| 应用入口 | 4 | `app/main.py`, `app/bootstrap.py`, `app/config.py`, `app/health.py` |
| 数据模型 | 5 | `core/models/pet.py`, `chat.py`, `personality.py`, `appearance.py` |
| 持久化层 | 5 | `core/storage/db.py`, `pet_repo.py`, `task_repo.py`, `chat_repo.py`, `settings_repo.py` |
| AI 适配器 | 6 | `core/agent/nanobot_adapter.py`, `config_builder.py`, `subagent_factory.py`, `image_validation.py`, `tools/analyze_image_tool.py` |
| 任务系统 | 2 | `core/tasks/task_manager.py`, `task_queue.py` |
| 事件总线 | 2 | `core/events/bus.py`, `events.py` |
| 扩展系统 | 2 | `core/abilities/ability_system.py`, `core/personality/personality_engine.py` |
| UI 层 | 6 | `ui/pet_window.py`, `task_panel.py`, `system_tray.py`, `hotkey_manager.py`, `result_popup.py`, `asset_manager.py` |
| 测试 | 14+ | 覆盖所有主要模块 |

---

## 8. 下一步建议

### 已完成（近期）
✅ 1. 修复 `app/main.py` 的 `pet` 变量作用域 Bug
✅ 2. 修复 `ChatSession` 可变默认列表问题
✅ 3. 实现 `ui/settings_window.py`
✅ 4. 连接 tray/window 的 settings/about/close 信号
✅ 6. 实现能力解锁状态的 SQLite 持久化
✅ 8. 任务状态变更持久化（`repo.update_task()`）

### 待完成（中期）
5. 将成长逻辑从 `core/models/pet.py` 迁移到 `core/game/` 模块
7. 任务难度自动判定（基于输入长度/关键词）

### 长期（可选）
9. 用 EventBus 逐步替换跨层 Qt Signal
10. 实现 `ui/growth_feedback.py` 升级/进化动画
11. 添加演示任务按钮和首次引导流程

---

## 9. Lobuddy 与 nanobot 的架构差距（AI 应用开发视角）

### 9.1 nanobot 核心架构概览

nanobot 作为底层 Agent 框架，提供了以下核心组件：

| 组件 | 文件 | 功能 |
|------|------|------|
| **Nanobot Facade** | `nanobot/__init__.py` | 主入口 `from_config()` + `run()` |
| **AgentLoop** | `agent/loop.py` | 核心处理引擎（LLM ↔ 工具执行 ↔ 流式输出） |
| **AgentRunner** | `agent/runner.py` | 独立的工具使用 LLM 执行循环 |
| **SubagentManager** | `agent/subagent.py` | nanobot 内置子 Agent 管理（后台 asyncio Task） |
| **AgentHook** | `agent/hook.py` | 生命周期钩子系统（6 个钩子点） |
| **ToolRegistry** | `agent/tools/registry.py` | 工具注册与发现 |
| **SessionManager** | `session/manager.py` | 会话隔离与历史管理 |
| **MessageBus** | `bus/queue.py` | 消息路由总线 |
| **SkillsLoader** | `agent/skills.py` | 技能加载系统 |
| **Memory** | `agent/memory.py` | Dream/Consolidator 长期记忆 |
| **CronService** | `cron/service.py` | 定时任务调度 |
| **Providers** | `providers/` | 20+ LLM Provider 适配层 |

### 9.2 Lobuddy 未充分利用的 nanobot 能力

#### 🔴 严重差距：未使用 nanobot 内置子 Agent 系统

**nanobot 已有 `SubagentManager`**（`agent/subagent.py`，257 行）：
- `spawn(task, label, session_key)` — 在同进程内创建 asyncio Task 执行后台任务
- 自动构建受限工具集（无 message/spawn 工具，防止递归）
- 通过 `MessageBus.publish_inbound()` 将结果注入主 Agent 会话
- 支持按 session 批量取消 `cancel_by_session()`
- 运行计数 `get_running_count()`

**Lobuddy 的做法**：完全绕过 nanobot 的 `SubagentManager`，自己实现了 `SubagentFactory`：
- 使用 `multiprocessing.Process` 创建独立进程
- 进程中全新初始化 `Nanobot.from_config()`
- 通过文件系统（`result.json`）传递结果
- 自行管理进程生命周期（启动/轮询/超时/强制终止）

**差距分析**：
- Lobuddy 的子 Agent **过重**：每次创建独立进程 + 全新 Nanobot 实例 + 临时工作区，启动开销大
- nanobot 的 `SubagentManager` **更轻量**：同进程 asyncio Task，共享 Provider，秒级启动
- Lobuddy **丢失了 MessageBus 集成**：子 Agent 结果无法自动注入主会话上下文
- 但 Lobuddy 的方式**隔离性更强**：适合图片分析这类可能阻塞/崩溃的任务

**建议**：
- 简单后台任务 → 使用 nanobot 内置 `SubagentManager`（轻量、自动集成）
- 高风险/阻塞任务（如图片分析）→ 保留 Lobuddy 的多进程方案
- 两者可以共存，按任务类型选择

#### 🟡 中度差距：AgentHook 系统未充分利用

**nanobot 提供 6 个生命周期钩子**（`agent/hook.py`）：
```python
class AgentHook:
    def wants_streaming(self) -> bool          # 是否启用流式
    async def before_iteration(self, ctx)      # 每次 LLM 调用前
    async def on_stream(self, ctx, delta)      # 流式输出增量
    async def on_stream_end(self, ctx, *, resuming)  # 流式结束
    async def before_execute_tools(self, ctx)  # 工具执行前
    async def after_iteration(self, ctx)       # 每次迭代后
    def finalize_content(self, ctx, content)   # 最终内容加工
```

**Lobuddy 当前仅实现了简陋的 `_ToolTracker`**：
- 只使用了 `before_execute_tools` 来记录工具名
- 没有使用流式钩子（`wants_streaming`, `on_stream`, `on_stream_end`）
- 没有使用迭代级钩子（`before_iteration`, `after_iteration`）
- 没有使用内容加工钩子（`finalize_content`）

**差距影响**：
- ❌ 无法实现实时打字机效果（缺少 `on_stream`）
- ❌ 无法在工具调用前做权限检查/日志记录（`before_execute_tools` 可扩展）
- ❌ 无法在每次 LLM 迭代后做 token 统计/成本计算
- ❌ 无法对最终输出做后处理（如过滤敏感词、格式化）

#### 🟡 中度差距：未使用 nanobot 流式输出

**nanobot 支持完整流式输出**（`AgentLoop` 中 `_LoopHook.on_stream`）：
- `bot.run("...", on_stream=callback)` — 实时接收增量文本
- 自动处理 think 标签剥离
- 支持 delta coalescing（边界合并）

**Lobuddy 当前做法**：
- 等待 `bot.run()` 完全结束后才拿到完整 `result.content`
- 用户提交任务后，桌宠进入 `RUNNING` 状态，但没有任何进度反馈
- 任务完成时一次性显示结果

**差距影响**：
- 用户等待期间完全盲等，不知道 Agent 在做什么
- 长时间任务（如代码生成、多步分析）体验差
- 无法显示"正在搜索..."/"正在读取文件..."等中间状态

#### 🟡 中度差距：未使用 nanobot 内置工具集

**nanobot 内置丰富工具**（`agent/tools/`）：
- `filesystem` — read/write/edit/list/glob/grep（文件操作）
- `shell` — exec（命令执行，可配置超时/工作目录）
- `web` — search/fetch（网页搜索与抓取）
- `cron` — 定时任务管理
- `spawn` — 子 Agent 启动
- `message` — 消息发送

**Lobuddy 当前做法**：
- 仅注册了自定义的 `AnalyzeImageTool`
- 用户提交的任务**无法使用文件系统/命令行/网页搜索**等工具
- nanobot 的强大能力被严重限制

**差距影响**：
- 用户问"帮我查一下 Python 3.12 的新特性" → Agent 无法使用 web_search
- 用户说"帮我修改这个文件" → Agent 无法使用 filesystem 工具
- Lobuddy 退化成了一个简单的聊天机器人，而非真正的 Agent

#### 🟢 轻度差距：其他未使用的能力

| 能力 | nanobot 实现 | Lobuddy 状态 | 影响 |
|------|-------------|-------------|------|
| **Skills 系统** | `agent/skills.py` + `skills/` 目录 | ❌ 未使用 | 无法扩展 Agent 能力 |
| **长期记忆** | Dream + Consolidator | ❌ 未使用 | 每次对话从零开始 |
| **Cron 定时任务** | `cron/service.py` | ❌ 未使用 | 无法实现定时提醒 |
| **Heartbeat 唤醒** | `heartbeat/` | ❌ 未使用 | 无法主动触发任务 |
| **Command Router** | `/new`, `/stop`, `/restart` 等 | ❌ 未使用 | 用户无法命令式控制 |
| **多 Provider 支持** | 20+ Provider | ⚠️ 部分使用 | 仅使用了 custom Provider |
| **MCP 协议** | `tools/mcp/` | ❌ 未使用 | 无法接入外部工具服务 |

### 9.3 Lobuddy 对 nanobot 内部 API 的依赖（脆弱性）

Lobuddy 多处直接访问 nanobot **私有/内部属性**，这些 API 随时可能因 nanobot 升级而变更：

| 位置 | 访问的内部 API | 风险 |
|------|--------------|------|
| `nanobot_adapter.py:147` | `bot._loop.sessions.get_or_create()` | 🔴 高 — SessionManager 内部方法 |
| `nanobot_adapter.py:163` | `bot._loop.tools.register()` / `unregister()` | 🔴 高 — ToolRegistry 内部方法 |
| `nanobot_adapter.py:84` | `bot._loop._process_message()` | 🔴 高 — 下划线私有方法 |
| `subagent_factory.py:70` | `bot._loop.sessions.get_or_create()` | 🔴 高 — 同上 |
| `subagent_factory.py:84` | `bot._loop._process_message()` | 🔴 高 — 同上 |
| `nanobot_adapter.py:106` | `bot._loop` | 🟡 中 — 直接检查内部循环 |

**建议**：
- 尽可能使用 nanobot **公共 API**（`bot.run()`, `bot.from_config()`）
- 对必须使用的内部 API，添加版本兼容性检查
- 考虑向 nanobot 提交 PR，将需要的功能暴露为公共 API

### 9.4 子 Agent 架构详解

#### Lobuddy 的子 Agent 实现（当前方案）

```
┌─────────────────────────────────────────────────────────────┐
│                    Lobuddy 主进程（Qt + asyncio）              │
│  ┌─────────────┐                                           │
│  │ TaskManager │──submit_task()──┐                          │
│  └─────────────┘                ▼                          │
│  ┌─────────────────────────────────────────┐               │
│  │     NanobotAdapter.run_task()           │               │
│  │  ┌─────────────────────────────────┐   │               │
│  │  │  Nanobot.from_config()          │   │               │
│  │  │  bot.run(prompt, hooks=[...])   │   │               │
│  │  │       │                         │   │               │
│  │  │       ▼                         │   │               │
│  │  │  LLM decides to call tool       │   │               │
│  │  │  "analyze_image"                │   │               │
│  │  └───────┬─────────────────────────┘   │               │
│  └──────────┼─────────────────────────────┘               │
│             ▼                                               │
│  ┌─────────────────────────────────────────┐               │
│  │   AnalyzeImageTool.execute()            │               │
│  │   └── validate_image_file()             │               │
│  │   └── 图片压缩（Pillow）                 │               │
│  │   └── SubagentFactory.run_image_analysis()              │
│  │       └── run_subagent("image_analysis")               │
│  │           └── asyncio 线程池中运行                       │
│  │               └── multiprocessing.Process              │
│  │                   └── _run_subagent_worker_process()   │
│  │                       └── 新进程内全新 Nanobot 实例      │
│  │                           └── bot._loop._process_message()
│  │                               └── 调用多模态模型         │
│  │                       └── 结果写入 result.json          │
│  │               └── 轮询 result.json 文件                  │
│  │           └── 返回图片分析结果                           │
│  └─────────────────────────────────────────┘               │
│             │                                               │
│             ▼                                               │
│  主 Nanobot 继续执行，拿到图片分析结果                        │
└─────────────────────────────────────────────────────────────┘
```

**关键设计决策**：
1. **多进程隔离**：子 Agent 在独立进程中运行，崩溃不影响主进程
2. **临时工作区**：每个子 Agent 有独立 `tempfile.mkdtemp()` 工作区
3. **文件系统通信**：主进程与子进程通过 `result.json` 文件交换结果
4. **超时控制**：`settings.task_timeout` 控制子 Agent 最大运行时间
5. **独立配置**：子 Agent 可使用与主 Agent 不同的模型/URL/Key（如多模态专用配置）

**当前限制**：
- 子 Agent 结果**无法自动注入主 Agent 的会话历史**（需要手动处理）
- 子 Agent 进程**无法流式返回结果**（只能等完全结束后拿到结果）
- 子 Agent **无法使用 nanobot 的 MessageBus**（独立进程隔离了消息总线）
- 每次创建子 Agent 都有**进程启动开销**（约 0.5-2 秒）

#### 理想的子 Agent 架构（建议演进方向）

```
方案 A：轻量子 Agent（使用 nanobot SubagentManager）
┌────────────────────────────────────────────┐
│              Lobuddy 主进程                  │
│  ┌────────────────────────────────────┐   │
│  │  NanobotAdapter                    │   │
│  │  └── bot.run(prompt)               │   │
│  │      └── AgentLoop                 │   │
│  │          └── SubagentManager.spawn()│  │
│  │              └── asyncio Task（同进程） │
│  │                  └── AgentRunner    │  │
│  │                      └── 受限工具集  │  │
│  │              └── 结果 → MessageBus  │  │
│  │          └── MessageBus 注入结果    │  │
│  │      └── 主 Agent 继续执行          │  │
│  └────────────────────────────────────┘   │
└────────────────────────────────────────────┘
适用：简单后台任务，需要快速启动和自动上下文集成

方案 B：重量级子 Agent（保留 Lobuddy 当前方案）
┌────────────────────────────────────────────┐
│              Lobuddy 主进程                  │
│  ┌────────────────────────────────────┐   │
│  │  SubagentFactory.run_subagent()    │   │
│  │  └── multiprocessing.Process       │   │
│  │      └── 独立 Nanobot 实例         │   │
│  │      └── 独立 Provider 连接        │   │
│  │  └── 结果返回（文件/管道）          │   │
│  └────────────────────────────────────┘   │
└────────────────────────────────────────────┘
适用：高风险任务（图片分析/代码执行），需要进程隔离

方案 C：混合架构（推荐）
┌────────────────────────────────────────────┐
│              Lobuddy 主进程                  │
│  ┌────────────────────────────────────┐   │
│  │  任务路由器                         │   │
│  │  ├── 低风险/快速任务               │   │
│  │  │   └── SubagentManager.spawn()   │   │
│  │  └── 高风险/阻塞任务               │   │
│  │      └── SubagentFactory（多进程） │   │
│  └────────────────────────────────────┘   │
└────────────────────────────────────────────┘
```

---

## 10. AI 应用开发层面的待办事项

### 🔴 高优先级（架构改进）

1. **启用 nanobot 内置工具集**
   - 在 `NanobotAdapter` 中不再限制工具注册，让用户的任务可以使用 filesystem/web search/shell 等工具
   - Lobuddy 才能真正发挥 Agent 能力，而非只是聊天机器人
   - 需要设计安全边界（如 `restrictToWorkspace`）

2. **接入流式输出**
   - 使用 nanobot 的 `on_stream` 钩子实现实时打字机效果
   - 在 `task_panel.py` 中逐步显示 Agent 的思考过程
   - 桌宠状态可以细化为"思考中"/"搜索中"/"读取文件中"等

3. **重构子 Agent 架构**
   - 简单任务使用 nanobot `SubagentManager`（轻量）
   - 图片分析保留多进程方案（隔离）
   - 统一结果返回机制，让子 Agent 结果能注入主会话

### 🟡 中优先级（能力扩展）

4. **使用 AgentHook 扩展能力**
   - `before_execute_tools` — 添加权限检查、成本统计
   - `on_stream` + `on_stream_end` — 实时显示进度
   - `after_iteration` — 每轮迭代后更新 token 消耗
   - `finalize_content` — 输出后处理（格式化、过滤）

5. **接入 Skills 系统**
   - 将 Lobuddy 的能力（如图片分析）封装为 nanobot Skill
   - 支持 Skill 热加载和版本管理

6. **使用长期记忆**
   - 接入 nanobot 的 Dream/Consolidator
   - 让 Agent 记住用户的偏好、常用任务模式

### 🟢 低优先级（可选）

7. **接入 MCP 协议**
   - 支持外部工具服务（如数据库查询、API 调用）

8. **多 Provider 切换**
   - 利用 nanobot 的 Provider 注册表实现模型动态切换
   - 不同任务自动选择最合适的模型（如代码任务用 Claude，简单聊天用 GPT-4o-mini）

9. **接入 Command Router**
   - 在聊天面板支持 `/new`、 `/stop`、 `/restart` 等命令

---

*本文档由代码审计自动生成，基于实际文件内容与 plan.md 对比分析。*
