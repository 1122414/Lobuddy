# Lobuddy 问题根因分析报告

**分析时间**: 2026-04-06

## 问题概述

用户报告了三个主要问题：
1. AI 记忆功能失效（记不住用户名字"小明"）
2. 文件读取错误（将"陈金保简历"误读为"新建简历"）
3. 搜索超时（搜索"洛克王国"时 120 秒超时）

---

## 问题一：AI 记忆功能失效

### 现象
- 用户说"你记住我是小明"，AI 回复"好的，小明！"
- 后续问"我是谁"，AI 回答"你是 Lobuddy"
- 说明对话历史没有被正确传递给 AI

### 根本原因

**代码位置**: `core/agent/nanobot_adapter.py` 第 138-147 行

```python
# 注入聊天历史到 nanobot 会话
if chat_history:
    session = bot._loop.sessions.get_or_create(session_key)
    # 只有会话为空时才注入（避免重复）
    if not session.messages:  # <-- 问题在这里
        for msg in chat_history:
            session.add_message(...)
```

**问题分析**:
1. Lobuddy 正确地从数据库收集了聊天历史
2. 但当 nanobot 已经存储了会话状态时（`session.messages` 不为空）
3. 我们的注入逻辑被跳过了
4. nanobot 使用的是它自己存储的过期会话，而不是我们从数据库加载的最新历史

**为什么之前修复没有解决**:
- 我们添加了 chat_history 传递流程，但注入条件太保守
- 只要 nanobot 内部有任何缓存，就跳过注入
- 导致数据库中的历史永远无法覆盖 nanobot 的内部缓存

### 解决方案
需要修改注入逻辑，强制用数据库的历史覆盖 nanobot 的会话：
```python
# 方案 A：总是先清空再注入
session = bot._loop.sessions.get_or_create(session_key)
session.messages.clear()  # 强制清空
for msg in chat_history:
    session.add_message(...)

# 方案 B：或者比较时间戳，用最新的
```

---

## 问题二：文件读取错误（幻觉）

### 现象
- 用户要求查看"简历文件夹"中的文件
- AI 列出："新建简历.pdf"、"新建简历_2025_11_23.pdf"
- 实际文件："陈金保简历.pdf"、"陈金保简历_2025_11_23.pdf"
- AI 将"陈金保"误读为"新建"

### 根本原因

**这不是 OCR 或视觉问题**。

nanobot 确实有真正的文件系统工具：
- `lib/nanobot/nanobot/agent/tools/filesystem.py` - `ListDirTool`, `ReadFileTool`
- 工具在 `AgentLoop._register_default_tools()` 中注册
- 模型通过 `tools.get_definitions()` 获取工具定义
- 工具调用通过 `ToolRegistry.execute()` 执行

**问题分析**:
1. 模型**没有实际调用** `list_dir` 工具
2. 或者工具调用失败了，模型"编造"了合理的文件名
3. 这是一个**工具使用失败**或**模型幻觉**问题，不是文件系统访问问题

**可能原因**:
1. 模型直接从训练数据推断回答，而不是使用工具
2. 工具调用失败（路径错误、权限问题、workspace 不匹配）
3. 工具输出没有正确返回到对话中

### 解决方案
需要检查运行时日志：
- 确认 `list_dir` 是否被实际调用
- 查看工具返回值是什么
- 检查是否有权限或路径问题

---

## 问题三：搜索超时（120秒）

### 现象
- 用户要求搜索"洛克王国"
- AI 回复："Task timed out" / "Task exceeded 120 seconds timeout"

### 根本原因

**超时配置位置**:
- `app/config.py` 第 39 行：`task_timeout=120`
- `core/agent/nanobot_adapter.py` 第 153-160 行：
  ```python
  result = await asyncio.wait_for(
      bot.run(...),
      timeout=self.settings.task_timeout  # 120秒
  )
  ```

**工具执行流程**:
1. `nanobot/agent/loop.py` - 构建 agent 循环，调用 `AgentRunner`
2. `nanobot/agent/runner.py` - 从模型获取工具调用，执行工具
3. `nanobot/agent/tools/search.py` - grep/glob 工具实现

**核心问题**:
1. nanobot 的搜索工具在异步方法中执行**同步**的文件系统遍历
   ```python
   # search.py 中的代码
   async def execute(self, ...):
       # 同步阻塞调用！
       for root, dirs, files in os.walk(...):
           ...
   ```
2. 搜索"洛克王国"可能触发大范围文件扫描
3. 没有**工具级别的超时**控制
4. 整个运行被 120 秒的外部超时杀死

**为什么搜索会慢**:
- `grep` 递归扫描整个工作区
- 如果没有早期匹配，会检查大量文件
- 同步的 `os.walk()` 阻塞事件循环
- 模型可能反复请求更多搜索

### 解决方案
1. **短期**：增加 `task_timeout` 到 300 秒或更长
2. **中期**：为每个工具调用添加独立超时
3. **长期**：将同步文件操作移到线程池 (`asyncio.to_thread`)

---

## 总结

| 问题 | 根本原因 | 修复难度 | 修复位置 |
|------|---------|---------|---------|
| 记忆失效 | nanobot 缓存优先于数据库历史 | 中 | `nanobot_adapter.py` |
| 文件误读 | 模型未调用工具或工具失败 | 高 | 需日志排查 |
| 搜索超时 | 同步文件扫描阻塞事件循环 | 中 | `search.py` + 配置 |

## 建议修复优先级

1. **立即修复记忆问题**（影响核心体验）
2. **调整超时设置**（缓解搜索问题）
3. **调查文件工具调用**（需要运行时日志）
4. **长期优化搜索性能**（将同步IO移到线程）
