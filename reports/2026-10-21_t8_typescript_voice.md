# T8：无 Python 连续语音实现与自动验收

基线：T7 `8d71667`。本阶段完成 TS 语音实现和可执行自动检查，默认桌面切换归 T9。真实 DSH→Fish 联调本次被钥匙串授权阻塞，不能宣称全部语音或发布门槛通过。

## 改动

| ID / 优先级 | 问题与证据 | 改动前行为 | 方案及预期 | 风险 | 状态 |
|---|---|---|---|---|---|
| TS8-01 / P1 | TS speech 包仅有协议类型 | 无持续采音识别实现 | 主进程持有独立 utilityProcess；Silero 状态、32 ms 帧、700 ms 停顿、Whisper small q8；固定文件 SHA256 | 本机 T1 速度余量小，不能推广到其他机器 | 本地原生加载及转写通过 |
| TS8-02 / P1 | TS 业务没有语音生命周期 | 无插话、静音、恢复和音频处理 | generation/round/turn 隔离；先停播/废弃旧结果，再取消拥有的前台任务；静音直接终止识别进程 | 外放回声仍依赖浏览器回声消除和真人验收 | 自动检查通过 |
| TS8-03 / P1 | 模型、采集、推理或播放可能过载 | TS 无队列限制 | 32 帧输入、单 ASR、938 帧最长片段、96 事件输出背压与 128 硬限；五秒客户端租约 | 持续过载明确停止，不能无界排队 | 自动检查通过 |
| TS8-04 / P1 | Fish 网络块可能在 PCM 样本中间断开 | TS 无合成链路 | 固定音色/档位，重组偶数字节 PCM；错误分类、无重试或换声；秘密仅业务内存 | 免费档不保证延迟；真实合成此次未执行 | 合成响应与错误模拟通过，真实联调待补 |
| TS8-05 / P2 | 直接加载 ORT 产生 `:memory:.ses` 标识文件（已观察） | 原生库初始化尝试持久化遥测标识 | 在导入原生绑定前设置官方 `ORT_DISABLE_TELEMETRY=1`，主进程也固定传入 | 本阶段未抓包测量所有底层网络行为 | 原生识别复验通过，未再生成该文件 |

下载由用户明确发起，只接受固定模型清单及允许的 HTTPS 下载域名，按大小和哈希校验、原子替换；加载不下载模型。不复用旧 faster-whisper 文件，不自动换模型或云端识别。语音进程不接收模型、Fish、Jev API Key。业务数据库不保存 PCM。

## 验证

| ID | 测试 / 命令 | 改动前预期（除注明外未实测） | 改动后预期 | 实际结果 | 状态 |
|---|---|---|---|---|---|
| TS8-01 | `speech.test.ts`；`voice-process-probe.cts` | 无 TS 识别实现 | 连续 VAD、真实本地转写、显式进程恢复 | 合成十句和原生 Whisper/Silero 通过；强制杀进程后显式启动成功 | 已执行 |
| TS8-02 | `voice.test.ts`；既有桌面 `voice-lifecycle.test.cjs` | 无 TS 会话实现 | 旧音频/转写不复活；只取消自身前台轮；后台独立 | 十轮、重复转写、插话、静音、启动中结束、失联租约通过 | 已执行 |
| TS8-03 | `speech.test.ts` 队列；`voice.test.ts` 慢播放；应用 suspend | 无队列治理 | 丢帧失败、过载有界、慢播放有背压、睡眠释放 | 32 帧边界、200 个 PCM 块背压、窗口控制链与 suspend 通过 | 已执行 |
| TS8-04 | `voice.test.ts` Fish connection 桩与 `voice-chain-probe.cts` | 无 TS Fish 实现 | 402 明确提示；单次请求；不完整样本报错；真实声音可用 | 错误/奇数网络块测试通过；真实联调在读取钥匙串时超时，尚未调用服务 | 联调待凭据授权 |
| TS8-05 | 关闭初始化遥测后再次运行原生 probe | 初次直接导入生成标识文件（实测） | 不再创建该文件，仍能推理 | 本地原生四组再次通过，见证据 JSON | 已执行 |

- `npm run build:packages`、qualification 构建通过。
- 工作目录及独立快照 `/private/tmp/lobuddy-t8-snapshot-nSlS4G`：`LOBUDDY_PYTHON=<旧桌面对照环境> npm run check` 通过 qualification 2、contracts 5（988 输入）、integration 119、bridge 8、desktop 16。
- 后补慢播放背压断言，同步独立快照重新构建并单独运行九组 voice 测试，通过；不将其计入上述 119 的全量计数。
- 独立快照 `npm ci --offline --ignore-scripts` 安装 674、审计 682、0 vulnerabilities。只增加已有 workspace 和已锁定 Zod 的直接依赖声明，未升级依赖。
- [原生证据](2026-10-21_t8_native_speech_evidence.json)：固定模型校验、真实 VAD/ASR、本进程终止及崩溃后显式恢复四组。使用既有固定公开语料，不采集真实麦克风；没有保存转写正文。
- 旧断言映射新增 9 项，累计 147 / 1077；930 项仍待逐项核对。所有 110 方法中服务实现 109，`credential.configure` 保留主进程专用入口，归 T9。

## 剩余门槛

真实模型及 Fish 联调需恢复本机钥匙串读取授权后运行 `voice-chain-probe.cts`。真人十轮、耳机和外放回声、插话 300 ms / 响应 4 秒 P95、两个 7200 秒长稳尚未关闭。T1 整体 ASR 对照通过但噪声子集退化仍有效，不能以合成十轮覆盖实际识别质量。当前不发布、不推送、不删除 Python。

官方遥测开关依据：[ONNX Runtime Privacy](https://github.com/microsoft/onnxruntime/blob/main/docs/Privacy.md)。

## 凭据恢复后的补充验收

用户恢复本机凭据后，再次运行 `qualification/ts-runtime/voice-chain-probe.cts`，五组全部通过：固定公开 PCM 经 Silero/Whisper、本轮 DSH 回复、指定 Fish 免费音色流式 PCM；只保存最终文字；静音释放实际识别进程；显式恢复使用新代次；业务和语音退出无孤儿。见 [真实链路证据](2026-10-21_t8_voice_chain_evidence.json)。这关闭了 TS8-04 的真实服务联调阻塞，不替代真人麦克风、外放回声、延迟分位数及两小时长稳。
