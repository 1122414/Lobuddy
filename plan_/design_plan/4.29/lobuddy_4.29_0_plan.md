# Lobuddy 4.29.0 下一阶段开发计划：设置中心 + 陪伴体验 + AI 可用性增强

> 交付给 opencode 执行。  
> 当前阶段目标：把 Lobuddy 从“有桌宠外观的聊天窗口”升级为“普通用户可配置、可陪伴、可长期使用的桌面宠物 AI 助手”。

---

## 0. 当前状态判断

从当前截图和已完成修复看，Lobuddy 已具备以下基础能力：

- 主聊天窗口可用；
- 左侧宠物卡片可显示图片 / GIF；
- 历史对话列表已经能显示真实 message 数量；
- 消息时间和右侧时间线已经初步实现；
- 设置窗口已有基础 Tab：基础设置、外观装扮、主题设置、陪伴设置、高级设置；
- 部分陪伴能力已经初步接入，例如宠物时钟、聊天时间线等。

但目前仍存在下一阶段必须解决的问题：

1. 设置面板仍然不是完整的“用户配置中心”；
2. 很多陪伴参数仍然没有暴露给用户自定义；
3. `.env` 和设置面板需要形成可靠的双向同步；
4. API、错误展示、模型连接测试等对普通用户不够友好；
5. 宠物的“陪伴感”还不够强，仍然偏工具化；
6. 后续记忆、专注、主动问候、收藏等能力需要预留接口。

---

## 1. 本阶段总目标

本阶段版本建议命名：

```txt
Lobuddy v0.4.29.0 - Companion Settings Core
```

核心目标：

> 将设置面板升级为普通用户唯一需要接触的配置中心，并围绕“陪伴感”完成第一批可配置能力。

也就是说，用户不需要改源码、不需要手动改 `.env`，只需要打开“设置小窝”就能配置：

- 宠物名字；
- 宠物外观；
- 是否每日问候；
- 每日问候几次；
- 超过几小时未互动后提醒；
- 点击宠物是否有反馈；
- 是否显示时间线；
- 是否显示消息时间；
- 专注默认几分钟；
- API Key / Base URL / Model；
- 是否显示原始错误详情；
- 是否开启记忆；
- 是否收藏消息。

---

## 2. 开发边界

### 2.1 本阶段必须做

本阶段必须完成以下 5 类任务：

1. **配置系统底座**
   - 统一 ConfigManager；
   - `.env` 读取、保存、reload；
   - 类型转换和默认值 schema；
   - 设置保存后运行时立即生效；
   - 防止 API Key 被掩码覆盖。

2. **设置面板扩展**
   - 补齐陪伴设置；
   - 新增聊天设置；
   - 新增记忆设置；
   - 新增专注模式；
   - 新增 AI 设置；
   - 整理高级设置。

3. **`.env` 与设置面板双向同步**
   - 打开设置面板时从 `.env` 读取；
   - 设置保存后写回 `.env`；
   - 外部修改 `.env` 后再次打开设置面板能同步；
   - 可选：使用 QFileSystemWatcher 监听 `.env` 变化。

4. **陪伴体验第一批落地**
   - 用户可配置每日问候；
   - 用户可配置未互动提醒；
   - 用户可配置宠物点击反馈；
   - 用户可配置宠物时钟；
   - 用户可配置消息时间 / 时间分隔条 / 右侧时间线。

5. **AI 可用性增强**
   - API 设置页；
   - 模型连接测试；
   - 错误卡片化；
   - 原始错误默认折叠；
   - API Key 不在日志中完整输出。

---

### 2.2 本阶段严禁做

本阶段不要做以下事情：

1. 不要重写整个 UI；
2. 不要引入大型 UI 框架；
3. 不要引入复杂数据库；
4. 不要做完整多人格系统；
5. 不要做复杂宠物养成数值系统；
6. 不要做完整 prompt 编辑器；
7. 不要把子 Agent、token 压缩策略、内部调度策略暴露给普通用户；
8. 不要要求用户手动修改源码；
9. 不要要求用户手动修改 `.env`；
10. 不要把配置默认值散落到多个 UI 文件里；
11. 不要让设置保存失败时静默失败；
12. 不要保存 API Key 的掩码值，例如 `******`、`••••••`；
13. 不要因为某个 env 字段缺失导致设置窗口打不开；
14. 不要让设置面板显示的值和实际运行时使用的值不一致。

---

## 3. 配置设计原则

### 3.1 `.env` 的定位

本阶段采用：

```txt
.env = 当前配置持久化层
设置面板 = 普通用户唯一操作入口
ConfigManager = 程序内部唯一配置读写入口
```

也就是说：

- 用户通过设置面板改配置；
- 设置面板通过 ConfigManager 写 `.env`；
- 运行时代码通过 ConfigManager 读取配置；
- 任何 UI / AI / 宠物模块都不应该直接解析 `.env`。

### 3.2 后续迁移预留

虽然本阶段使用 `.env` 作为持久化层，但需要预留未来迁移到：

```txt
data/settings/user_settings.json
```

的接口。

因此 ConfigManager 不应把 `.env` 读写逻辑直接散落到业务层，应保持类似接口：

```python
config.get("PET_NAME")
config.set("PET_NAME", "小窝")
config.update_many({...})
config.save()
config.reload()
```

未来迁移存储格式时，业务层不需要改。

---

## 4. 推荐文件结构

根据现有项目结构微调，不要求完全一致，但建议新增或整理如下模块：

```txt
app/
  config/
    config_manager.py
    config_schema.py
    env_writer.py
    defaults.py

  ui/
    dialogs/
      settings_dialog.py
    settings/
      base_settings_page.py
      appearance_settings_page.py
      theme_settings_page.py
      companion_settings_page.py
      chat_settings_page.py
      memory_settings_page.py
      focus_settings_page.py
      ai_settings_page.py
      advanced_settings_page.py
    widgets/
      setting_row.py
      setting_group.py
      error_card.py

  core/
    companion/
      companion_settings.py
      companion_scheduler.py
      pet_interaction_manager.py
    focus/
      focus_settings.py
    ai/
      llm_config.py
      connection_tester.py
    errors/
      error_presenter.py
```

如果当前项目没有这些目录，不要一次性大重构，可以先在现有结构中最小化新增。

---

## 5. 配置 Schema

### 5.1 必须有统一 schema

新增配置 schema，用来声明：

- env key；
- 类型；
- 默认值；
- UI 显示名；
- 分组；
- 可选项；
- 数值范围；
- 是否敏感字段；
- 是否允许写入 `.env`。

示例结构：

```python
CONFIG_SCHEMA = {
    "PET_NAME": {
        "type": "str",
        "default": "MyBuddy",
        "label": "宠物名字",
        "group": "base",
        "sensitive": False,
    },
    "LLM_API_KEY": {
        "type": "password",
        "default": "",
        "label": "API Key",
        "group": "ai",
        "sensitive": True,
    },
}
```

### 5.2 类型要求

必须支持这些类型：

```txt
str
int
float
bool
password
select
time
path
```

### 5.3 bool 解析规则

`.env` 中以下值都应能识别为 true：

```txt
true
True
TRUE
1
yes
on
```

以下值识别为 false：

```txt
false
False
FALSE
0
no
off
```

非法值回退默认值，并记录 warning。

---

## 6. 本阶段必须接入的设置项

### 6.1 P0 MVP 设置项

以下 12 个为本阶段最小必须接入项：

```env
COMPANION_GREETING_ENABLED=true
COMPANION_GREETING_MAX_PER_DAY=3
COMPANION_IDLE_REMIND_HOURS=2
PET_CLICK_FEEDBACK_ENABLED=true
PET_CLOCK_ENABLED=true
CHAT_SHOW_MESSAGE_TIME=true
CHAT_SHOW_TIME_DIVIDER=true
CHAT_TIMELINE_ENABLED=true
MEMORY_ENABLED=true
MEMORY_CONFIRM_BEFORE_SAVE=true
FOCUS_DEFAULT_MINUTES=25
FOCUS_BREAK_MINUTES=5
```

这些必须满足：

1. 出现在设置面板中；
2. 能从 `.env` 读取；
3. 能保存回 `.env`；
4. 保存后运行时立即生效；
5. 重启后仍然保留。

---

### 6.2 完整建议设置项

#### 基础设置

| UI 名称 | env key | 类型 | 默认值 | 优先级 |
|---|---|---|---|---|
| 宠物名字 | PET_NAME | str | MyBuddy | P0 |
| 窗口始终置顶 | WINDOW_ALWAYS_ON_TOP | bool | true | P0 |
| 启动时打开聊天窗口 | OPEN_CHAT_ON_STARTUP | bool | true | P1 |
| 启动时显示宠物 | SHOW_PET_ON_STARTUP | bool | true | P1 |

#### 外观装扮

| UI 名称 | env key | 类型 | 默认值 | 优先级 |
|---|---|---|---|---|
| 宠物图片 / GIF 路径 | PET_ASSET_PATH | path | 空 | 已有 / P0 |
| 宠物显示大小 | PET_DISPLAY_SCALE | float | 1.0 | 已有 / P0 |
| 启用宠物动画 | PET_ANIMATION_ENABLED | bool | true | 已有 / P0 |
| 显示宠物时钟 | PET_CLOCK_ENABLED | bool | true | P0 |
| 时钟显示秒数 | PET_CLOCK_SHOW_SECONDS | bool | false | P1 |
| 时钟格式 | PET_CLOCK_FORMAT | select | MM/dd HH:mm | P1 |
| 显示今日陪伴时长 | PET_SHOW_COMPANION_DURATION | bool | true | P2 预留 |
| 显示今日互动次数 | PET_SHOW_INTERACTION_COUNT | bool | true | P2 预留 |

#### 主题设置

| UI 名称 | env key | 类型 | 默认值 | 优先级 |
|---|---|---|---|---|
| 主题色 | THEME_COLOR | select | orange | P1 |
| 字体大小 | CHAT_FONT_SIZE | int | 14 | P1 |
| 聊天气泡最大宽度 | CHAT_BUBBLE_MAX_WIDTH | int | 520 | P1 |
| 输入框风格 | CHAT_PLACEHOLDER_STYLE | select | warm | P2 预留 |

#### 陪伴设置

| UI 名称 | env key | 类型 | 默认值 | 优先级 |
|---|---|---|---|---|
| 启用每日问候 | COMPANION_GREETING_ENABLED | bool | true | P0 |
| 启动时问候 | COMPANION_GREETING_ON_STARTUP | bool | true | P1 |
| 每日最多问候次数 | COMPANION_GREETING_MAX_PER_DAY | int | 3 | P0 |
| 超过几小时未互动后提醒 | COMPANION_IDLE_REMIND_HOURS | float | 2 | P0 |
| 启用深夜提醒 | COMPANION_NIGHT_REMIND_ENABLED | bool | true | P1 |
| 深夜提醒时间 | COMPANION_NIGHT_REMIND_AFTER | time | 23:00 | P1 |
| 问候语风格 | COMPANION_GREETING_STYLE | select | warm | P1 |
| 只显示气泡，不主动打开聊天窗 | COMPANION_GREETING_BUBBLE_ONLY | bool | true | P1 |
| 点击宠物反馈 | PET_CLICK_FEEDBACK_ENABLED | bool | true | P0 |
| 点击动画 | PET_CLICK_ANIMATION_ENABLED | bool | true | P1 |
| 点击气泡 | PET_CLICK_BUBBLE_ENABLED | bool | true | P1 |
| 连续点击彩蛋 | PET_CLICK_EASTER_EGG_ENABLED | bool | true | P1 |
| 点击反馈冷却时间 | PET_CLICK_COOLDOWN_MS | int | 800 | P1 |
| 双击宠物行为 | PET_DOUBLE_CLICK_ACTION | select | open_chat | P1 |
| 默认宠物状态文案 | PET_DEFAULT_STATUS | str | 陪伴中 | P1 |

#### 聊天设置

| UI 名称 | env key | 类型 | 默认值 | 优先级 |
|---|---|---|---|---|
| 显示消息时间 | CHAT_SHOW_MESSAGE_TIME | bool | true | P0 |
| 显示时间分隔条 | CHAT_SHOW_TIME_DIVIDER | bool | true | P0 |
| 时间分隔间隔分钟 | CHAT_TIME_DIVIDER_INTERVAL_MINUTES | int | 5 | P1 |
| 显示右侧会话时间线 | CHAT_TIMELINE_ENABLED | bool | true | P0 |
| 时间线 hover 显示摘要 | CHAT_TIMELINE_HOVER_PREVIEW | bool | true | P1 |
| 自动滚动到底部 | CHAT_AUTO_SCROLL_TO_BOTTOM | bool | true | P1 |
| 启用消息收藏 | HIGHLIGHT_ENABLED | bool | true | P2 预留 |
| 显示消息收藏按钮 | HIGHLIGHT_HOVER_BUTTON | bool | true | P2 预留 |

#### 记忆设置

| UI 名称 | env key | 类型 | 默认值 | 优先级 |
|---|---|---|---|---|
| 启用长期记忆 | MEMORY_ENABLED | bool | true | P0 |
| 保存记忆前需要确认 | MEMORY_CONFIRM_BEFORE_SAVE | bool | true | P0 |
| 自动提取候选记忆 | MEMORY_AUTO_EXTRACT_CANDIDATES | bool | true | P1 |
| 首页最多显示记忆数量 | MEMORY_HOME_MAX_ITEMS | int | 3 | P1 |
| 显示“我的记忆”按钮 | MEMORY_BUTTON_VISIBLE | bool | true | P1 |
| 允许用户编辑记忆 | MEMORY_USER_EDITABLE | bool | true | P2 预留 |
| 允许用户删除记忆 | MEMORY_USER_DELETABLE | bool | true | P2 预留 |

#### 专注模式

| UI 名称 | env key | 类型 | 默认值 | 优先级 |
|---|---|---|---|---|
| 启用专注陪伴模式 | FOCUS_MODE_ENABLED | bool | true | P1 |
| 默认专注时长分钟 | FOCUS_DEFAULT_MINUTES | int | 25 | P0 |
| 默认休息时长分钟 | FOCUS_BREAK_MINUTES | int | 5 | P0 |
| 专注结束提醒 | FOCUS_END_REMINDER_ENABLED | bool | true | P1 |
| 休息结束提醒 | FOCUS_BREAK_END_REMINDER_ENABLED | bool | true | P1 |
| 专注时静默问候 | FOCUS_MUTE_GREETING | bool | true | P1 |
| 专注时宠物状态文案 | FOCUS_STATUS_TEXT | str | 陪你专注中 | P1 |
| 自动循环专注 / 休息 | FOCUS_AUTO_LOOP | bool | false | P2 预留 |

#### AI 设置

| UI 名称 | env key | 类型 | 默认值 | 优先级 |
|---|---|---|---|---|
| API Key | LLM_API_KEY | password | 空 | P0 |
| Base URL | LLM_BASE_URL | str | 空 | P0 |
| Model | LLM_MODEL | str | 空 | P0 |
| Provider | LLM_PROVIDER | select | openai_compatible | P1 |
| 默认 AI 模式 | AI_DEFAULT_MODE | select | chat | P1 |
| 自动判断聊天 / 任务模式 | AI_AUTO_MODE_DETECTION | bool | false | P2 预留 |
| 陪聊回复长度 | AI_CHAT_REPLY_LENGTH | select | normal | P1 |
| 陪聊语气 | AI_CHAT_TONE | select | warm | P1 |
| 任务模式显示执行过程 | AI_TASK_SHOW_PROGRESS | bool | true | P1 |
| 工具调用前确认 | AI_CONFIRM_BEFORE_TOOL_USE | bool | true | P1 |
| Shell Tool | ENABLE_SHELL_TOOL | bool | false | 已有 / P0 |
| Task Timeout | TASK_TIMEOUT_SECONDS | int | 120 | 已有 / P0 |

#### 高级设置

| UI 名称 | env key | 类型 | 默认值 | 优先级 |
|---|---|---|---|---|
| 错误卡片展示 | ERROR_CARD_ENABLED | bool | true | P0 |
| 显示原始错误详情 | ERROR_SHOW_RAW_DETAIL | bool | false | P0 |
| 错误时显示打开设置按钮 | ERROR_SHOW_OPEN_SETTINGS_BUTTON | bool | true | P1 |
| 保存错误日志 | ERROR_SAVE_LOG | bool | true | P1 |
| 日志等级 | LOG_LEVEL | select | INFO | P1 |

---

## 7. 设置面板 UI 规划

### 7.1 Tab 调整

当前 Tab：

```txt
基础设置
外观装扮
主题设置
陪伴设置
高级设置
```

调整为：

```txt
基础设置
外观装扮
主题设置
陪伴设置
聊天设置
记忆设置
专注模式
AI 设置
高级设置
```

如果横向 Tab 空间不够，优先改为左侧竖向分类导航。

### 7.2 设置项交互规范

每个设置项应包含：

1. 中文名称；
2. 控件；
3. 可选说明文字；
4. 保存时类型校验；
5. 非法输入提示。

示例：

```txt
每日最多问候次数    [ 3 ]
小窝每天最多主动问候你的次数，建议 1-3 次，避免打扰。
```

### 7.3 控件选择规范

| 类型 | 控件 |
|---|---|
| bool | QCheckBox |
| int | QSpinBox |
| float | QDoubleSpinBox |
| str | QLineEdit |
| password | QLineEdit + Show/Hide |
| select | QComboBox |
| time | QTimeEdit 或格式校验 QLineEdit |
| path | QLineEdit + 选择文件按钮 |

---

## 8. 详细开发任务拆解

## Phase 1：配置系统底座 P0

### Task 1.1：创建配置 schema

目标：建立所有已知配置项的统一定义。

要做：

1. 新增 `config_schema.py`；
2. 定义每个 env key 的类型、默认值、分组、中文名、说明；
3. 标记敏感字段，例如 `LLM_API_KEY`；
4. 标记可选项，例如主题色、问候风格、AI 模式；
5. 标记数值范围，例如专注时长、问候次数。

验收：

- schema 能覆盖 P0 12 项；
- schema 能覆盖已有基础设置；
- 没有默认值散落在 UI 文件中。

---

### Task 1.2：实现 ConfigManager

目标：所有配置读写都走统一入口。

要做：

1. 新增或整理 `ConfigManager`；
2. 支持 `load()` 从 `.env` 读取；
3. 支持 `save()` 写回 `.env`；
4. 支持 `reload()`；
5. 支持 `get()`、`set()`、`update_many()`；
6. 支持 `get_bool()`、`get_int()`、`get_float()`；
7. 支持信号或回调 `config_changed`；
8. 支持运行时订阅配置变更。

验收：

- 设置窗口、AI client、宠物时钟、聊天窗口均不再直接读 `.env`；
- 修改 `.env` 后 ConfigManager 能 reload；
- 保存设置后能通知 UI 立即刷新。

---

### Task 1.3：实现 `.env` 安全写入

目标：可靠写回 `.env`。

要做：

1. 保留未知字段；
2. 只更新已知字段；
3. 使用原子写入：先写临时文件，再 replace；
4. 写入前校验类型；
5. 保存失败要弹出错误提示；
6. API Key 不能被掩码覆盖；
7. 如果 API Key 输入框未修改，则保留原值。

验收：

- `.env` 原有未知字段不丢失；
- API Key 不会变成 `******`；
- 保存失败时用户能看到提示。

---

### Task 1.4：缺失 `.env` 自动生成

目标：降低小白用户启动门槛。

要做：

1. 如果 `.env` 不存在，自动基于 schema 生成；
2. 敏感字段默认空；
3. 生成后记录日志；
4. 设置面板可以正常打开。

验收：

- 删除 `.env` 后程序能启动；
- 设置面板能显示默认值；
- 保存后 `.env` 被创建。

---

## Phase 2：设置面板扩展 P0 / P1

### Task 2.1：重构设置窗口为多页配置中心

目标：在不推翻现有 UI 的前提下扩展设置窗口。

要做：

1. 保留现有“设置小窝”视觉风格；
2. 新增 Tab：聊天设置、记忆设置、专注模式、AI 设置；
3. 如 Tab 太多，改为左侧竖向导航；
4. 每页使用统一的 SettingGroup / SettingRow 风格；
5. 每页设置项从 ConfigManager 初始化。

验收：

- 设置窗口不拥挤；
- 所有 Tab 可以正常切换；
- 保存 / 取消行为一致。

---

### Task 2.2：基础设置页接入 ConfigManager

要做：

1. `PET_NAME`；
2. `WINDOW_ALWAYS_ON_TOP`；
3. `OPEN_CHAT_ON_STARTUP`；
4. `SHOW_PET_ON_STARTUP`。

验收：

- 修改宠物名字后左侧宠物卡片立即更新；
- 修改置顶设置后窗口置顶行为立即变化；
- 保存后 `.env` 正确更新。

---

### Task 2.3：外观装扮页接入 ConfigManager

要做：

1. 宠物图片 / GIF 路径；
2. 显示大小；
3. 动画开关；
4. 时钟开关；
5. 是否显示秒；
6. 时钟格式。

验收：

- 修改 `PET_CLOCK_ENABLED=false` 后宠物时钟立即隐藏；
- 修改宠物大小后 UI 能更新；
- 图片路径保存后重启仍然生效。

---

### Task 2.4：陪伴设置页补齐

要做：

1. 每日问候开关；
2. 启动时问候；
3. 每日最多问候次数；
4. 未互动提醒小时数；
5. 深夜提醒；
6. 深夜提醒时间；
7. 问候语风格；
8. 点击宠物反馈；
9. 点击动画；
10. 点击气泡；
11. 连续点击彩蛋；
12. 点击冷却；
13. 双击宠物行为；
14. 默认宠物状态文案。

验收：

- 关闭点击反馈后点击宠物不再弹反馈；
- 修改未互动提醒小时数后 CompanionScheduler 使用新值；
- 修改问候次数后当天问候次数限制生效。

---

### Task 2.5：新增聊天设置页

要做：

1. 消息时间开关；
2. 时间分隔条开关；
3. 时间分隔间隔；
4. 右侧时间线开关；
5. 时间线 hover 摘要开关；
6. 自动滚动到底部；
7. 收藏按钮开关预留。

验收：

- 关闭消息时间后气泡时间隐藏；
- 关闭时间分隔条后新消息不再插入时间分隔条；
- 关闭右侧时间线后时间线立即隐藏。

---

### Task 2.6：新增记忆设置页

要做：

1. 长期记忆开关；
2. 保存前确认；
3. 自动提取候选记忆；
4. 首页记忆显示数量；
5. 我的记忆按钮显示；
6. 编辑 / 删除记忆开关预留。

验收：

- 关闭 `MEMORY_ENABLED` 后 UI 不再主动展示记忆写入入口；
- 关闭 `MEMORY_BUTTON_VISIBLE` 后底部“我的记忆”按钮隐藏；
- 设置写入 `.env`。

---

### Task 2.7：新增专注模式页

要做：

1. 专注模式开关；
2. 默认专注时长；
3. 默认休息时长；
4. 专注结束提醒；
5. 休息结束提醒；
6. 专注时静默问候；
7. 专注状态文案；
8. 自动循环预留。

验收：

- 修改默认专注时长后，下一次开始专注时使用新值；
- 关闭专注模式后相关入口隐藏或不可用；
- 保存后 `.env` 正确更新。

---

### Task 2.8：新增 AI 设置页

要做：

1. API Key；
2. Base URL；
3. Model；
4. Provider；
5. 默认 AI 模式；
6. 自动模式判断预留；
7. 陪聊回复长度；
8. 陪聊语气；
9. 任务过程显示；
10. 工具调用前确认；
11. Shell Tool；
12. Task Timeout；
13. 模型连接测试按钮。

验收：

- 修改 API Key 后下一次请求使用新 key；
- 修改模型后下一次请求使用新模型；
- API Key 不在日志中完整显示；
- Show / Hide 按钮可用。

---

### Task 2.9：高级设置页整理

要做：

1. 错误卡片展示；
2. 显示原始错误详情；
3. 错误时显示打开设置按钮；
4. 保存错误日志；
5. 日志等级。

验收：

- 默认不显示 raw JSON；
- 开启原始错误后才能展开详情；
- 日志等级保存生效。

---

## Phase 3：运行时同步 P0

### Task 3.1：设置保存后立即刷新 UI

目标：用户点击保存后不用重启。

要做：

保存后触发 `config_changed`，相关模块订阅：

1. Pet card：名字、大小、图片、时钟、状态；
2. Chat window：消息时间、时间线、字体大小、气泡宽度；
3. Companion manager：问候次数、未互动提醒、深夜提醒；
4. Focus manager：默认专注 / 休息时长；
5. AI client：API Key、Base URL、Model、Provider。

验收：

- 关闭宠物时钟后立即消失；
- 关闭右侧时间线后立即隐藏；
- 修改字体大小后聊天区刷新；
- 修改 LLM_MODEL 后下一次请求使用新模型。

---

### Task 3.2：`.env` 外部变更同步

目标：即使开发者手动改 `.env`，设置面板也能显示最新值。

要做：

1. 每次打开设置面板时强制 `reload()`；
2. 可选：使用 `QFileSystemWatcher` 监听 `.env`；
3. 如果设置窗口已经打开，并且没有未保存改动，自动刷新；
4. 如果有未保存改动，提示用户是否重新加载。

验收：

- 手动改 `.env` 后重新打开设置面板显示新值；
- 打开设置窗口时不显示旧缓存。

---

## Phase 4：AI 可用性增强 P0 / P1

### Task 4.1：模型连接测试

目标：普通用户可以在设置页知道模型配置是否可用。

要做：

1. AI 设置页增加“测试模型连接”按钮；
2. 点击后发送最小测试请求；
3. 请求超时可配置；
4. 成功显示：`连接成功`；
5. 失败显示用户友好原因；
6. 详情可展开查看原始错误；
7. 不输出完整 API Key。

验收：

- API Key 正确时测试成功；
- API Key 错误时提示“API Key 可能无效”；
- Base URL 错误时提示“服务地址可能不可访问”；
- 模型错误时提示“模型名可能不可用”。

---

### Task 4.2：错误卡片化

目标：不要把 raw JSON 直接塞进聊天气泡。

当前错误示例：

```txt
Error: {"error":{"message":"You didn't provide an API key..."}}
```

应改为：

```txt
模型请求失败

可能原因：
- API Key 未配置或无效
- Base URL 与模型不匹配
- 网络请求失败

[打开 AI 设置] [查看详情]
```

要做：

1. 新增 ErrorCard 组件；
2. 默认展示用户友好错误；
3. raw JSON 默认折叠；
4. 根据错误类型展示不同建议；
5. API 认证失败时提供“打开 AI 设置”按钮。

验收：

- 聊天区不再默认显示一大段 raw JSON；
- 用户能通过按钮直接打开 AI 设置；
- 高级设置开启原始错误后可查看详情。

---

## Phase 5：陪伴功能第一批落地 P1

### Task 5.1：CompanionScheduler

目标：让问候、未互动提醒、深夜提醒有统一调度。

要做：

1. 新增 CompanionScheduler；
2. 每日问候次数限制；
3. 启动问候；
4. 未互动提醒；
5. 深夜提醒；
6. 只显示气泡，不主动打开聊天窗；
7. 读取 ConfigManager 配置。

验收：

- 关闭问候开关后不再主动问候；
- 每日最多问候次数生效；
- 未互动提醒小时数可配置；
- 专注时如果 `FOCUS_MUTE_GREETING=true`，不触发问候。

---

### Task 5.2：PetInteractionManager

目标：宠物点击反馈统一管理。

要做：

1. 单击宠物随机气泡；
2. 点击动画；
3. 点击冷却；
4. 连续点击彩蛋；
5. 双击行为；
6. 读取 ConfigManager 配置。

验收：

- 关闭 `PET_CLICK_FEEDBACK_ENABLED` 后无反馈；
- 关闭 `PET_CLICK_ANIMATION_ENABLED` 后无动画但可保留气泡；
- 连续点击不会卡顿；
- 双击行为按设置执行。

---

### Task 5.3：宠物状态系统

目标：让宠物根据场景显示不同状态。

状态示例：

```txt
陪伴中
Listening
Thinking
Working
Idle
Sleepy
Happy
```

要做：

1. 新增 PetStateManager；
2. 用户输入时显示 Listening；
3. AI 回复中显示 Thinking；
4. 工具任务中显示 Working；
5. 长时间未互动显示 Idle；
6. 深夜显示 Sleepy；
7. 点击宠物显示 Happy；
8. 默认状态读取 `PET_DEFAULT_STATUS`。

验收：

- 状态变化不影响 Agent 逻辑；
- 状态文案可以通过设置更改；
- 状态显示区域不遮挡宠物图片和等级条。

---

## Phase 6：后续接口预留 P1 / P2

本阶段不一定完整实现，但必须预留配置、入口或接口。

### 6.1 记忆管理接口预留

预留：

```python
memory_store.list_memories()
memory_store.add_memory(text, source)
memory_store.update_memory(memory_id, text)
memory_store.delete_memory(memory_id)
memory_store.extract_candidates(message)
```

本阶段只需要设置项和基础入口，不要求做复杂记忆编辑器。

---

### 6.2 消息收藏接口预留

预留：

```python
highlight_store.add(message_id, session_id)
highlight_store.remove(highlight_id)
highlight_store.list()
highlight_store.jump_to_source(highlight_id)
```

本阶段可以只做开关，不要求完整收藏中心。

---

### 6.3 专注模式接口预留

预留：

```python
focus_manager.start(minutes=None)
focus_manager.pause()
focus_manager.resume()
focus_manager.stop()
focus_manager.get_status()
```

本阶段至少保证设置项可配置，后续接入 UI 按钮。

---

### 6.4 AI 模式接口预留

预留：

```python
ai_mode_manager.get_mode()
ai_mode_manager.set_mode("chat" | "task")
ai_mode_manager.should_confirm_tool_use(tool_name)
```

本阶段可以先做默认模式配置，不要求完整自动识别。

---

## 9. 开发优先级

### P0：必须优先完成

1. ConfigManager；
2. 配置 schema；
3. `.env` 安全读写；
4. 设置面板读取 `.env`；
5. 设置面板保存回 `.env`；
6. P0 12 个设置项；
7. API Key 防掩码覆盖；
8. AI 设置页；
9. 模型连接测试；
10. 错误卡片化。

### P1：本阶段建议完成

1. 陪伴设置完整项；
2. 聊天设置完整项；
3. 记忆设置基础项；
4. 专注模式基础项；
5. 运行时配置变更同步；
6. 宠物点击反馈管理；
7. 宠物状态系统；
8. CompanionScheduler。

### P2：预留，不强制完整实现

1. 今日陪伴时长；
2. 今日互动次数；
3. 消息收藏中心；
4. 记忆卡片编辑器；
5. 专注模式完整 UI；
6. AI 自动模式识别；
7. 多主题深度定制；
8. 用户设置从 `.env` 迁移到 `user_settings.json`。

---

## 10. 手动验收清单

### 10.1 配置保存验收

1. 打开设置面板；
2. 修改宠物名字为 `TestPet429`；
3. 点击保存；
4. 检查左侧宠物卡片立即更新；
5. 检查 `.env` 中 `PET_NAME=TestPet429`；
6. 重启程序后仍然显示 `TestPet429`。

---

### 10.2 `.env` 反向同步验收

1. 关闭设置面板；
2. 手动修改 `.env`：

```env
COMPANION_GREETING_MAX_PER_DAY=5
```

3. 重新打开设置面板；
4. 检查每日问候次数显示为 5。

---

### 10.3 API Key 防覆盖验收

1. `.env` 中写入真实 `LLM_API_KEY`；
2. 打开 AI 设置页；
3. 不点击 Show，不修改 API Key；
4. 修改其他字段并保存；
5. 检查 `.env` 中 API Key 仍为真实值；
6. 不应变成 `******` 或空。

---

### 10.4 宠物时钟验收

1. 打开外观设置；
2. 关闭 `显示宠物时钟`；
3. 点击保存；
4. 宠物卡片右下角时钟应立即消失；
5. 再次打开后开启；
6. 时钟重新显示。

---

### 10.5 聊天时间线验收

1. 打开聊天设置；
2. 关闭 `显示右侧会话时间线`；
3. 点击保存；
4. 聊天窗口右侧时间线隐藏；
5. 再次开启后恢复。

---

### 10.6 模型连接测试验收

1. 打开 AI 设置；
2. 填写正确 API Key / Base URL / Model；
3. 点击测试模型连接；
4. 应显示连接成功；
5. 改成错误 API Key；
6. 应显示友好错误，不显示一大段 raw JSON。

---

### 10.7 错误卡片验收

1. 故意使用错误 API Key；
2. 发送消息；
3. 聊天区应出现错误卡片；
4. 默认不展示完整 JSON；
5. 点击“查看详情”后可以展开；
6. 点击“打开 AI 设置”可以打开设置页。

---

## 11. 自动化测试建议

至少补充以下测试：

```txt
tests/test_config_manager.py
tests/test_env_writer.py
tests/test_settings_schema.py
tests/test_llm_config.py
tests/test_error_presenter.py
```

### 必测点

1. bool 类型解析；
2. int / float 类型解析；
3. 缺失字段回退默认值；
4. 非法字段回退默认值；
5. 保存 `.env` 保留未知字段；
6. API Key 不被掩码覆盖；
7. 配置更新后触发 config_changed；
8. 错误分类是否正确映射成用户友好文案。

---

## 12. 给 opencode 的执行要求

执行时必须遵守：

1. 每个 Phase 完成后先运行测试或手动验证；
2. 不要一次性大规模重构；
3. 先做 ConfigManager，再改设置 UI；
4. 所有设置项必须有默认值；
5. 所有用户可见文案使用中文；
6. 所有新增功能必须可以关闭；
7. 任何保存失败都必须提示用户；
8. 任何 API Key 日志都必须脱敏；
9. 修复完成后说明修改了哪些文件；
10. 最终给出完整验收记录。

---

## 13. 最终交付物

完成后应交付：

1. 新的配置管理模块；
2. 新的配置 schema；
3. 可双向同步 `.env` 的设置面板；
4. 新增设置页：聊天设置、记忆设置、专注模式、AI 设置；
5. 完整陪伴设置项；
6. 模型连接测试；
7. 错误卡片展示；
8. P0 12 个设置项全部可视化；
9. 保存后运行时立即生效；
10. 测试或手动验证说明。

---

## 14. 一句话原则

```txt
.env 是配置持久化层，不是用户操作入口；设置面板才是 Lobuddy 的唯一用户配置入口。
```

