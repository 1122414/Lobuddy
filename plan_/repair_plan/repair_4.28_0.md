````md
# Lobuddy 当前 UI / 配置 / 历史 / API 调用 Bug 修复任务

## 背景

当前 Lobuddy 桌宠窗口已经可以启动，并且主聊天窗口、悬浮控制台、设置窗口、任务完成弹窗都能显示。但现在存在多个严重 Bug，会影响基础使用，需要优先修复。

请基于现有代码排查并修改，不要大改架构，不要重写 UI，只修复当前问题。修改后需要给出可验证的测试方式。

---

## Bug 1：点击历史按钮后弹出的 History 窗口全黑

### 复现步骤

1. 启动 Lobuddy。
2. 点击聊天窗口右上角的菜单 / 历史按钮。
3. 弹出一个标题为 `History` 的窗口。

### 当前现象

弹出的 History 窗口内容区域是全黑的，只能看到一个蓝色信息图标和一个空按钮区域，看不到任何历史会话列表，也看不到有效文本。

### 预期行为

点击历史按钮后，应该显示历史会话列表，例如：

- 会话标题
- 最近消息摘要
- 创建时间 / 更新时间
- 点击某条历史记录后能恢复对应会话

如果当前没有历史记录，也应该显示明确的空状态，例如：

> 暂无历史对话

而不是弹出黑框。

### 重点排查方向

请检查：

1. 历史窗口是否使用了 `QMessageBox` 或系统默认弹窗，导致被全局 QSS / 深色样式污染。
2. 是否存在文本颜色与背景色冲突，例如黑底黑字。
3. 历史数据是否没有正确传入窗口，导致只显示了空弹窗。
4. 是否应该改为自定义 `QDialog` / `QWidget`，避免系统 MessageBox 样式不可控。
5. 历史按钮当前到底绑定的是“打开历史列表”，还是只是弹出一个占位提示框。

### 修复要求

- 历史窗口不能再出现全黑不可读的问题。
- 即使没有历史记录，也要显示正常空状态。
- 历史列表 UI 要与当前 Lobuddy 橙色 / 奶油色风格保持一致。
- 不要使用不可控的系统 MessageBox 来展示复杂内容。

---

## Bug 2：点击设置图标后，设置窗口中的配置不会真正保存

### 复现步骤

1. 点击悬浮控制台或聊天窗口中的设置按钮。
2. 打开 `Lobuddy Settings`。
3. 修改以下任意配置：
   - Pet Name
   - LLM API Key
   - LLM Base URL
   - LLM Model
   - Task Timeout
   - Enable Shell Tool
4. 点击 Save。
5. 关闭程序后重新启动，或者再次打开设置窗口。

### 当前现象

设置看起来可以填写，但点击 Save 后并没有真正持久化。重新打开后配置可能恢复旧值，运行时也可能没有使用新配置。

### 预期行为

点击 Save 后：

1. 配置应写入统一配置文件或 `.env`。
2. 程序当前运行时的配置也应立即更新。
3. 再次打开设置窗口时，应展示刚刚保存的新值。
4. 重启程序后配置仍然存在。
5. API Key 不能被保存成掩码字符，例如 `••••••••`。

### 重点排查方向

请检查：

1. Save 按钮是否真的绑定了保存函数。
2. 保存函数是否只是关闭窗口，没有写入配置。
3. 当前项目配置来源是否混乱：`.env`、环境变量、内存 config、settings dialog 是否读取了不同来源。
4. API Key 输入框如果显示为密码模式，保存时是否错误读取到了掩码值。
5. 修改后的配置是否同步到 LLM client，而不是只有 UI 里变了。

### 修复要求

- 建立一个统一的配置读写入口，例如 `ConfigManager`。
- 设置窗口只通过统一配置入口读取和保存。
- Save 后立即刷新运行时配置。
- API Key 保存时必须保存真实值，不允许保存 `******`、`••••••`、空字符串。
- 如果用户没有修改 API Key，则保留原 API Key，不要覆盖为空。
- 保存成功后给出明确提示。
- 保存失败时给出错误提示和日志。

---

## Bug 3：每次移动悬浮控制台都会在终端刷屏报错

### 复现步骤

1. 启动 Lobuddy。
2. 拖动桌宠或悬浮控制台。
3. 查看终端输出。

### 当前现象

每次移动窗口都会大量输出：

```txt
UpdateLayeredWindowIndirect failed for ptDst=(...), size=(140x180), dirty=(180x220 -20, -16) (参数错误。)
```
````

这会导致终端刷屏，影响调试，也说明当前透明窗口 / 分层窗口刷新区域存在问题。

### 预期行为

移动桌宠或控制台时不应该持续报错。终端不应刷屏。

### 重点排查方向

请检查 PySide6 / Qt 透明窗口相关代码：

1. 是否使用了：
   - `Qt.FramelessWindowHint`
   - `Qt.Tool`
   - `Qt.WindowStaysOnTopHint`
   - `Qt.WA_TranslucentBackground`
   - layered window / mask / shadow
2. 是否存在窗口尺寸和绘制区域不一致：
   - 窗口 size 是 `140x180`
   - dirty rect 却是 `180x220 -20, -16`
   - dirty 区域出现负坐标，可能导致 Windows API 参数错误
3. 是否在 `paintEvent` 中绘制了超出 widget 边界的阴影、圆角或外边距。
4. 是否使用了过大的 drop shadow / blur radius，导致 dirty region 超出实际窗口。
5. 是否可以通过调整 widget margin、固定尺寸、绘制区域、阴影容器来避免负坐标。
6. 是否需要在 Windows 下禁用某些透明窗口效果，或改为更稳定的绘制方式。

### 修复要求

- 拖动桌宠和悬浮控制台时不再刷 `UpdateLayeredWindowIndirect failed`。
- 不要简单粗暴地屏蔽所有日志。
- 如果确实是 Qt + Windows 透明窗口已知问题，也要通过调整窗口尺寸、绘制区域或阴影实现来解决。
- 保留当前悬浮窗的透明 / 圆角 / 置顶体验。

---

## Bug 4：历史对话不见了

### 复现步骤

1. 使用 Lobuddy 进行一次聊天。
2. 完成一次任务或收到一次回复。
3. 关闭窗口或新建聊天。
4. 再次点击历史按钮查看历史记录。

### 当前现象

历史对话没有正常显示，之前的对话像是丢失了。点击历史按钮也没有可用历史列表。

### 预期行为

Lobuddy 应该持久化历史对话。至少需要支持：

1. 每次用户发送消息后保存用户消息。
2. 每次 Agent 回复后保存助手消息。
3. 每个会话有独立 session id。
4. 新建聊天不会覆盖旧聊天。
5. 历史窗口可以看到之前的会话。
6. 点击历史会话后可以恢复聊天内容。

### 重点排查方向

请检查：

1. 当前聊天消息是否只存在内存，没有写入本地。
2. 是否每次启动都创建了新 session，但没有加载旧 session。
3. 是否保存路径错误，例如写到了临时目录。
4. 是否新建聊天时覆盖了旧历史文件。
5. 是否历史列表读取逻辑和保存逻辑使用了不同目录。
6. 是否任务完成弹窗中的结果没有进入聊天历史。
7. 是否历史存储格式存在异常导致加载失败。

### 修复要求

- 明确历史数据保存位置，例如：

```txt
data/conversations/
  session_xxx.json
```

- 每个会话单独保存。
- 消息结构至少包含：

```json
{
  "role": "user | assistant | system",
  "content": "...",
  "timestamp": "...",
  "metadata": {}
}
```

- 历史窗口能读取这些会话。
- 如果历史文件损坏，不要导致整个历史窗口崩溃，应跳过坏文件并记录 warning。
- 新建聊天只创建新 session，不删除旧 session。

---

## Bug 5：明明已经提供了 API Key，但现在请求报错没有 API Key

### 复现步骤

1. `.env` 中已经配置过 API Key。
2. 设置窗口里也能看到 API Key 输入框中有内容。
3. 发送消息。
4. 请求失败。

### 当前现象

任务完成弹窗中显示：

```txt
Error: {
  "error": {
    "message": "You didn't provide an API key. You need to provide your API key in an Authorization header..."
  }
}
```

终端中也可以看到请求失败。说明实际发起 HTTP 请求时，Authorization header 没有带上 API Key。

### 预期行为

只要用户已经在 `.env` 或设置窗口中配置 API Key，请求 LLM API 时就必须带上：

```txt
Authorization: Bearer <API_KEY>
```

并且不应该因为打开设置窗口、保存设置、新建聊天、切换模型后丢失 API Key。

### 重点排查方向

请重点检查以下情况：

1. 设置窗口显示了 API Key，但实际 LLM client 初始化时没有读取到。
2. `.env` 中有 key，但代码读取的环境变量名称不一致，例如：
   - `OPENAI_API_KEY`
   - `LLM_API_KEY`
   - `DASHSCOPE_API_KEY`
   - `MOONSHOT_API_KEY`
3. 设置窗口保存时把 API Key 覆盖成了空字符串。
4. 设置窗口保存时把 API Key 覆盖成了掩码字符串。
5. LLM client 初始化早于配置加载，导致后续配置变化没有同步。
6. base_url 与 model / key 不匹配。
7. 当前配置中 `LLM Base URL` 是：

```txt
https://dashscope.aliyuncs.com/compatible-mode/v1
```

模型是：

```txt
kimi-k2.5
```

需要确认当前 provider、base_url、model、api_key 是否匹配。如果使用 DashScope 兼容模式，就应该使用 DashScope 对应的 API Key 和模型名；如果使用 Kimi/Moonshot，就应该使用对应的 base_url 和 API Key。

### 修复要求

- 统一 LLM 配置字段，例如：

```env
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
LLM_PROVIDER=
```

- 所有 LLM 请求必须从同一个配置对象读取。
- 发请求前必须校验：
  - API Key 非空
  - Base URL 非空
  - Model 非空
- 如果 API Key 缺失，应在 UI 中提示“请先配置 API Key”，不要真的发起请求。
- 日志中可以打印 API Key 是否存在，但不能打印完整 API Key。
- 例如只允许打印：

```txt
api_key_present=True
api_key_prefix=sk-****
```

- 禁止在日志中输出完整 API Key。

---

## 额外问题：任务弹窗显示为 Success，但实际内容是 API 错误

### 当前现象

截图中任务完成弹窗显示：

```txt
Task Complete
Success
+5 EXP
```

但是正文内容却是 API 请求错误：

```txt
You didn't provide an API key...
```

这说明任务状态判断有问题。即使 LLM API 返回错误，系统仍然把任务标记成了成功。

### 预期行为

如果 LLM 请求失败，任务状态应该是失败，而不是成功。

### 修复要求

- API 请求异常、HTTP 401、HTTP 403、HTTP 429、HTTP 500 等都不能标记为 Success。
- 任务完成状态应该区分：
  - success
  - failed
  - cancelled
  - timeout
- 只有真正拿到有效 assistant 回复时才允许加 EXP。
- 失败任务不应该加 EXP。
- 失败弹窗应显示明确错误原因，并提供“打开设置”按钮。

---

## 总体验收标准

修复后需要满足以下条件：

1. 点击历史按钮，不再出现全黑弹窗。
2. 历史窗口能正常显示历史会话或空状态。
3. 聊天记录可以持久化，重启后仍能查看。
4. 设置窗口点击 Save 后配置真实保存。
5. API Key 不会被保存成空值或掩码值。
6. LLM 请求会正确携带 Authorization header。
7. 如果 API Key 缺失，UI 提示用户配置，而不是直接请求。
8. 拖动桌宠 / 控制台时不再刷 `UpdateLayeredWindowIndirect failed`。
9. API 请求失败时，任务不能显示 Success，也不能加 EXP。
10. 修改后请补充最小测试：
    - 配置保存测试
    - 历史保存 / 加载测试
    - LLM 配置读取测试
    - 失败任务状态测试

---

## 开发约束

- 不要重写整个项目。
- 不要引入大型新框架。
- 不要破坏现有桌宠 UI、聊天窗口、悬浮控制台。
- 优先做小范围、可验证修复。
- 所有路径、环境变量名、默认配置要集中管理，不要散落在多个文件。
- 修复后请说明改了哪些文件，以及每个 Bug 如何验证。

```

重点提醒 opencode：**第 2、5、额外问题很可能是同一个根因**——设置保存逻辑把 API Key 弄丢了，或者 LLM client 没有从最新配置重新初始化。第 1、4 也可能是同一条历史链路的问题：历史数据没保存 / 没加载，最后弹了一个空的系统 MessageBox。
```
