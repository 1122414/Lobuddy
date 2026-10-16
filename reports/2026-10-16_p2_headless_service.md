# P2 无界面业务服务验收

日期：2026-10-16；阶段通过，后续 Electron、记忆技能注入、成长结算与语音尚未交付。

## 交付

领域 TaskQueue/TaskManager/FocusCompanion 不再导入 Qt。AgentResult/TaskAgent 为独立契约，旧 nanobot 通过默认延迟装配继续工作；旧 UI 使用 QtTaskEvents 和 QtFocusDriver 保留线程派发、倒计时。新入口 `python -m app.service` 使用 stdio JSON-RPC，Pydantic 校验请求，生成 `shared/desktop-protocol.ts`。SQLite 保存请求身份、引擎会话映射、任务状态和事件序号；前台/后台各一个串行队列，分别使用 DSH 会话。

| ID / 优先级 | 问题与证据 | 修复前行为 | 方案与预期 | 风险 | 状态 |
| --- | --- | --- | --- | --- | --- |
| H01 / P1 | 领域模块导入 QObject/Signal/QTimer（源码观察） | 无 Qt 环境无法加载队列和专注 | 同步领域事件，展示层保留 Qt 派发；服务可独立运行 | 遗留线程派发改变 / 兼容层保留 Qt 信号 | 通过 |
| H02 / P1 | processor 在异步入口内设置 running（代码推断） | 同时入队可能创建多个 processor | 入队检查已拥有的 processor；20 次并发入队只运行一个执行器 | 重复任务 / 队列关闭后拒绝新任务 | 通过 |
| H03 / P1 | 新界面刷新/进程重启需保持执行身份（设计要求） | 旧版无 stdio 执行账本 | 请求 ID 唯一约束、恢复中断态、不自动派发；不同轮次迟到文本丢弃 | 重复副作用 / 中断需用户明确恢复 | 通过 |
| H04 / P1 | 取消 SDK 的 to_thread 等待不会停止原生启动线程（代码推断） | 启动后可能遗留进程 | shield 记录启动任务，清理先等待启动返回再 close | 孤儿进程 / 退出可能等待 SDK 启动超时 | 故障注入通过 |
| H05 / P1 | 输出管道断开需使执行与审批关闭（设计要求） | 单独等输入不能及时发现输出失败 | 同时观察输入/输出任务；任一结束都清理；EOF 拒绝审批、取消执行 | 断连后副作用 / 故障按失败处理且不重试 | 通过 |
| B05 / P2 | 旧测试断言英文，生产提示已经中文（P0 观察） | 测试与现有行为不符 | 对齐“缺少 API Key”，保留失败状态和错误字段断言 | 错误提示测试失效 / 无生产行为修改 | 通过 |

## 验证

| ID | 检查 | 修复前结果 | 修复后期望 | 实际结果 | 状态 |
| --- | --- | --- | --- | --- | --- |
| H01/H03/H05 | `/tmp/lobuddy-headless-p2/bin/python scripts/smoke_headless_service.py` | 无新服务（观察） | 无 Qt/nanobot 的真实模型、审批、历史、重复请求、重启、EOF | DeepSeek deepseek-flash 全部通过；临时工作区写入受控 acceptance.txt | 通过 |
| H01/H02/H03/H04/B05 | 隔离临时 cwd 执行 headless_service、dsh_protocol、dsh_tools、task_manager_session、task_queue、focus_companion、task_status_persistence、repair_4_28、pet、shutdown_regression | H02/H04 原风险为预测；B05 失败为观察 | 领域兼容、安全与生命周期回归 | 75 passed，1 个既有 Pydantic 弃用警告 | 通过 |
| H03/H05 | `pytest -q tests/test_headless_service.py`（最后补入实际管道边界测试） | 原无用例（观察） | 非法 JSON、同 ID 重复/冲突、审批关闭拒绝、恢复不重放 | 7 passed；与上行合计覆盖 76 个不同用例 | 通过 |
| H01 | `python scripts/smoke_legacy_startup.py` | P0 可启动（观察） | 改造后真实 Qt 仍能启动并关闭 worker | 通过；无模型调用 | 通过 |
| H01–H05 | Ruff、Black、mypy --explicit-package-bases --follow-imports=silent | 新增文件无基线 | 17 个新建/重写 Python 文件通过 | 全部通过 | 通过 |
| H03 | `tsc --noEmit --strict --skipLibCheck --target es2023 shared/desktop-protocol.ts`；生成一致性测试 | 无协议类型（观察） | TS 类型可编译且未漂移 | 通过 | 通过 |
| H04/H05 | `npm test --prefix bridge/dsh` | P1 已通过 | 插件传输和生产构建无回归 | 3 passed；最初沙箱禁止 loopback，授权重跑通过 | 通过 |

静态检查集合：app/service.py、core/agent/contracts.py、core/events/hook.py、core/service/、core/storage/service_repo.py、core/tasks/task_queue.py、core/tasks/task_manager.py、core/focus/focus_companion.py、ui/domain_bridge.py、scripts/generate_desktop_protocol.py、scripts/smoke_headless_service.py、tests/test_headless_service.py、tests/test_dsh_protocol.py、core/agent/dsh/runtime.py。其余旧文件仅局部兼容改动，仓库整体静态债务仍见 P0 报告，不宣称全仓通过。

无 Qt 环境由独立临时 venv 实测，未安装 PySide6 或 nanobot，仅安装 SDK/runtime 与现有直接依赖。日志在 stderr；任务执行器仅记录异常类型，避免把上游诊断中的凭据输出。CI 已加入离线检查；未声称远端 CI 已运行。现阶段只开放 P1 两个已治理文件工具；其余工具与原业务能力按 P4/P5 继续迁移。
