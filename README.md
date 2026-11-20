# Lobuddy

浊蒂桌宠陪伴的桌面个人助手，使用 **Electron + React + TypeScript + SQLite + DSH**。支持文字与图片对话、受控工具、关系记忆、主动气泡、持续委托、Jev 判断、技能学习、可验证的工作流改进与本地连续语音。

当前为 macOS Apple Silicon（macOS 14+）发布候选。默认开发、检查、打包和运行不调用 Python。真人十轮、耳机与扬声器回声、完整语音长稳和最终发布验收仍单独记录，不能把自动检查通过视为全部体验验收通过。

## 开发

使用 Node 24（需要内置 `node:sqlite`），在仓库根目录操作：

```sh
npm ci
npm run setup:native
npm run build:packages
npm run --workspace @lobuddy/dsh-bridge build
npm run --workspace lobuddy-desktop build
npm start
```

只有一个根 `package-lock.json`。`.npmrc` 禁止安装脚本，`setup:native` 仅安装锁定的 Electron 分发物；SQLite、ONNX、sharp 和 DSH 使用原生二进制。开发模型配置可放在本机 `.env`（参考 `.env.example`），不要提交密钥。应用设置提供受系统保护的凭据入口；开发 `.env` 不随包分发。

首次使用开发环境的真实 DSH 引擎，先运行 `npm run --workspace @lobuddy/runtime-qualification build`，再运行 `node qualification/ts-runtime/dist/download-assets.js .local-upgrade/ts-assets --runtime-only` 下载并校验锁定的运行时。无需全局 DSH 或 Python。语音模型在应用设置中由用户明确下载；未下载时文字功能可用。旧 faster-whisper 模型不能直接供 ONNX 使用。

## 工程结构

| 路径 | 职责 |
|---|---|
| `desktop/` | React 桌宠与管理界面、受限 preload、Electron 窗口/凭据/进程管理 |
| `packages/contracts/` | 110 个 RPC 方法、事件、配置与持久化数据的 Zod 校验和 TS 类型 |
| `packages/domain/` | 纯业务规则、状态机、日期/时区、记忆规则与工作流定义 |
| `packages/service/` | 独立业务进程，SQLite 唯一写入者、任务治理、记忆、学习与调度 |
| `packages/speech/` | 独立 Silero VAD / Whisper small ONNX q8 语音进程 |
| `bridge/dsh/` | 锁定 DSH 的受控插件桥，HTTP 命令与 SSE 事件 |
| `qualification/ts-runtime/` | 固定运行时/模型来源、哈希、许可证与原生验证工具 |
| `migration/` | 冻结旧行为样例及逐项迁移去向 |
| `reports/` | 实际验证结果和未关闭门槛 |

数据流是 React → preload → Electron → MessagePort → TS 业务进程 → DSH／Fish／Jev。业务进程写 SQLite；原始麦克风音频只在内存中进入本地语音进程。转写文字交给配置的模型服务，回复文字交给 Fish 合成；它仍是联网助手。

工具执行须经过路径、网络、预算与审批边界；未知写入结果不自动重放。工作流晋升仅改变受控工作方式，不扩大授权，也不允许模型修改评测规则或应用源码。学习状态、来源与回退可在管理界面查询。

## 验证和打包

```sh
npm run check
npm run check:retirement
npm run test:integration
npm run test:desktop
npm run package:mac
npm run verify:package
npm run test:soak
npm run test:voice-soak
```

`check` 不使用模型凭据；原生桌面真实模型检查需要本机配置。长稳默认分别计满 7200 秒，隐藏窗口会按设计结束语音；中断不能按累计时长判通过。打包生成未公开签名/公证的本地 arm64 `.app`，路径写在 `desktop/release/latest.txt`。包包含 Electron、DSH 和必要原生依赖，识别模型仍需显式下载。

验收最终包时，将 `LOBUDDY_SOAK_PACKAGE` 设置为该 `.app` 的绝对路径再运行 `npm run test:soak`；脚本会搬迁安装包、使用隔离资料并记录包清单哈希。`LOBUDDY_SOAK_REPORT` 可指定新的报告路径，短测不会标记为两小时通过。`node desktop/tests/package-migration-smoke.cjs` 检查最终包自动导入合成旧库、重启幂等和备份恢复；重复运行用 `LOBUDDY_MIGRATION_REPORT` 指定新文件，保留先前证据。

## 数据升级与回退

首次启动会将旧应用资料备份后导入独立 TS 目录，保留实体 ID、来源和版本证据。旧进程必须先退出，损坏库或未知版本会阻止升级；不会悄悄创建空库代替。TS 存储版本为 3，旧程序不能直接打开。

默认新资料在 Electron 用户资料目录的 `typescript/` 下，旧资料和升级备份保留。本工程应用名为 `lobuddy-desktop`，默认 macOS 路径为 `~/Library/Application Support/lobuddy-desktop/typescript/`；开发或测试可显式指定隔离目录。凭据使用 Electron safeStorage 系统保护并读回校验，不可用时报错。第一次迁移保留旧凭据来源，以便回退。

手动工具只写入新的目标目录：

```sh
npm run storage -- backup DATA WORKSPACE BACKUP
npm run storage -- verify BACKUP
npm run storage -- import BACKUP NEW_TS_DIRECTORY
npm run storage -- restore BACKUP NEW_ROLLBACK_DIRECTORY
```

回退采用 Git 历史中的旧程序和升级前备份。先保存新版快照，再恢复旧版本；新版期间新增聊天不会自动反向合并。旧 Python／Qt／nanobot 源码和对照脚本保留在 Git 历史，不属于当前默认工程。

- [完整 TS 重构计划](plan_/10.21/2026-10-21_lobuddy_full_typescript_rebuild_plan.md)
- [T9 切换记录与剩余验收](reports/2026-10-21_t9_typescript_cutover.md)
- [T10 安装包验收进度](reports/2026-10-21_t10_release_candidate.md)
- [行为迁移清单说明](migration/README.md)
- [项目经验索引](docs/experience/README.md)
