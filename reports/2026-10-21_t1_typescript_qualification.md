# T1 无 Python 技术验证

平台：macOS arm64；Electron 44.8.0 / Node 24.22.0；DSH 0.1.5-rc.1；Transformers.js 4.3.1；ONNX Runtime 1.30.0。本阶段未切换业务后端或删除 Python。

## 结果与范围

- 实际 Electron utilityProcess 与 MessagePort 通信通过；业务进程内 SQLite FTS5 查询、在线备份与只读恢复通过。
- 官方 TS SDK 经 JS 入口和 POSIX execve 启动独立 DSH 二进制；SDK 子进程 PID 与桥报告 PID 相同。认证健康检查通过，无令牌请求被拒绝（403）。正常关闭和注入 SIGKILL 后的清理均确认进程消失。
- Electron 主进程完成合成 Keychain 来源读取、safeStorage 加密、0600 文件原子写入、读回验证；来源在验证前保留，测试结束仅清理自身合成条目。未迁移真实用户凭据，完整产品凭据模块归 T3。
- Node 下载官方固定 wheel ZIP，校验 SHA256，仅提取 DSH 原生二进制和许可证；VAD 与 Whisper 权重按大小/哈希固定。全程不运行 pip/Python。
- 将 TS 编译产物、全部验证依赖、DSH 插件及 Whisper 模型复制到新的临时目录后，SQLite、ONNX/VAD、ASR、DSH 与系统加密再次实际运行。Electron 可执行文件仍来自当前开发安装；这不是最终独立应用包验收。
- 120 条固定语料（108 来源样例＋12确定性噪声/停顿变体）依次由新版 Electron TS ASR 和旧版本地 faster-whisper 运行。均 CPU、4线程；各预热一条；无并行识别竞争、云端识别或麦克风采集。

| 指标 | 旧版 | 新版 | 预先定义门槛 | 实测判定 |
|---|---:|---:|---|---|
| 总体 CER | 21.20% | 22.01% | 恶化≤2个百分点 | +0.81个百分点，通过 |
| 热运行 P95 | 1239.97ms | 1471.58ms | 新版≤旧版1.2倍 | 1.187倍，通过 |

CER规则保持一致，不做繁简转换或模型专属文本纠正；绝对CER不能直接视为日常聊天体验。速度余量较小，仅本机此轮结果。噪声、停顿组各只有6个变体，CER分别从18.59%→24.12%、13.07%→19.10%，后续 T8 需要扩大真实噪声样本并优化，不能以总体通过掩盖分组退化。台湾来源无说话人元数据，不能声称覆盖全部台式口音。

## 问题与处置

| ID / 优先级 | 问题与证据 | 修改前行为 | 方案 | 修改后预期 | 风险 | 状态 |
|---|---|---|---|---|---|---|
| TQ-01 / P1 | rc.1 SDK 源码把 dshBin 拼入 Node argv | 将原生二进制直接作为 JS 入口预计失败；计划的参数语义有误 | JS入口 execve 替换为固定原生 runtime | PID/stdio保持，SDK直接管理退出 | 依赖POSIX及Electron Node模式fuse，Windows另验 | 本机验证通过 |
| TQ-02 / P1 | 初次锁文件混入rc.3；增加overrides后旧嵌套解析仍残留43项 | SDK与插件类型/协议可能混用 | 全家族固定rc.1，空目录重建锁，自动检查 | 锁文件无DSH版本漂移 | SDK依赖树较大，T2合并锁后须复验 | 验证通过 |
| TQ-03 / P1 | utilityProcess设置ELECTRON_RUN_AS_NODE后实测拒绝Chromium参数 | utility进程退出，业务代码不运行 | 仅SDK后续启动入口设置该变量 | utility正常启动，DSH仍走Node入口 | 环境层级必须继续隔离 | 验证通过 |
| TQ-04 / P2 | ONNX输出名是speech_probs，旧Python按位置取结果 | 初版探针访问output.data失败 | 使用锁定模型真实输入/输出名称 | 静音概率0.02383，ASR可转写 | 更换VAD权重必须复验张量协议 | 验证通过 |
| TQ-05 / P2 | 总体速度接近门槛，噪声/停顿组退化 | 新版在部分输入上更慢/更易错 | 保留固定评测，不更换小模型或降低门槛；T8扩大设备场景优化 | 完整语音接入有证据再判定 | 未解决时影响真实体验；优化有识别回归风险 | 总体门槛通过，分组优化待T8 |

## 验证记录

| ID | 命令/步骤 | 修改前预期或观察 | 修改后预期 | 实际结果 | 状态 |
|---|---|---|---|---|---|
| TQ-01/03/04 | `npm run --prefix qualification/ts-runtime check`；`dist/run.js`正常模式 | 03/04的失败为实际观察；01直接执行Mach-O的失败为源码推断 | 类型/版本/校验测试通过，真实utility启动 | 2项针对评测门槛及音频格式的测试通过；真实SQLite/ONNX/DSH通过 | 已执行 |
| TQ-01 | `dist/run.js ... --crash` | 未有TS生命周期证据 | 故障后确认退出，不重启或重放 | PID一致，SIGKILL后SDK清理通过 | 已执行 |
| TQ-02 | `dist/verify-dependencies.js`；`npm audit`安装输出 | 初次存在rc.3混用 | 全部DSH固定rc.1 | 无漂移；审计报告0已知漏洞（非全面安全审计） | 已执行 |
| TQ-01/04 | `dist/download-assets.js`；`dist/run.js ... --relocate` | 未有资源搬迁证据 | 新目录加载原生依赖及权重，无Python启动 | 哈希/许可证提取、搬迁启动、合成凭据往返通过 | 已执行 |
| TQ-05 | `dist/prepare-corpus.js`、`dist/augment-corpus.js`、Electron corpus运行、`dist/legacy-comparison.js`、`dist/compare-corpus.js` | 旧版实测见表，不以推断当基线 | 120条同源对照，质量≤2pp/速度≤1.2倍 | 两项总体门槛通过；全部结果与哈希保留 | 已执行 |
| 产品门槛 | 真人10轮、外放回声、端到端4秒、打断300ms、两组7200秒 | 历史未完整验收 | 后续阶段真实验证 | 本阶段未执行 | 待验收 |

证据：`reports/ts-migration/t1-*.json`；可重跑的代码、来源与命令见 `qualification/ts-runtime/README.md`。当前仅 T0/T1 已交付；T2–T10 尚未完成。T1 的技术可行性通过不等于语言迁移或产品发布完成。
