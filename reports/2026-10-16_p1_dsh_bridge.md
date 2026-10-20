# P1：DSH 运行时与受控插件桥

日期：2026-10-16。分支：`codex/lobuddy-dsh-rebuild`。前置阶段：P0 `7a17791`。

## 交付范围

- Python 官方 SDK/runtime 精确固定 `0.1.5rc1`；插件公共类型精确固定 npm `0.1.5-rc.1`。运行前验证 Python 包版本，npm 锁文件和 overrides 阻止 peer 依赖混入其他预发布版。
- `core/agent/dsh/runtime.py` 管理官方 SDK 子进程、独立 0700 home、0600 启动配置与就绪文件。密钥仅经子进程环境传入，不写配置文件。SDK stdout 保持其协议专用。
- `bridge/dsh/` 是 TypeScript 插件。使用公开的 `ctx.agents.create/resume`、Agent followup/cancel/whenIdle、stream/session events 和 `ctx.tools.guard/register`，不改上游循环。
- 随机 loopback HTTP JSON-RPC + 单所有者 SSE；每次启动随机令牌；拒绝无认证、错误 Host、浏览器 Origin、冲突请求 ID；有请求大小、事件积压和请求缓存上限。
- 事件带 session/task/turn/sequence。只输出用户回答的文本增量与最终文本，不转发 reasoning；取消、失败、完成分开。最多一个前台轮次和一个后台轮次；连接丢失取消在途工作，不自动重启或重发。
- 关闭内置工具、自动目标驱动、独立技能发现、agent instructions、会话日志上传、遥测和插件清单上传。真实启动后实际工具目录仅包含 `lobuddy_read_file`、`lobuddy_write_file`。
- 工具效果在 Python 执行，经 Pydantic → 明确映射 → ToolPolicy → Guardrails → ExecutionBudget → HITL → 执行前存活检查。写入需要审批；审批 ID 不匹配、拒绝、超时、断连、取消均不执行。
- 首批文件工具仅限指定 workspace，拒绝凭据路径、越界、符号链接和硬链接；文件描述符逐级打开，审批后目录被替换成 symlink 也无法跟随。

本阶段只开放两项已验收工具。Shell、网络、图片、历史检索、本地打开、技能等仍在旧 UI/nanobot 可用；新链路在 P4/P5 逐项迁移后开放，不把未迁移工具标为完成。新桌面 UI 与真实审批弹层属于 P3，本次真实模型验收使用仅允许临时测试文件的审批实现。

## 问题与处理

| ID / 优先级 | 问题与证据 | 处理前行为 | 解决 / 预期 | 不修风险 / 回归风险 | 状态 |
| --- | --- | --- | --- | --- | --- |
| D01 / P1 | 固定 runtime 的 npm peer 范围实际解析到了 rc.3，npm 报 ERESOLVE | 固定顶层版本仍不足以保证 API 匹配 | 15 个 DSH 包同版 overrides + lock；仅类型依赖，插件运行时只导入 Node 内置模块 | API 漂移 / 升级须重跑兼容验证 | 已验证 |
| D02 / P1 | 默认 SDK 不能替代本产品的取消、治理和双向工具结果链路 | 无 Lobuddy 接入 | 专用插件和 Python 效果执行边界 | 工具绕过治理 / 新桥接协议风险 | 已验证基础闭环 |
| D03 / P1 | 断连、重发与恢复可能重复副作用（设计风险，非旧版实测缺陷） | 原无 DSH 链路 | 请求 ID 去重、已提交消息 ID 恢复去重、禁止旧 inbox 自动执行；不重试未知结果 | 重复写入 / 需用户明确发起恢复操作 | 实际进程故障验证通过 |
| B03 / P1 | macOS pathlib 将 Windows drive/backslash 当普通字符；P0 两个测试实测失败 | 跨平台逃逸语义判允许 | Windows drive 在 POSIX 拒绝；同时验证反斜杠路径解释；合法原生路径保留 | 后续适配器可能越界 / 少数含反斜杠路径更严格 | 已修复 |
| B04 / P2 | 两项 URL 单测依赖公网 DNS | 沙箱 DNS 失败导致合法 URL 断言失败 | 仅单测固定公网 DNS；生产 SSRF 校验不变 | 网络波动影响回归 / mock 不代表公网集成 | 已修复 |
| B06 / P1 | Windows ACL 失败测试未模拟 Windows 平台 | macOS 根本不进入 ACL 分支 | 局部模拟 os.name/getlogin 与 icacls 失败，保留删除临时文件断言 | 故障分支无验证 / 非真实 Windows 验收 | 故障注入通过 |
| D04 / P1 | 删除保护根目录解析异常时，旧实现 except-pass 继续判定 | 异常时可能漏掉保护目标（代码推断） | 保护根无法解析就拒绝删除；清除同文件重复声明并收敛异常类型 | 删除保护失效 / 环境异常时拒绝更多操作 | 新回归通过 |
| D05 / P2 | uv macOS 平台默认 13，runtime wheel 要求 macOS 14 | 交叉平台锁解析失败，实际本机安装成功 | 显式 MACOSX_DEPLOYMENT_TARGET=14.0；锁文件注明最低版本 | 错误安装预期 / macOS 13 不支持此 runtime | 已验证解析 |

## 验收记录

| ID | 检查 / 命令 | 变更前预期或观察 | 变更后期望 | 实际结果 | 状态 |
| --- | --- | --- | --- | --- | --- |
| D02/D03 | `python scripts/smoke_dsh_bridge.py` | 无新链路（观察） | 真实模型流式、拒绝、允许、取消、恢复 | DeepSeek `deepseek-flash` 实测全部通过；拒绝不生成文件，允许写入 hello | 通过 |
| D03 | 上述脚本：收到文本增量后取消 | 中途取消能力未接入（观察） | turn.cancelled，不误报 failed/completed | 通过 | 通过 |
| D03 | 上述脚本：审批等待时 SIGKILL 自己启动的 runtime，再恢复 | 重放风险为推断 | 旧请求不执行、原文件不变、新进程可恢复会话 | 通过；文件仍为 hello | 通过 |
| D02 | 上述脚本：检查实际工具目录及扫描临时 DSH home | 隔离保证待验证 | 只有两项受控工具，所有 home 文件不含凭据 | 通过；没有打印密钥 | 通过 |
| D02/D03 | `npm test --prefix bridge/dsh` | 无测试（观察） | 鉴权、Origin、私有文件、去重、SSE 断连通过 | 3 tests passed；含 tsc 生产构建 | 通过 |
| B03/B04/B06/D02/D03/D04 | pytest：dsh_tools、dsh_protocol、integration_phase1、tool_policy、temp_config_security、security_fixes | P0 相关 5 项失败为观察；新场景为预测 | 路径、审批/超时、取消、预算、symlink 替换、乱序/重复事件、无自动重试通过 | 103 passed，1 个既有 Pydantic 警告 | 通过 |
| D01/D02/B03 | Ruff/Black：所有本阶段 Python 改动文件；mypy：DSH 目录、guardrails、新测试、冒烟脚本 | guardrails 存在重复声明和旧格式问题（观察） | 改动文件相关门禁通过 | 通过；旧测试全仓类型债务仍见 P0 | 通过 |
| D01/D05 | lock 重新解析、`uv pip check`、npm audit | npm peer 漂移与 macOS 13 解析失败为观察 | 版本一致、安装依赖兼容 | 解析通过；npm audit 0 vulnerabilities | 通过 |

真实模型脚本仅操作临时工作区，审批由受约束测试实现提供；不访问用户资料。默认 CI 跑离线单测和构建，不使用个人密钥，也不把远端 CI 尚未运行说成已通过。macOS 首次启动 SDK 会解压原生模块缓存；开发工具沙箱曾拒绝缓存目录和 loopback 监听，获得该检查的执行授权后启动通过。

## 复现

```bash
MACOSX_DEPLOYMENT_TARGET=14.0 uv pip compile requirements-dev-macos.in --python-version 3.12 --python-platform aarch64-apple-darwin -o requirements-dev-macos.lock
uv pip install --python .venv/bin/python -r requirements-dev-macos.lock
npm ci --prefix bridge/dsh --ignore-scripts
npm test --prefix bridge/dsh
.venv/bin/python scripts/smoke_dsh_bridge.py
```

最后一条会调用 `.env` 配置的真实模型并产生正常 API 用量。要求 macOS 14+ arm64。Windows DSH 私有 home ACL 与原生文件工具未完成验收，明确拒绝启动新底座；旧版路径保留。完整功能、SQLite 持久审批/结算与 Electron 界面在后续阶段交付。

版本来源：[PyPI SDK 0.1.5rc1](https://pypi.org/project/deepseek-harness-sdk/0.1.5rc1/)、[官方 DSH 仓库](https://github.com/deepseek-ai/deepseek-harness)、[固定 Agent 包](https://www.npmjs.com/package/@deepseek-ai/dsh-agent/v/0.1.5-rc.1)。使用已安装发布包声明核对 API，不以 master 的最新文档替代固定版本事实。
