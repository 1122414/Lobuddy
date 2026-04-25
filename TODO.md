# Lobuddy UI Redesign — 可行性分析与实施 TODO

> 基于现有代码库审计和 `ui-redesign-plan.md` 的重设计划。
> 本文件将计划中的 6 个 Phase 映射为可执行的增量任务，标注已有基础、风险点、依赖项。

---

## 审计摘要

### 现有代码已有基础（无需从零实现）

| 组件 | 现状 | 重设计划对应 |
|---|---|---|
| `PetWindow` | 180行，无边框、透明背景、可拖拽、支持GIF(QMovie)、有等级/EXP条、有浮动EXP动画、有状态切换(idle/running/success/error) | PetWidget (5.1) — 已有80% |
| `AssetManager` | 211行，懒加载+缓存，支持状态图片映射，自动回退，支持GIF/PNG | PetAssetLoader (5.5) — 已有70% |
| `PetAppearance` | 支持idle/running/success/error四状态图片配置+宽高 | PetConfig (9.1) — 需要扩展 |
| `TaskPanel` | 539行，聊天面板，带历史侧边栏、消息气泡、markdown渲染、图片发送/显示、会话管理 | ChatPanel (5.3) — 需要重构 |
| `styles.py` | 集中式QSS，当前绿/白主题 | cozy主题 (4.1) — 需要重写配色 |
| `settings_repo` | SQLite持久化，已有`get_json_setting`/`set_json_setting` | SettingsService (11) — 已有基础 |
| `pet_repo` | SQLite持久化宠物状态(等级/EXP/皮肤/性格) | 宠物状态持久化 — 已有 |
| `TaskStatus` | idle/created/queued/running/success/failed/cancelled | 任务状态枚举 (5.4) — 已覆盖 |
| `TaskResult` | 有task_id/success/raw_result/summary/error_message | 任务卡片数据 (9.2) — 需扩展 |
| `SystemTray` / `HotkeyManager` | 托盘、全局快捷键已完善 | 保留不变 |

### 关键差距与风险

| # | 差距 | 风险等级 | 说明 |
|---|---|---|---|
| 1 | **任务步骤数据不可见** | 🔴 高 | 当前 `TaskManager` 只暴露 `task_started` / `task_completed` 信号，没有中间工具调用步骤。要实现计划中的「✅启动浏览器 → ✅访问百度」卡片，需要修改 nanobot 适配层暴露中间步骤，或做文本解析。 |
| 2 | **设置持久化方式选择** | 🟡 中 | 计划建议 JSON 文件(`data/settings/ui_settings.json`)，但现有 `settings_repo` 用 SQLite 且已有 JSON 序列化方法。建议沿用 SQLite，避免引入第二套数据源。 |
| 3 | **TaskPanel 功能耦合** | 🟡 中 | `task_panel.py` 539 行，同时承担聊天、历史、图片发送。拆分为 ChatPanel + HistoryDrawer + TaskCardPanel 需要谨慎重构，避免破坏现有消息渲染和会话管理。 |
| 4 | **宠物自定义文件存储** | 🟡 中 | 需要新增 `data/user_assets/pets/` 目录结构、文件复制逻辑、文件大小校验。注意 Windows 路径处理。 |
| 5 | **宠物位置持久化** | 🟢 低 | `PetWindow` 已有 `move(x,y)`，只需在关闭/移动时保存到 settings_repo，启动时恢复。 |
| 6 | **宠物气泡对话** | 🟢 低 | 可在 `PetWindow` 中新增浮动 QLabel，用 QPropertyAnimation 做淡入淡出。 |

---

## 实施顺序与依赖图

```
Phase 1: UI Shell 分离 ─────┬───► Phase 2: 视觉主题
       │                     │
       ▼                     ▼
PetWidget重构(已有)      styles.py重写
QuickActionMenu(新建)    配色替换
ChatPanel拆分(重构)      圆角/阴影
HistoryDrawer(新建)

Phase 3: 任务卡片 ─────────► Phase 4: 宠物自定义
       │                          │
       ▼                          ▼
简单结果卡片(先做)           PetSettingsPanel
查看详情折叠               文件上传/验证/复制
EXP奖励显示                缩放/透明度/位置
                           持久化设置

Phase 5: 宠物交互增强 ─────► Phase 6: 历史抽屉
       │                          │
       ▼                          ▼
状态气泡文字               可折叠抽屉
右键菜单                   卡片式历史
位置保存                   删除按钮移入抽屉
always-on-top切换
```

> **依赖规则**: Phase N 中标记为 ⬇️ 的任务必须在 Phase N-1 完成后才能开始。

---

## 具体 TODO 清单

---

### 🔵 Phase 1: UI Shell 分离

**目标**: 将当前大窗口拆分为 PetWidget + ChatPanel + QuickActionMenu。Pet 成为默认可见表面。

#### 1.1 新建 `ui/quick_action_menu.py` — QuickActionMenu 组件
- [ ] 创建 `QuickActionMenu` 类（继承 `QWidget` 或 `QDialog`）
- [ ] 设计为围绕宠物的浮动按钮组（Chat / Task / Pet / Settings / Close）
- [ ] 使用小圆角图标按钮，无边框透明背景
- [ ] 点击宠物打开/关闭菜单（通过 `PetWindow.task_requested` 信号扩展）
- [ ] 点击外部区域自动关闭菜单
- [ ] 连接信号：Chat→打开 ChatPanel，Pet→打开 PetSettingsPanel，Settings→打开 AppSettingsPanel
- **验收**: 点击宠物出现/消失菜单；各按钮能触发对应信号

#### 1.2 重构 `ui/pet_window.py` — 扩展 PetWidget 功能
- [ ] 保留现有：无边框、透明、拖拽、GIF、EXP条、浮动动画
- [ ] 新增：宠物状态文字显示（idle/thinking/working/success/failed）
- [ ] 新增：点击宠物打开 `QuickActionMenu`（替代当前直接打开 TaskPanel）
- [ ] 保留：右键打开 Settings（`settings_requested` 信号）
- [ ] 新增：右键菜单（Open Chat / Pet Settings / Exit）
- [ ] 调整信号：`task_requested` 改为 `quick_menu_requested` 或新增信号
- **验收**: 默认只显示宠物+EXP；点击打开菜单；右键有菜单

#### 1.3 拆分 `ui/task_panel.py` — 提取 ChatPanel
- [ ] 将当前 `TaskPanel` 重命名为 `ChatPanel`（或保留类名，重构内部）
- [ ] 移除永久可见的 History 侧边栏（180px sidebar）
- [ ] 保留：消息气泡、markdown渲染、图片发送/显示、输入框
- [ ] 保留：会话切换功能，但改为非侧边栏形式（后续 Phase 6 做抽屉）
- [ ] 调整头部：Lobuddy Chat + [History]按钮 + [Settings]按钮 + [X]
- [ ] `task_submitted` 信号保留
- [ ] 删除大红色 Delete 按钮从主布局
- **验收**: ChatPanel 可打开/关闭；能发送消息；无永久侧边栏

#### 1.4 更新 `app/main.py` — 重新连接信号
- [ ] `pet_window.task_requested` → 改为打开 `QuickActionMenu`
- [ ] `quick_action_menu.chat_clicked` → `show_task_panel()`（即打开 ChatPanel）
- [ ] `quick_action_menu.pet_clicked` → `show_pet_settings()`
- [ ] `quick_action_menu.settings_clicked` → `on_settings_requested()`
- [ ] 保留所有现有 TaskManager 信号连接
- **验收**: 应用启动只显示宠物；点击宠物→菜单→Chat 能打开聊天

---

### 🔵 Phase 2: 视觉主题 redesign

**目标**: 替换当前绿/白 admin 风格为 cozy 桌面伴侣风格。

#### 2.1 重写 `ui/styles.py` — Cozy 主题 QSS
- [ ] 替换全局配色为 plan 指定的 cozy 色板：
  - Background: `#FFF7ED`, Panel: `#FFFFFF`, Primary: `#F97316`
  - Text: `#1F2937`, Muted: `#6B7280`, Border: `#F3D9B1`
  - Success: `#22C55E`, Warning: `#F59E0B`, Error: `#EF4444`
- [ ] 圆角：大面板 16px-24px，按钮 12px-18px
- [ ] 阴影：为浮动面板添加柔和阴影
- [ ] 字体：优先 `Microsoft YaHei UI` / `Segoe UI`
- [ ] 重新设计所有样式常量（保留原有命名，替换值）
- **验收**: 运行后 UI 整体呈现暖色调，无大面积绿色/红色按钮

#### 2.2 更新 PetWindow 样式
- [ ] EXP 条改为 cozy 配色（橙色渐变 `#F97316` → `#FB923C`）
- [ ] 等级标签改用新字体和颜色
- **验收**: EXP 条与宠物图片不冲突

#### 2.3 更新 ChatPanel 样式
- [ ] 用户消息气泡：Primary 色背景，白色文字
- [ ] 助手消息气泡：浅灰背景，深色文字
- [ ] 输入框：圆角、浅色背景、聚焦高亮
- [ ] Send 按钮：Primary 色圆角按钮
- **验收**: 聊天界面看起来统一、温暖

---

### 🔵 Phase 3: 任务卡片系统

**目标**: 将工具执行结果从长文本聊天改为结构化任务卡片。

> ⚠️ **风险**: 当前 `TaskManager` 不暴露中间步骤。本 Phase 先做「简单结果卡片」，步骤明细待 Phase 3b（需要 backend 改造）。

#### 3.1 新建 `core/models/task_card.py` — 任务卡片数据模型
- [ ] `TaskStatus` 复用现有 `core.models.pet.TaskStatus`
- [ ] 新建 `TaskCardModel` dataclass：
  - `title`, `status`, `short_result`, `details`, `exp_reward`
- [ ] 新建 `TaskStep` dataclass（预留，当前可先空实现）
- **验收**: 模型可被 UI 层导入使用

#### 3.2 新建 `ui/task_card_panel.py` — TaskCardPanel 组件
- [ ] `TaskCardPanel` 类，显示在宠物附近（浮动小卡片）
- [ ] 字段：任务标题、状态图标（pending/running/success/warning/failed）
- [ ] 短结果文字（1-2行）
- [ ] 「查看详情」可折叠区域（显示完整日志/原始结果）
- [ ] 动作按钮：「继续操作」「截图」「打开网页」「查看详情」
- [ ] EXP 奖励显示（成功时）
- [ ] 卡片自动关闭或最小化逻辑
- **验收**: 运行任务时卡片出现；成功/失败有对应状态；详情可折叠

#### 3.3 更新 `app/main.py` — 任务结果改为卡片
- [ ] `on_task_completed` 中：
  - 向 `TaskCardPanel` 发送结构化数据（而非纯文本）
  - 向 `ChatPanel` 只发送短摘要（宠物气泡）
- [ ] 保留向 `ChatPanel` 的完整消息作为 fallback
- **验收**: 任务结果以卡片显示；聊天只显示简短摘要

#### 3.4 （可选/延后）Phase 3b: 任务步骤追踪
- [ ] 需要修改 `core/agent/nanobot_adapter.py` 或 `core/tasks/task_manager.py` 暴露中间工具调用步骤
- [ ] 或：在 `TaskResult` 中增加 `steps` 字段，通过解析 nanobot 输出文本生成步骤列表
- **风险**: 需要 nanobot 集成层配合，不属于纯 UI 改动

---

### 🔵 Phase 4: 宠物自定义

**目标**: 允许用户上传自定义宠物图片/GIF，调节缩放和透明度。

#### 4.1 扩展 `core/models/appearance.py` — 支持用户资产
- [ ] `PetAppearance` 新增字段：
  - `custom_asset_path: str | None`
  - `custom_asset_type: str` ("default" / "image" / "gif")
  - `scale: float = 1.0`
  - `opacity: float = 1.0`
  - `position_x: int = 100`, `position_y: int = 100`
  - `always_on_top: bool = True`
- [ ] 更新 `save_to_file` / `load_from_file` 方法
- **验收**: 新字段能正确序列化/反序列化

#### 4.2 新建 `ui/pet_settings_panel.py` — PetSettingsPanel
- [ ] `PetSettingsPanel` 对话框/面板
- [ ] 当前预览区（显示当前宠物）
- [ ] 「上传图片/GIF」按钮 → `QFileDialog`
  - 过滤：`*.png *.jpg *.jpeg *.webp *.gif`
  - 大小限制：20MB
- [ ] 缩放滑块（0.5x - 2.0x）
- [ ] 透明度滑块（0.3 - 1.0）
- [ ] 「重置位置」按钮
- [ ] 「恢复默认宠物」按钮
- [ ] 「保存」按钮
- **验收**: 面板能打开；各控件有响应；预览实时更新

#### 4.3 新建 `core/services/pet_asset_service.py` — PetAssetService
- [ ] `validate_asset(path) -> ValidationResult`（类型、大小）
- [ ] `copy_to_app_data(path) -> copied_path`
  - 目标：`data/user_assets/pets/pet_YYYYMMDD_HHMMSS.<ext>`
  - 目录不存在则创建
- [ ] `detect_asset_type(path) -> image/gif/invalid`
- [ ] `remove_asset(path)` 清理旧文件
- [ ] 文件名生成：`pet_{timestamp}.{ext}`
- **验收**: 上传 PNG/GIF 能被复制到正确位置；验证能拒绝大文件/非法类型

#### 4.4 扩展 `ui/asset_manager.py` — 支持自定义资产
- [ ] `AssetManager` 读取 `PetAppearance.custom_asset_path` 优先于默认路径
- [ ] 自定义文件不存在时自动回退到默认 pet
- [ ] 支持 scale/opacity 参数传入（影响 QMovie.setScaledSize 和 QLabel 透明度）
- **验收**: 上传自定义图片后宠物立即更新；删除文件后回退默认

#### 4.5 更新 `app/main.py` — 持久化宠物设置
- [ ] 启动时从 `PetAppearance.load_from_file()` 读取位置/缩放/透明度，应用到 `PetWindow`
- [ ] 宠物移动结束时保存位置到 `PetAppearance`
- [ ] `PetSettingsPanel` 保存时更新 `PetAppearance` 并调用 `save_to_file()`
- **验收**: 自定义宠物在重启后仍然有效；位置/缩放/透明度持久化

---

### 🔵 Phase 5: 宠物交互增强

**目标**: 让宠物更有生命感。

#### 5.1 扩展 `PetWindow` — 状态气泡
- [ ] 新增 `SpeechBubble` 浮动 QLabel（限时显示，2-4秒后淡出）
- [ ] 状态对应默认气泡文字：
  - idle: "..." 或随机短语
  - working: "正在努力处理中..."
  - success: "任务完成啦！"
  - failed: "哎呀，出错了..."
- [ ] 气泡位置：宠物上方，自动调整大小
- [ ] 气泡样式：圆角白底+柔和阴影+小三角
- **验收**: 切换状态时显示对应气泡；气泡自动消失

#### 5.2 扩展 `PetWindow` — 位置保存
- [ ] `mouseReleaseEvent` 中：如果移动了超过阈值，保存新位置到 `PetAppearance`
- [ ] 启动时恢复上次位置
- **验收**: 拖拽宠物后重启，宠物出现在新位置

#### 5.3 扩展 `PetWindow` — always-on-top 切换
- [ ] 新增属性/方法 `set_always_on_top(enabled)`
- [ ] 在右键菜单中添加「置顶」复选菜单项
- [ ] 注意：Qt 中 `WindowStaysOnTopHint` 需要重新创建窗口或调用 `setWindowFlags` 后 `show()`
- **验收**: 可切换置顶状态；重启后保持

#### 5.4 完善右键菜单
- [ ] 右键点击宠物弹出 `QMenu`
- [ ] 菜单项：Open Chat / Pet Settings / Always on Top / Exit
- [ ] 样式与 cozy 主题一致
- **验收**: 右键菜单功能完整、样式统一

---

### 🔵 Phase 6: 历史抽屉

**目标**: 将永久历史侧边栏改为可折叠抽屉。

#### 6.1 重构 ChatPanel — 添加 HistoryDrawer
- [ ] 将当前左侧 sidebar（历史列表）提取为独立的 `HistoryDrawer` 组件
- [ ] 默认隐藏，通过 ChatPanel 头部的 [History] 按钮切换显示
- [ ] 抽屉从左侧滑入/滑出（QPropertyAnimation）
- [ ] 历史项改为卡片样式（显示标题+最后消息预览+时间）
- [ ] 删除按钮移入每个历史项的上下文菜单或抽屉底部
- **验收**: 历史默认隐藏；点击按钮展开；删除不再是大红按钮

#### 6.2 更新样式
- [ ] 抽屉背景：`#FFFFFFDD`（半透明白）
- [ ] 历史项悬停/选中效果与 cozy 主题一致
- **验收**: 抽屉视觉与整体主题统一

---

## 关键决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 设置持久化方式 | **沿用 SQLite**（`settings_repo`） | 已有 `get_json_setting`/`set_json_setting`，无需引入第二套 JSON 文件数据源。计划中的 `data/settings/ui_settings.json` 可映射为 SQLite 中 `ui_settings` 键的 JSON 值。 |
| 任务步骤追踪 | **Phase 3 先做简单结果卡片**，步骤追踪延后到 Phase 3b | 当前 nanobot 集成层不暴露中间步骤，需要 backend 改造。先做结果卡片可快速见效。 |
| PetAppearance 与 PetConfig 关系 | **扩展 PetAppearance**，不新建 PetConfig | 现有 `PetAppearance` 已有状态图片映射+尺寸，只需新增自定义资产/位置/透明度字段即可。避免模型冗余。 |
| 宠物文件存储路径 | **`data/user_assets/pets/`**（相对运行目录） | 与计划中一致。`data/` 目录已在 bootstrap 中创建，只需新增子目录。 |
| 宠物位置保存时机 | **mouseReleaseEvent 中保存** | 避免频繁写文件；只在拖拽结束后保存。 |

---

## 回归测试清单

每次完成一个 Phase 后运行：

- [ ] `pytest tests/ -v` 全部通过
- [x] App 正常启动，PetWindow 可见
- [x] 点击宠物能打开 QuickActionMenu（支持点击外部关闭）
- [x] ChatPanel 能打开/关闭，消息发送正常
- [x] 任务提交到完成流程正常（Agent backend 无变化）
- [x] 任务卡片显示结构化结果（继续操作/截图/打开网页/查看详情）
- [x] 宠物自定义面板支持上传图片/GIF、缩放、透明度、预览
- [x] 宠物设置保存后立即生效（reload_appearance）
- [x] 宠物位置、缩放、透明度持久化
- [x] 托盘 Exit 能正常退出
- [x] 重复打开/关闭 ChatPanel 无崩溃
- [x] 无边框窗口拖拽正常
- [x] 所有信号已连接，无 dead signal

---

## Oracle 审查后修复（第 2 轮）

| 问题 | 修复 |
|---|---|
| QuickActionMenu 点击外部不关闭 | 添加 `_OutsideClickFilter` 事件过滤器 |
| main.py 多个 dead signal | `history_requested`→显示提示信息；`continue_clicked`→打开 ChatPanel；`screenshot_clicked`/`open_web_clicked`→显示功能提示 |
| PetWindow 未应用 scale/opacity | 添加 `_apply_appearance()` 和 `reload_appearance()`，在启动和设置保存后调用 |
| TaskCardPanel 缺少截图/打开网页按钮 | 添加两个按钮并连接信号 |
| History 按钮无响应 | 连接信号到提示对话框 |

---

## 执行状态

**已完成**: Phase 1-5 + Oracle 审查修复 + 回归测试全部通过（224/224 tests passed）
**状态**: 全部核心功能实现完毕，所有信号已连接，无已知 dead code

---

## 工作量估算

| Phase | 预估工作量 | 主要新建文件 | 主要修改文件 |
|---|---|---|---|
| Phase 1: UI Shell 分离 | 1-2 天 | `quick_action_menu.py`, `chat_panel.py`(重构) | `pet_window.py`, `task_panel.py`, `main.py` |
| Phase 2: 视觉主题 | 0.5-1 天 | — | `styles.py`, `pet_window.py`, `task_panel.py` |
| Phase 3: 任务卡片 | 1-2 天 | `task_card_panel.py`, `task_card.py`(model) | `main.py`, `task_panel.py` |
| Phase 4: 宠物自定义 | 1-2 天 | `pet_settings_panel.py`, `pet_asset_service.py` | `appearance.py`, `asset_manager.py`, `main.py` |
| Phase 5: 宠物交互增强 | 0.5-1 天 | — | `pet_window.py` |
| Phase 6: 历史抽屉 | 0.5-1 天 | `history_drawer.py` | `task_panel.py` |
| **总计** | **5-9 天** | | |

> 估算基于现有代码已有大量基础（PetWindow、AssetManager、SQLite 持久化），纯 UI 层面增量开发。

---

## 下一步建议

1. **确认设置持久化方案**：是否同意沿用 SQLite（`settings_repo`）而非新建 JSON 文件？
2. **确认任务卡片范围**：Phase 3 先做「结果卡片」（无中间步骤），还是等 backend 暴露步骤后再做完整卡片？
3. **开始 Phase 1**：新建 `QuickActionMenu` → 重构 `PetWindow` 点击行为 → 拆分 `ChatPanel`
