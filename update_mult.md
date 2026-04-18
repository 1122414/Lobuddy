# Lobuddy 更新日志：主 Agent + 子 Agent 图片分析架构

**更新日期**：2026-04-12  
**更新范围**：主 Agent（kimi-2.5）+ 子 Agent（qwen 多模态）图片分析链路实现、任务会话归属修复、测试补齐与仓库清理  
**验证状态**：Oracle 最终审查通过 `<promise>VERIFIED</promise>`，44 项相关测试全部通过

---

## 1. 需求概述

用户原需求：
- 主 Agent 使用 `kimi-2.5`（纯文本模型）处理日常对话
- 用户上传图片时，主 Agent **自主判断**是否需要图片分析
- 如需分析，主 Agent 在程序运行时**动态调用子 Agent**（多模态模型，当前为 qwen）
- 子 Agent 的分析结果返回主 Agent，由其生成最终回答
- 子 Agent 的模型可通过 `.env` / Pydantic Settings 由用户自行配置

---

## 2. 新增模块

### 2.1 `core/agent/image_analyzer.py` — 图片分析子 Agent
- 使用 `httpx` 直接调用 OpenAI 兼容的多模态接口
- 支持独立配置 `llm_multimodal_base_url` / `llm_multimodal_api_key`（未配置时自动回退到主配置）
- 图片安全校验：
  - 大小限制：5MB（stat + read_bytes 双重检查，消除 TOCTOU）
  - 扩展名白名单：`.png`、`.jpg`、`.jpeg`、`.webp`、`.gif`、`.svg`
  - Magic bytes 校验 + SVG 内容中必须包含 `<svg` 标签
- 错误日志脱敏：仅记录 HTTP status code，不记录 response body；用户 facing 错误已完全脱敏

### 2.2 `core/agent/tools/analyze_image_tool.py` — nanobot 自定义工具
- 继承 `nanobot.agent.tools.base.Tool`
- `prompt` 参数必填，`path` 可选（默认使用上传图片路径）
- **路径安全校验**：拒绝与 `image_path` 不一致的 `path`，防止任意文件读取（Arbitrary File Read）
- `read_only=True`，并发安全

### 2.3 `tests/test_image_analysis_integration.py` — 端到端集成测试
- 使用真实临时 PNG 文件作为输入
- 通过 `patch.object(AgentRunner, "_request_model")` 模拟 LLM 行为：
  - 第一次调用返回 `analyze_image` 工具调用请求
  - nanobot 的 `ToolRegistry.execute()` **真实执行** `AnalyzeImageTool`
  - `ImageAnalyzer.analyze` 被 mock 以避免真实 HTTP 请求
  - 第二次调用验证 `messages` 中确实包含 `role="tool"` 且内容为子 Agent 结果
- 断言最终输出包含主 Agent 总结、工具调用记录、`call_count == 2`

---

## 3. 核心改动

### 3.1 `core/agent/nanobot_adapter.py` — 主 Agent 适配器
**关键修改**：
1. **移除直接 model-switch 逻辑**：主 Agent 始终固定使用 `llm_model`（kimi-2.5），不再因图片上传临时切模型
2. **动态注册 / 清理工具**：
   - 若配置了 `llm_multimodal_model`：在 `bot.run()` 前注册 `AnalyzeImageTool` 为 `analyze_image`，保存旧工具并在 `finally` 中恢复
   - 若未配置：向 session 注入临时 system message（告知当前无法分析图片），**不注册工具**
3. **临时 system message 管理**：
   - 运行前注入、运行后在 `finally` 中按 `(role, content)` 精确清理
   - 成功、异常、timeout 三种分支均有清理保障
4. **`_ToolTracker` 完整实现 `AgentHook` 合约**：补全 `wants_streaming`、`before_iteration`、`on_stream`、`on_stream_end`、`before_execute_tools`、`after_iteration`、`finalize_content` 方法，避免 `CompositeHook` 调用失败
5. **变量初始化防护**：`previous_tool` 与 `temp_system_msg` 在 `try` 块前初始化，杜绝 `UnboundLocalError`

### 3.2 `core/tasks/task_manager.py` — 任务生命周期与会话归属
- 新增 `_task_session_map: dict[str, str]`，保存 `task_id -> session_id` 映射
- `submit_task` 时写入映射；`_on_task_completed` 时弹出并随信号发出
- `task_completed` 信号签名更新为 `Signal(str, str, bool, str, str)`（新增 session_id）
- 解决用户在任务执行期间切换会话导致结果保存到错误会话的问题

### 3.3 `app/main.py` — UI 层事件订阅
- `on_task_completed` 现在接收并直接使用任务的原始 `session_id`
- 保存 assistant message 时不再依赖 `task_panel.current_session_id`
- 渲染更新增加条件判断：仅当 `session_id == task_panel.current_session_id` 时才立即渲染到当前面板

### 3.4 `app/config.py` — 配置扩展
新增字段：
```python
llm_multimodal_model: str = ""
llm_multimodal_base_url: str | None = None
llm_multimodal_api_key: str | None = None
```
- `llm_multimodal_model` 为空字符串时禁用图片分析工具
- 多模态 base_url / api_key 未配置时自动回退到主 LLM 配置
- 修复 `convert_to_path` validator：新增 `.expanduser()`，解决 `~` 路径无法正确展开的问题

### 3.5 `.env.example` — 示例更新
新增如下配置项示例：
```env
LLM_MULTIMODAL_MODEL=qwen3.5-omni-plus-2026-03-15
LLM_MULTIMODAL_BASE_URL=
LLM_MULTIMODAL_API_KEY=
```

---

## 4. 测试矩阵

### 4.1 新增测试文件
| 文件 | 用例数 | 覆盖范围 |
|------|--------|----------|
| `tests/test_image_analyzer.py` | 10 | 子 Agent 成功、缺失文件、超时、大小超限、扩展名拒绝、magic bytes 拒绝、假 SVG 拒绝、缺失模型、独立 endpoint/key 覆盖、脱敏错误 |
| `tests/test_analyze_image_tool.py` | 8 | 工具名/Schema、只读属性、正常委托、默认路径、path 省略、路径不匹配拒绝、无路径错误 |
| `tests/test_image_upload.py` | 12 | 主 Agent 无模型切换、缺失多模态配置降级、system message 注入与清理、工具注册/恢复/异常恢复、跨回合无残留、UnboundLocalError 防护、纯文本任务不注册工具 |
| `tests/test_task_manager_session.py` | 3 | 信号携带原始 session_id、会话切换保真、映射清理 |
| `tests/test_image_analysis_integration.py` | 1 | 主 Agent → Tool → 子 Agent → 回主 Agent 的完整端到端链路 |

### 4.2 修复的 pre-existing 失败
- `tests/test_nanobot_adapter.py::test_settings_validates_required_fields`：使用 `Settings(_env_file=None)` 避免本地 `.env` 污染
- `tests/test_nanobot_adapter.py::test_path_expansion`：`app/config.py` 的 `.expanduser()` 修复自然通过
- `tests/test_nanobot_adapter.py::test_health_check_with_invalid_config`：标记从 `@pytest.mark.asyncio` 改为 `@pytest.mark.anyio`，避免后端不兼容

### 4.3 其他测试修复
- 所有使用 `asyncio.get_event_loop().run_until_complete(coro)` 的 `run_async` 辅助函数统一改为 `asyncio.run(coro)`，解决 `asyncio.run` 关闭事件循环后再次调用 `get_event_loop` 报 `RuntimeError` 的问题
- `tests/test_analyze_image_tool.py` 与 `tests/test_task_manager_session.py` 在模块级 mock nanobot 后、导入目标模块前恢复真实模块，避免污染后续集成测试

---

## 5. Bug 修复与 Oracle 审查轮次

本功能历经 **5 轮 Oracle 审查** 与修复：

| 轮次 | 发现的问题 | 修复措施 |
|------|-----------|----------|
| 1 | `_ToolTracker` 未完整实现 `AgentHook`；`AnalyzeImageTool` `path` 必填；缺少多模态 endpoint 配置；未限制图片大小；测试覆盖不足 | 补全 Hook 方法、改 `path` 为可选、新增 `llm_multimodal_base_url/api_key`、加 5MB 限制、补充测试 |
| 2 | 临时 system message 仅在成功路径清理，异常/超时分支会污染会话历史 | 将清理移入 `finally` 块，覆盖所有退出路径 |
| 3 | `previous_tool` / `temp_system_msg` 在 `try` 内初始化导致 `UnboundLocalError` | 提前至 `try` 前初始化 |
| 4 | 任务完成时用 `task_panel.current_session_id` 导致用户切换会话后结果写错；HTTP 日志未完全脱敏；SVG 校验过松；未配多模态时硬拒绝 | 新增 `_task_session_map` 与信号携带 `session_id`；脱敏日志；要求 `<svg` 标签；未配置时降级提示 |
| 5（最终） | 端到端集成测试 `_inner()` 控制流错误导致被测代码未实际执行；`sys.modules` mock 污染 | 修正测试控制流；模块级 mock 导入后恢复真实模块 |

---

## 6. 运行验证

```bash
pytest tests/test_image_analysis_integration.py tests/test_image_upload.py tests/test_image_analyzer.py tests/test_analyze_image_tool.py tests/test_task_manager_session.py tests/test_nanobot_adapter.py
# 结果：44 passed, 0 failed

pytest tests/ -q
# 结果：61 passed, 0 failed
```

---

## 7. 仓库状态

- 工作区干净，无未提交文件
- 根目录误生成的 `package-lock.json` 已删除
- 所有变更已通过 `git commit` 提交

---

## 8. 待办（非阻断）

以下事项经 Oracle 确认不构成本次任务 BLOCKER：
- README 主文档中补充 `LLM_MULTIMODAL_*` 配置说明（当前 `.env.example` 已有）
- 整理 `pyproject.toml` 中不存在的 `asyncio_mode` 与 `asyncio_default_fixture_loop_scope` 选项，消除 pytest warnings

---

**总结**：本次更新完整实现了 Lobuddy 的「主 Agent（kimi-2.5）+ 子 Agent（可配置多模态）」图片分析架构，覆盖动态工具注册、结果回注、会话隔离、错误降级与完整测试验证，已通过 Oracle 最终验收。