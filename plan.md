# Lobuddy 开发计划（修订版 v2.0）

**生成时间**: 2026-04-24  
**上次重构**: `refactor/simplify-r1-r7` 分支（code-simplifier skill，17 个原子提交，净减 ~400 行）  
**测试状态**: 224 passed, 0 failed

---

## 项目概述

**Lobuddy** - AI 桌面宠物助手，基于 nanobot 打造的智能桌宠。

当前项目状态：**远超 plan.md v1.0 规划**，所有 8 个 Stage 的基础设施已实现，并包含大量计划外功能。当前处于 **Stage 8 打磨中**。

---

## 各 Stage 完成度（实际状态）

| Stage | 计划内容 | 实际状态 | 完成度 |
|-------|---------|---------|--------|
| **Stage 1** | 工程骨架与 nanobot 集成 | 全部完成 | 100% |
| **Stage 2** | 数据模型与持久化 | 全部完成（+ 聊天/个性扩展） | 100%+ |
| **Stage 3** | 桌宠基础 UI | 全部完成（+ GIF/系统托盘/快捷键） | 100%+ |
| **Stage 4** | 任务编排与执行流 | 全部完成（+ 历史压缩/子 Agent） | 100%+ |
| **Stage 5** | 成长系统 | 功能完成，成长逻辑已迁移到 `core/game/growth.py` | 85% |
| **Stage 6** | 事件总线与状态联动 | EventBus 实现但 UI 层仍主要用 Qt Signal | 60% |
| **Stage 7** | 设置系统 | 配置模型+Repo 完成，设置窗口 UI 基础实现 | 70% |
| **Stage 8** | 容错、日志、打磨 | 进行中（退出可靠性已修复，code-simplifier 重构完成） | 80% |

---

## 已实现功能清单

### 核心工程
- 应用入口 (`app/main.py`) — Qt + asyncio 双事件循环
- 启动引导 (`app/bootstrap.py`) — 配置加载、loguru 日志、健康检查
- 配置管理 (`app/config.py`) — Pydantic Settings，支持 .env
- 健康检查 (`app/health.py`) — CLI 依赖验证

### 数据模型与持久化
- `PetState` — 等级/经验/进化/心情/皮肤/个性
- `TaskRecord` / `TaskResult` — 任务全生命周期
- `ChatMessage` / `ChatSession` — 聊天历史
- `PetPersonality` — 五维个性系统
- SQLite 持久化 — pet/task/chat/settings/ability 仓库
- `BaseRepository` 抽象 — 消除 5 处重复初始化

### AI 适配器
- `NanobotAdapter` — 完整封装（配置/超时/工具追踪/历史压缩）
- `SubagentFactory` — 子 Agent 工厂
- **多模态图片分析** — 独立子进程 + Pillow 压缩 + 验证

### 任务系统
- `TaskManager` — 提交/队列/执行/结果/EXP 奖励
- `TaskQueue` — FIFO 串行异步队列
- Qt Signal 状态流转

### 成长系统（分散实现）
- 经验/等级 — `PetState.add_exp()`
- 三阶段进化
- 能力解锁系统 — 7 种能力
- 个性引擎 — 五维属性自动调整

### 事件总线
- `EventBus` — 轻量异步事件总线
- UI 层仍主要使用 Qt Signal

### UI 层
- `pet_window.py` — 无边框/拖拽/状态动画/EXP 进度条
- `task_panel.py` — 会话/输入/Markdown 渲染/图片附件
- `system_tray.py` — 托盘图标与菜单
- `hotkey_manager.py` — Ctrl+Shift+L
- `settings_window.py` — 设置窗口（基础实现）
- `asset_manager.py` — 资源管理

### 安全与质量
- Guardrails — 路径/命令/URL 校验
- API Key 加密存储
- 敏感数据日志过滤
- HTML 净化
- 历史压缩注入防护
- 224 测试覆盖所有主要模块

---

## 待办事项（按优先级）

### P0 — 必须修复（阻塞/安全/数据）

1. ✅ **失败任务不加经验** — `task_manager.py` 中 `_on_task_completed` 已检查 `result.success`
2. ✅ **SQLite 外键约束** — `db.py` 已启用 `PRAGMA foreign_keys = ON`
3. ✅ **异常静默吞掉** — 所有 `except: pass` 已加日志或重构
4. ✅ **TaskQueue 竞态条件** — 已添加 `asyncio.Lock` 并发保护
5. ✅ **超时后资源泄漏** — `nanobot_adapter` 超时后已清理底层任务

### P1 — 中优先级（架构/安全/功能）

6. ✅ **core -> app.config 循环依赖** — 已重构为依赖注入
7. ✅ **TaskManager/NanobotAdapter 上帝类** — 已拆分职责
8. ✅ **共享状态无锁保护** — token_meter, ability_system, task_manager 已加锁
9. ✅ **事务边界缺失** — 写操作已包事务
10. ✅ **路径校验封堵 UNC/ADS** — 已添加路径校验
11. ✅ **敏感信息日志脱敏** — 已脱敏处理
12. ✅ **图像处理 DoS 风险** — 已限制压缩循环
13. ✅ **AssetManager 资源管理缺陷** — 已修复
14. ✅ **任务状态机不完整** — 已添加状态转移校验

### P2 — 低优先级（打磨/优化）

15. ✅ **成长逻辑迁移到 core/game/** — `core/game/growth.py` 已创建，`PetState` 委托给 `GrowthEngine`
16. ✅ **能力解锁状态 SQLite 持久化** — 已实现
17. ✅ **任务难度自动判定** — `_determine_task_difficulty()` 基于输入长度和关键词自动判定
18. ✅ **设置窗口完善** — 所有信号已连接
19. ✅ **成长反馈 UI** — `PetWindow.show_exp_gained()` 浮动 +EXP 动画（QPropertyAnimation）
20. ❌ **EventBus 逐步替换 Qt Signal** — EventBus 存在但 `task_queue.py`/`task_manager.py`/UI 层仍主要用 Qt Signal
21. ✅ **首次引导流程** — `main.py` 首次运行显示欢迎对话框（含快速提示）
22. ✅ **代码风格统一** — 内联样式已重构，重复代码已提取

---

## 下一步行动（建议）

### Wave 1: 安全与架构（2-3 天）
1. API Key 临时文件权限加固
2. Guardrail 参数类型校验强化
3. 收紧 shell 命令策略（白名单替代黑名单）
4. 加强 URL/SSRF 防护
5. 统一错误处理策略
6. 补全测试覆盖盲区

### Wave 2: 功能完善（可选）
8. 设置窗口 UI 打磨（补充多模态/数据目录等配置项、样式优化）
11. EventBus 逐步替换 Qt Signal

---

## 文件统计

| 类别 | 文件数 | 主要文件 |
|------|--------|---------|
| 应用入口 | 4 | `app/main.py`, `bootstrap.py`, `config.py`, `health.py` |
| 数据模型 | 5 | `core/models/pet.py`, `chat.py`, `personality.py`, `appearance.py` |
| 持久化层 | 6 | `core/storage/db.py`, `base_repo.py`, `pet_repo.py`, `task_repo.py`, `chat_repo.py`, `settings_repo.py` |
| AI 适配器 | 7 | `core/agent/nanobot_adapter.py`, `config_builder.py`, `subagent_factory.py`, `image_validation.py`, `history_compressor.py`, `tools/analyze_image_tool.py` |
| 任务系统 | 2 | `core/tasks/task_manager.py`, `task_queue.py` |
| 事件总线 | 2 | `core/events/bus.py`, `events.py` |
| 扩展系统 | 2 | `core/abilities/ability_system.py`, `core/personality/personality_engine.py` |
| UI 层 | 6 | `ui/pet_window.py`, `task_panel.py`, `system_tray.py`, `hotkey_manager.py`, `settings_window.py`, `asset_manager.py` |
| 测试 | 20+ | 覆盖所有主要模块 |

---

*计划版本：v2.0*  
*最后更新：2026-04-24*  
*对应分支：refactor/simplify-r1-r7*
