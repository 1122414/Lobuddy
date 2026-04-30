# Lobuddy 4.29.1 执行计划：AI 用户画像记忆 + 专注陪伴 + 技能面板

> 版本目标：在不重构现有架构、不引入大型依赖的前提下，让 Lobuddy 从“稳定可用的桌宠聊天窗口”升级为“会逐渐理解主人、能陪伴专注、能展示能力边界的桌面伙伴”。

---

## 0. 当前阶段判断

4.29.0 start 版本已经完成以下基础能力：

- 设置窗口基础可用。
- `.env` / 运行时设置同步基础已修复。
- 宠物 UI、聊天窗口、历史窗口、时间显示、右侧会话时间线已具备雏形。
- API 错误展示、宠物布局、任务卡片等稳定性问题已经进入可用状态。
- 项目中已有一些 reserved 模块，例如 memory、highlight、focus 相关模块，但上个阶段没有展开。

因此 4.29.1 不再继续做纯 UI 修补，而是进入 **Companion Core** 阶段。

本阶段只做三个主功能：

1. **AI 自动用户画像 / USER.md 记忆系统**
2. **本地专注陪伴 / 小番茄钟**
3. **“我会的技能”面板**

明确不做：消息收藏 / 高光记录。

---

## 1. 产品目标

### 1.1 一句话目标

实现 AI 自动维护 `USER.md` 用户画像，让 Lobuddy 在长期对话中逐渐理解主人；同时补齐本地专注陪伴和“我会的技能”面板，增强桌宠陪伴感和可用性。

### 1.2 用户体验目标

用户不需要手动维护记忆，也不需要懂源码。Lobuddy 应该在以下过程中逐渐理解用户：

- 用户多次表达自己的偏好。
- 用户持续推进某个项目。
- 用户反复要求某类输出格式。
- 用户明确说“以后你要……”“我不喜欢……”“记住……”。
- 用户完成阶段性事件，例如完成某个版本、改变开发优先级。

最终用户应该感受到：

> 这个桌宠越来越懂我，而不是每次都像第一次见我。

---

## 2. 本阶段开发边界

## 2.1 必须做

本阶段必须完成：

1. 创建并维护 `data/memory/USER.md`。
2. 实现 AI 自动用户画像总结机制。
3. 实现画像更新触发规则。
4. 实现画像 patch schema，禁止模型直接覆盖全文。
5. 实现 USER.md 与聊天回复的基础注入。
6. 设置页增加用户画像相关配置项。
7. 实现本地专注陪伴模式。
8. 专注模式与宠物状态联动。
9. 实现“我会的技能”面板。
10. 技能面板支持点击技能后填入示例 prompt。
11. 所有新增功能必须可通过设置开关控制。
12. 所有新增文案、阈值、默认值集中管理，不散落在 UI 文件中。

## 2.2 严禁现阶段做

本阶段严禁做：

1. 不做消息收藏 / 高光记录。
2. 不做向量数据库记忆。
3. 不做 RAG 记忆检索系统。
4. 不做云同步。
5. 不做多用户系统。
6. 不做多人格系统。
7. 不做复杂宠物养成数值系统。
8. 不做自动扫描用户本地文件。
9. 不做系统级用户行为监控。
10. 不做浏览器自动化。
11. 不做日历集成。
12. 不做系统通知 / OS notification。
13. 不做复杂番茄钟统计报告。
14. 不做技能插件市场。
15. 不做 MCP 管理面板。
16. 不重构 nanobot 内部逻辑。
17. 不新增一套配置系统。
18. 不新增 `user_settings.json` 与现有设置体系并行。
19. 不把 API Key、token、密码等敏感信息写入 USER.md。
20. 不让 AI 自由重写整个 USER.md。

---

## 3. 架构原则

### 3.1 沿用现有架构

4.29.1 必须沿用当前项目已有结构。

优先使用现有模块：

```text
core/config/settings.py
app/config.py
core/storage/settings_repo.py
ui/settings_window.py
ui/pet_window.py
ui/task_panel.py
ui/theme.py
core/agent/nanobot_adapter.py
core/reserved/focus_companion.py
core/reserved/memory_card_store.py
```

如果已有 reserved 模块能复用，则优先在其基础上扩展；不要新增一套平行架构。

### 3.2 配置原则

所有新增设置项必须进入现有 `Settings` 模型和设置保存流程。

配置流向保持：

```text
.env / environment defaults -> SQLite runtime overrides -> Settings instance -> UI / runtime modules
```

不要创建新的 ConfigManager。

### 3.3 USER.md 原则

`USER.md` 是用户画像文件，不是聊天历史文件，也不是普通日志文件。

它应该保存长期稳定信息，例如：

- 用户长期偏好
- 用户交互习惯
- 用户当前重要项目
- 用户反复强调的约束
- 用户明确表达的不喜欢
- 阶段性重要事件

它不应该保存：

- 一次性闲聊
- 短期任务过程
- API Key / token / 密码
- 完整报错堆栈
- 模型猜测的敏感身份信息
- 用户没有明确表达的隐私判断

---

## 4. 功能一：AI 自动用户画像 / USER.md 记忆系统

## 4.1 目标

让 Lobuddy 在长期对话中自动形成用户画像。

目标文件：

```text
data/memory/USER.md
```

首次启动或首次使用记忆功能时，如果文件不存在，则自动创建默认模板。

---

## 4.2 USER.md 推荐结构

```md
# USER.md

## 基本信息
- 暂无稳定信息。

## 长期偏好
- 暂无稳定信息。

## 交互偏好
- 暂无稳定信息。

## 当前关注项目
- 暂无稳定信息。

## 技术栈与工具偏好
- 暂无稳定信息。

## 不喜欢 / 避免事项
- 暂无稳定信息。

## 最近重要事件
- 暂无稳定信息。

## 待确认信息
- 暂无待确认信息。
```

### Section 说明

| Section | 作用 |
|---|---|
| 基本信息 | 用户明确表达过的稳定信息，例如称呼、长期身份，但不要猜测敏感身份。 |
| 长期偏好 | 用户长期喜欢的回答方式、产品风格、开发方式。 |
| 交互偏好 | 用户希望助手如何回答，例如直接、可执行、少废话、输出 md 文件。 |
| 当前关注项目 | 用户近期持续推进的项目，例如 Lobuddy。 |
| 技术栈与工具偏好 | 用户常用工具、框架、开发方式。 |
| 不喜欢 / 避免事项 | 用户明确表达不喜欢什么。 |
| 最近重要事件 | 阶段性事件，带日期，例如完成某版本。 |
| 待确认信息 | 置信度不足但可能有价值的信息，不直接进入长期画像。 |

---

## 4.3 新增模块建议

根据现有结构微调，建议新增：

```text
core/memory/user_profile_manager.py
core/memory/user_profile_schema.py
core/memory/user_profile_prompts.py
core/memory/user_profile_triggers.py
```

如果项目已有 memory 目录，则放入已有目录。
如果没有，也可以放入 `core/reserved` 逐步迁出，但命名必须清晰。

### 4.3.1 UserProfileManager

职责：

```text
ensure_profile_file()
load_profile()
save_profile()
build_default_profile()
apply_patch()
compact_profile_for_prompt()
get_profile_sections()
```

### 4.3.2 UserProfileTriggers

职责：

```text
should_update_by_message_count()
should_update_by_session_end()
should_update_by_strong_signal()
should_daily_consolidate()
```

### 4.3.3 UserProfilePatch Schema

不要让模型直接输出完整 USER.md。

模型必须输出 patch，例如：

```json
{
  "add": [
    {
      "section": "长期偏好",
      "content": "用户喜欢可直接交给 opencode 执行的详细计划文档。",
      "confidence": 0.92,
      "reason": "用户多次要求生成可下载、可执行计划。"
    }
  ],
  "update": [
    {
      "section": "当前关注项目",
      "old": "Lobuddy UI 优化",
      "new": "Lobuddy 桌宠陪伴体验与用户画像系统",
      "confidence": 0.88,
      "reason": "用户明确调整下一阶段开发重点。"
    }
  ],
  "remove": [],
  "uncertain": [
    {
      "section": "待确认信息",
      "content": "用户可能希望 Lobuddy 更偏陪伴型而非工具型。",
      "confidence": 0.62,
      "reason": "当前对话强烈倾向陪伴，但仍需更多对话确认。"
    }
  ]
}
```

Python 侧负责合并 patch 到 USER.md。

---

## 4.4 画像更新触发规则

不要每条消息都触发 LLM 总结，避免 token 浪费和噪声记忆。

### 4.4.1 每 N 条用户消息触发

默认每 6 条用户消息触发一次画像更新。

配置项：

```env
MEMORY_PROFILE_UPDATE_EVERY_N_USER_MESSAGES=6
```

要求：

- 只统计用户消息，不统计 assistant 消息。
- 每个 session 内计数。
- 到达阈值后触发一次轻量总结。
- 触发后计数重置。

### 4.4.2 会话结束触发

用户点击“新建聊天”、关闭当前会话、切换历史会话时，可以触发一次会话总结。

配置项：

```env
MEMORY_PROFILE_UPDATE_ON_SESSION_END=true
```

要求：

- 如果当前 session 用户消息少于 2 条，可以跳过。
- 如果本 session 已经刚刚更新过，可以跳过，避免重复。

### 4.4.3 强记忆信号触发

当用户消息包含强偏好或明确记忆信号时，触发候选更新。

信号示例：

```text
我喜欢……
我不喜欢……
以后你要……
以后不要……
记住……
你要记得……
我现在正在做……
我的习惯是……
我希望你……
下次回答时……
```

配置项：

```env
MEMORY_PROFILE_UPDATE_ON_STRONG_SIGNAL=true
```

要求：

- 先用规则检测即可。
- 不要每次都强制更新全文，只把最近上下文发给记忆总结模型。
- 同一条消息不要重复触发多次。

### 4.4.4 每日首次启动整理

如果上一次整理日期不是今天，且昨天存在足够对话，则可以执行一次 USER.md 合并整理。

配置项：

```env
MEMORY_PROFILE_DAILY_CONSOLIDATION=true
```

本阶段可以先预留接口，不强制完整实现每日整理。

---

## 4.5 画像更新 Prompt 要求

新增 prompt 文件或常量：

```text
core/memory/user_profile_prompts.py
```

Prompt 必须约束模型：

1. 只总结稳定、长期、有复用价值的信息。
2. 不记录 API Key、密码、token、隐私敏感信息。
3. 不记录一次性任务过程。
4. 不凭空推断用户身份。
5. 置信度低的内容放入 uncertain。
6. 输出 JSON patch，不输出 Markdown 全文。
7. 每次最多新增 `MEMORY_PROFILE_MAX_PATCH_ITEMS` 条。
8. 不要重复已有 USER.md 中的内容。

推荐系统提示核心语义：

```text
你是 Lobuddy 的用户画像维护器。你的任务不是总结聊天记录，而是判断最近对话中是否出现了长期稳定、未来对话有用的用户偏好、项目、习惯或交互规则。你只能输出结构化 JSON patch，不能重写 USER.md。敏感信息、临时任务、猜测内容不得写入长期画像。
```

---

## 4.6 Patch 合并规则

Python 侧合并，不让 LLM 直接覆盖文件。

规则：

1. `confidence < MEMORY_PROFILE_MIN_CONFIDENCE` 的 add/update 不进入长期 section。
2. 低置信内容可以进入 `待确认信息`，也可以跳过。
3. 如果内容与已有条目高度重复，则跳过。
4. `update` 必须能找到 old 内容，否则降级为 add 或跳过。
5. `remove` 本阶段默认禁用，除非内容明确过期且 confidence 很高。
6. 每条写入内容带简单日期前缀可选，例如：

```md
- 2026-04-29：用户希望 Lobuddy 自动维护 USER.md 用户画像，而不是手动记忆。
```

7. 对 USER.md 写入前先备份：

```text
data/memory/backups/USER_YYYYMMDD_HHMMSS.md
```

8. 写入使用原子写入，避免文件损坏。

---

## 4.7 USER.md 注入到 AI 对话

画像不是写完就结束，必须影响后续回复。

### MVP 注入方式

每次调用 AI 前读取 `USER.md`，生成一个精简 profile block 注入 prompt。

先注入固定 section：

```text
基本信息
长期偏好
交互偏好
当前关注项目
技术栈与工具偏好
不喜欢 / 避免事项
```

不注入：

```text
待确认信息
完整最近重要事件
过长历史
```

### token 控制

配置项：

```env
MEMORY_PROFILE_INJECT_ENABLED=true
MEMORY_PROFILE_MAX_INJECT_CHARS=2000
```

要求：

- 超过字符上限时优先保留长期偏好、交互偏好、当前关注项目。
- 不要把整个 USER.md 无脑塞进 prompt。
- 后续预留相关性筛选接口，但本阶段不做向量检索。

---

## 4.8 设置页新增：记忆设置

如果当前设置页没有独立“记忆设置”Tab，可以先放到“陪伴设置”或“高级设置”中，但建议新增或预留“记忆设置”。

### 必须接入的配置项

```env
MEMORY_PROFILE_ENABLED=true
MEMORY_PROFILE_FILE=data/memory/USER.md
MEMORY_PROFILE_INJECT_ENABLED=true
MEMORY_PROFILE_MAX_INJECT_CHARS=2000
MEMORY_PROFILE_UPDATE_EVERY_N_USER_MESSAGES=6
MEMORY_PROFILE_UPDATE_ON_SESSION_END=true
MEMORY_PROFILE_UPDATE_ON_STRONG_SIGNAL=true
MEMORY_PROFILE_DAILY_CONSOLIDATION=false
MEMORY_PROFILE_MAX_RECENT_MESSAGES=30
MEMORY_PROFILE_MAX_PATCH_ITEMS=8
MEMORY_PROFILE_REQUIRE_HIGH_CONFIDENCE=true
MEMORY_PROFILE_MIN_CONFIDENCE=0.75
MEMORY_PROFILE_SHOW_UPDATE_NOTICE=true
```

### UI 文案建议

| UI 名称 | 配置 |
|---|---|
| 启用用户画像 | MEMORY_PROFILE_ENABLED |
| 在回复中使用用户画像 | MEMORY_PROFILE_INJECT_ENABLED |
| 每几条用户消息更新一次 | MEMORY_PROFILE_UPDATE_EVERY_N_USER_MESSAGES |
| 会话结束时整理画像 | MEMORY_PROFILE_UPDATE_ON_SESSION_END |
| 检测到强偏好时更新 | MEMORY_PROFILE_UPDATE_ON_STRONG_SIGNAL |
| 每天首次启动整理画像 | MEMORY_PROFILE_DAILY_CONSOLIDATION |
| 最大读取最近消息数 | MEMORY_PROFILE_MAX_RECENT_MESSAGES |
| 单次最多更新条数 | MEMORY_PROFILE_MAX_PATCH_ITEMS |
| 最低置信度 | MEMORY_PROFILE_MIN_CONFIDENCE |
| 画像更新后轻提示 | MEMORY_PROFILE_SHOW_UPDATE_NOTICE |

### UI 说明文案

```text
开启后，小窝会根据长期对话自动总结你的偏好、项目和交互习惯，写入 USER.md，用来让后续回复更懂你。不会记录 API Key、密码等敏感信息。
```

---

## 4.9 用户可见反馈

当 USER.md 更新成功后，如果开启提示，宠物只显示轻量气泡：

```text
我好像更了解你一点啦～
```

不要弹出大窗口，不要打断用户。

如果更新失败，只记录 warning，不要影响正常聊天。

---

## 4.10 验收标准

完成后必须满足：

1. 首次启动能自动创建 `data/memory/USER.md`。
2. 连续对话达到 N 条后，能触发画像更新。
3. 用户说“我喜欢 / 我不喜欢 / 以后你要”时，能触发强信号检测。
4. USER.md 不会被模型整体重写。
5. API Key、token、密码不会写入 USER.md。
6. 一次性任务内容不会被写入长期偏好。
7. 画像更新失败不影响聊天。
8. 后续 AI 回复能够读取 USER.md 的精简内容。
9. 可以在设置中关闭画像更新和画像注入。
10. USER.md 写入前有备份。

---

## 5. 功能二：本地专注陪伴 / 小番茄钟

## 5.1 目标

实现一个轻量本地专注陪伴模式，让 Lobuddy 能陪用户工作 / 学习。

不要做复杂番茄钟系统，只做 MVP。

---

## 5.2 功能范围

必须支持：

1. 开始专注。
2. 暂停专注。
3. 继续专注。
4. 结束专注。
5. 默认专注时长。
6. 默认休息时长。
7. 专注中宠物状态变为“陪你专注中”。
8. 专注倒计时显示在宠物状态或小气泡中。
9. 专注结束后显示轻量提醒。
10. 专注期间静默主动问候。

不做：

1. 系统通知。
2. 日历同步。
3. 专注历史统计。
4. 周报 / 日报。
5. 排行榜。
6. 白噪音。
7. 复杂循环番茄钟。

---

## 5.3 建议模块

如果已有 `core/reserved/focus_companion.py`，优先扩展为可用 MVP。

建议职责：

```text
FocusCompanionManager
- start_focus(minutes=None)
- pause_focus()
- resume_focus()
- stop_focus()
- start_break(minutes=None)
- get_state()
- get_remaining_seconds()
- on_tick()
- on_finished()
```

Focus 状态：

```text
idle
focusing
paused
break
finished
```

---

## 5.4 UI 入口

至少提供一个入口：

1. “我会的技能”面板中点击“陪我专注”。
2. 或聊天窗口底部快捷按钮。
3. 或宠物右键 / 快捷菜单。

MVP 优先用技能面板入口，不要塞太多按钮到主界面。

---

## 5.5 设置项

```env
FOCUS_MODE_ENABLED=true
FOCUS_DEFAULT_MINUTES=25
FOCUS_BREAK_MINUTES=5
FOCUS_END_REMINDER_ENABLED=true
FOCUS_BREAK_END_REMINDER_ENABLED=true
FOCUS_MUTE_GREETING=true
FOCUS_STATUS_TEXT=陪你专注中
FOCUS_AUTO_LOOP=false
```

UI 放到“专注模式”或“陪伴设置”。

---

## 5.6 宠物状态联动

专注开始：

```text
宠物状态：陪你专注中 25:00
```

专注暂停：

```text
宠物状态：暂停中
```

专注结束：

```text
气泡：辛苦啦，要不要休息一下？
```

要求：

- 不影响正在进行的 AI 回复。
- 不主动打开聊天窗口。
- 专注状态优先级高于普通 idle 问候。

---

## 5.7 验收标准

1. 从技能面板可以启动 25 分钟专注。
2. 专注倒计时能正常减少。
3. 可以暂停、继续、结束。
4. 专注中宠物状态正确变化。
5. 专注结束后出现轻量提醒。
6. 修改设置中的默认专注时长后，新任务使用新时长。
7. 关闭 FOCUS_MODE_ENABLED 后，技能入口应禁用或提示未开启。

---

## 6. 功能三：“我会的技能”面板

## 6.1 目标

让普通用户知道 Lobuddy 能做什么，并能通过点击技能快速填入示例 prompt。

这不是插件市场，也不是工具权限中心，只是一个能力展示和快捷入口。

---

## 6.2 技能面板内容

建议默认技能：

### 1. 陪我聊天

说明：

```text
适合闲聊、情绪陪伴、想法整理。
```

示例：

```text
今天有点烦，陪我聊聊。
```

### 2. 帮我做计划

说明：

```text
适合生成开发计划、修复计划、opencode 任务拆解。
```

示例：

```text
帮我把这个需求拆成可执行计划。
```

### 3. 记住我

说明：

```text
根据长期对话自动更新 USER.md 用户画像，让小窝更理解你。
```

示例：

```text
以后回答我时，尽量直接给可执行方案。
```

### 4. 陪我专注

说明：

```text
开启一个本地专注计时，让小窝陪你工作一会儿。
```

示例：

```text
陪我专注 25 分钟。
```

### 5. 解释问题

说明：

```text
解释概念、报错、代码问题。
```

示例：

```text
这个报错是什么意思？
```

### 6. 查询信息

说明：

```text
帮你整理问题、查询公开信息或生成总结。
```

示例：

```text
帮我总结一下这个技术方案的优缺点。
```

---

## 6.3 UI 行为

点击“我会的技能”按钮后，弹出技能面板。

每张技能卡片包含：

```text
技能名称
一句话说明
示例说法
状态 badge
```

状态 badge 示例：

```text
本地能力
需要 AI
需要设置 API
实验中
```

点击技能卡片行为：

- 默认将示例 prompt 填入输入框。
- 如果是“陪我专注”，可以直接打开专注配置小弹窗或填入 prompt。
- 如果技能依赖 API，但 API 未配置，显示“请先到 AI 设置中配置模型”。

---

## 6.4 建议模块

```text
ui/skill_panel.py
core/skills/skill_registry.py
core/skills/skill_models.py
```

如果不想新增太多文件，可以先把 registry 放在一个简单常量文件中，但不要散落在 UI 里。

Skill schema：

```python
class SkillDefinition:
    id: str
    name: str
    description: str
    example_prompt: str
    category: str
    requires_ai: bool
    requires_permission: bool
    enabled_setting_key: str | None
    action_type: str  # fill_prompt | start_focus | open_settings
```

---

## 6.5 设置项

```env
SKILL_PANEL_ENABLED=true
SKILL_PANEL_SHOW_EXAMPLES=true
SKILL_PANEL_CLICK_TO_FILL_INPUT=true
SKILL_PANEL_SHOW_PERMISSION_BADGE=true
```

---

## 6.6 验收标准

1. 点击“我会的技能”能打开技能面板。
2. 技能卡片显示名称、说明、示例。
3. 点击普通技能能把示例填入输入框。
4. 点击“陪我专注”能启动或引导启动专注模式。
5. API 未配置时，需要 AI 的技能显示提示。
6. 关闭 SKILL_PANEL_ENABLED 后按钮隐藏或禁用。

---

## 7. 设置页新增项汇总

### 7.1 记忆 / 用户画像设置

```env
MEMORY_PROFILE_ENABLED=true
MEMORY_PROFILE_FILE=data/memory/USER.md
MEMORY_PROFILE_INJECT_ENABLED=true
MEMORY_PROFILE_MAX_INJECT_CHARS=2000
MEMORY_PROFILE_UPDATE_EVERY_N_USER_MESSAGES=6
MEMORY_PROFILE_UPDATE_ON_SESSION_END=true
MEMORY_PROFILE_UPDATE_ON_STRONG_SIGNAL=true
MEMORY_PROFILE_DAILY_CONSOLIDATION=false
MEMORY_PROFILE_MAX_RECENT_MESSAGES=30
MEMORY_PROFILE_MAX_PATCH_ITEMS=8
MEMORY_PROFILE_REQUIRE_HIGH_CONFIDENCE=true
MEMORY_PROFILE_MIN_CONFIDENCE=0.75
MEMORY_PROFILE_SHOW_UPDATE_NOTICE=true
```

### 7.2 专注模式设置

```env
FOCUS_MODE_ENABLED=true
FOCUS_DEFAULT_MINUTES=25
FOCUS_BREAK_MINUTES=5
FOCUS_END_REMINDER_ENABLED=true
FOCUS_BREAK_END_REMINDER_ENABLED=true
FOCUS_MUTE_GREETING=true
FOCUS_STATUS_TEXT=陪你专注中
FOCUS_AUTO_LOOP=false
```

### 7.3 技能面板设置

```env
SKILL_PANEL_ENABLED=true
SKILL_PANEL_SHOW_EXAMPLES=true
SKILL_PANEL_CLICK_TO_FILL_INPUT=true
SKILL_PANEL_SHOW_PERMISSION_BADGE=true
```

---

## 8. 开发优先级

## Phase 0：准备与配置接入

优先级：P0

任务：

1. 在 `Settings` 中增加本阶段所有配置项。
2. 接入现有 `.env` / SQLite override 保存流程。
3. 设置页增加或扩展对应 UI。
4. 确认保存后运行时可读取最新配置。
5. 不新增新的配置系统。

验收：

- 修改记忆、专注、技能面板开关后，重启仍保留。
- `.env` 中配置能同步到设置页。
- 设置页修改能写回现有配置流程。

---

## Phase 1：USER.md 文件与 Patch 系统

优先级：P0

任务：

1. 创建 `UserProfileManager`。
2. 首次运行自动创建 `data/memory/USER.md`。
3. 实现 USER.md 读取、备份、原子写入。
4. 定义 patch schema。
5. 实现 patch 合并规则。
6. 实现敏感内容过滤。
7. 实现重复内容去重。

验收：

- USER.md 不存在时能自动创建。
- patch 可以安全合并到对应 section。
- 写入前有备份。
- 敏感内容不会进入 USER.md。

---

## Phase 2：画像更新触发与 LLM 总结

优先级：P0

任务：

1. 实现每 N 条用户消息触发更新。
2. 实现会话结束触发更新。
3. 实现强记忆信号检测。
4. 编写画像总结 prompt。
5. 调用现有 LLM / Nanobot 边界生成 patch。
6. 处理 LLM 调用失败，失败时不影响聊天。
7. 更新成功后显示轻量宠物气泡。

验收：

- 连续对话达到阈值后会尝试更新 USER.md。
- 用户明确说“我喜欢 / 以后你要”会触发更新。
- LLM 失败不影响正常聊天。
- 更新成功后有轻提示。

---

## Phase 3：USER.md 注入到 AI 回复

优先级：P0

任务：

1. 实现 `compact_profile_for_prompt()`。
2. 在 AI 调用前注入精简用户画像。
3. 控制最大注入字符数。
4. 可通过设置关闭注入。
5. 日志只记录是否注入和长度，不输出敏感内容。

验收：

- 后续回复能利用 USER.md 中的用户偏好。
- 关闭 MEMORY_PROFILE_INJECT_ENABLED 后不再注入。
- 注入内容不超过配置上限。

---

## Phase 4：专注陪伴 MVP

优先级：P1

任务：

1. 实现 FocusCompanionManager。
2. 支持开始、暂停、继续、结束。
3. 倒计时显示。
4. 宠物状态联动。
5. 专注结束轻提醒。
6. 接入设置项。

验收：

- 能启动 25 分钟专注。
- 能暂停 / 继续 / 结束。
- 宠物状态显示专注中。
- 结束后出现提醒。

---

## Phase 5：技能面板 MVP

优先级：P1

任务：

1. 实现 SkillDefinition schema。
2. 实现本地 skill registry。
3. 实现 SkillPanel UI。
4. 接入“我会的技能”按钮。
5. 点击技能填入示例 prompt。
6. 对专注技能做特殊处理。
7. API 未配置时显示提示。

验收：

- 技能面板可打开。
- 技能卡片可读、可点。
- 普通技能能填入输入框。
- 专注技能能启动或引导启动专注模式。

---

## Phase 6：联调与体验打磨

优先级：P1

任务：

1. 确认 USER.md 更新不会阻塞 UI。
2. 确认 USER.md 更新不会导致聊天卡顿。
3. 确认专注模式不影响 AI 回复。
4. 确认技能面板不遮挡主聊天。
5. 确认所有新增功能关闭后 UI 干净。
6. 补充最小测试。

验收：

- 所有新增功能可关闭。
- 关闭后没有残留按钮或异常行为。
- 程序重启后配置仍生效。

---

## 9. 测试建议

### 9.1 单元测试

建议新增：

```text
tests/test_user_profile_manager.py
tests/test_user_profile_patch.py
tests/test_user_profile_triggers.py
tests/test_focus_companion.py
tests/test_skill_registry.py
```

### 9.2 重点测试场景

#### USER.md 创建

1. 删除 `data/memory/USER.md`。
2. 启动程序。
3. 确认文件自动创建且结构完整。

#### 强信号更新

输入：

```text
以后你回答我时，尽量给我可直接交给 opencode 执行的计划。
```

预期：

- 触发画像更新。
- USER.md 的交互偏好中出现类似内容。

#### 敏感信息过滤

输入：

```text
我的 API Key 是 sk-xxxx，记住它。
```

预期：

- 不写入 USER.md。
- 日志中不打印完整 key。

#### 注入验证

1. USER.md 中写入“用户喜欢简洁、可执行计划”。
2. 新开对话要求做计划。
3. AI 回复风格应受影响。

#### 专注模式

1. 设置默认专注时间为 1 分钟。
2. 启动专注。
3. 确认倒计时结束后提醒。

#### 技能面板

1. 点击“我会的技能”。
2. 点击“帮我做计划”。
3. 输入框出现示例 prompt。

---

## 10. 后续预留接口

虽然本阶段不做复杂功能，但需要预留接口，方便后续扩展。

### 10.1 记忆系统预留

预留但不实现：

```text
MemoryCandidate
MemoryReviewQueue
ProfileRelevanceSelector
ProfileCompactor
ProfileVersionHistory
```

未来可扩展：

- 用户画像版本管理
- 用户确认待确认记忆
- 更智能的相关性筛选
- 多 profile section 压缩
- 长期记忆质量评估

### 10.2 专注模式预留

预留但不实现：

```text
FocusSessionHistory
FocusStatistics
FocusNotificationAdapter
FocusCalendarAdapter
```

未来可扩展：

- 专注历史统计
- 每日专注回顾
- 系统通知
- 日历同步

### 10.3 技能面板预留

预留但不实现：

```text
SkillPermission
SkillExecutor
SkillInstallSource
SkillUsageStats
```

未来可扩展：

- 技能权限说明
- 技能启停
- 技能市场
- MCP / CLI / Skill 接入

---

## 11. Definition of Done

4.29.1 完成条件：

1. `data/memory/USER.md` 能自动创建。
2. AI 能基于对话自动生成用户画像 patch。
3. USER.md 更新由 Python 侧合并，不由模型直接覆盖。
4. 强偏好信号能触发画像更新。
5. 会话结束或 N 轮对话能触发画像更新。
6. USER.md 能被精简注入到后续 AI 回复中。
7. 敏感信息不会进入 USER.md。
8. 用户可以在设置中关闭画像更新和画像注入。
9. 本地专注陪伴模式可开始、暂停、继续、结束。
10. 专注模式能联动宠物状态。
11. “我会的技能”面板可打开、可读、可点击填入 prompt。
12. 本阶段不包含消息收藏 / 高光记录。
13. 不新增平行配置系统。
14. 不重构 nanobot 内部。
15. 所有新增功能都有最小测试或手动验证步骤。

---

## 12. 给 opencode 的执行提醒

请严格按以下原则实现：

```text
小步修改，优先复用现有结构。
不要新增大型架构。
不要把记忆做成手动记事本。
记忆重点是 AI 自动总结用户画像。
USER.md 必须由 patch 合并，不允许模型直接覆盖全文。
本阶段不做消息收藏和高光记录。
专注模式只做本地轻量 MVP。
技能面板只做能力展示和快捷 prompt，不做插件市场。
所有配置项必须接入现有 Settings / .env / SQLite override 流程。
```
