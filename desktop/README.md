# Lobuddy desktop

Electron 44.8.0 + React 19.3.1 + TypeScript 7.0.2 + Vite 8.3.4. macOS 14+ arm64 development target.

```bash
npm ci --prefix desktop --ignore-scripts
node desktop/node_modules/electron/install.js
npm run build --prefix bridge/dsh
npm test --prefix desktop
npm start --prefix desktop
```

Python dependencies are locked in `requirements-dev-macos.lock`; the default interpreter is the checkout's `.venv/bin/python`. `LOBUDDY_PYTHON` can explicitly select another interpreter. Configure `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` in the checkout's ignored `.env`. Do not put credentials in Vite environment variables or frontend code.

The main process owns one Python stdio service. React receives a narrowly scoped preload API, and Python validates every business request. Only the local `lobuddy://app` main frame can invoke IPC; navigation, new windows and unrequested permissions are denied. Chat Markdown ignores raw HTML and remote images. HTTP(S) links use the system browser, with all other schemes rejected. Window close/reload rejects pending approvals; running tasks stay in the service until explicitly cancelled or app exit.

Development data is isolated under Electron's userData/service directory. `LOBUDDY_DATA_DIR` and `LOBUDDY_WORKSPACE` allow explicit test directories; existing legacy data is not migrated by this phase. Selecting the background mode gives work an independent serial lane and engine session.

```bash
npm run package --prefix desktop
npm run test:desktop --prefix desktop
```

`package` produces a timestamped standalone `release/Lobuddy-*.app`; `release/latest.txt` locates it. The app includes Python, DSH and runtime dependencies, with no development-runtime.json or bundled credentials. The qualified Python build base is uv standalone CPython 3.12.13 for macOS arm64; other Python distributions need relocation qualification before packaging. No signing, notarization, or public release is performed.

The desktop smoke uses real configured model calls and disposable files. It checks sandboxing, multiple turns, rejection/allowance, approval on refresh, cancellation, task navigation and actual close/reopen. It never auto-approves user tasks: approvals in this test are confined to the newly created test workspace. `LOBUDDY_PACKAGE` may point to a generated app's `Contents/MacOS/Lobuddy` executable to test the package itself. Unit/transport tests need no model access.

`npm run preview --prefix desktop` serves built UI for visual inspection only. A normal browser has no business bridge; the UI clearly reports this and cannot send messages. Native functional tests use Playwright's Electron driver because the in-app browser cannot access the sandboxed Electron preload.

Source ownership: electron/ manages lifecycle and IPC; src/components/ owns views; src/useDesktop.ts reconciles real state/events; shared/desktop-protocol.ts is generated from Python (`scripts/generate_desktop_protocol.py`). Changes to protocol source must regenerate that file. Automatic retries of mutations are prohibited; cancelled, failed and interrupted states remain distinct.

## Voice development (P8, physical acceptance pending)

Install the locked Python environment including the `voice` extra. In Settings, explicitly download the fixed multilingual small model; opening chat never downloads it automatically. CPU int8 recognition and Silero VAD run in a child process, with only bounded in-memory PCM. Final transcripts use the existing message/history path. Model downloads require internet; recognition does not use cloud ASR.

Configure Fish in the native credential dialog (macOS Keychain), or explicitly migrate a development `.env` with `python -m app.upgrade credentials`. Website credits and API credit are separate. The user-selected default is `s2.1-pro-free`, with no latency SLA and possible provider model-improvement retention. Settings can explicitly choose paid `s2.1-pro`; errors never change tier or voice. The fixed voice is `e4a66454f7a44f63a2cc9e8c044d701d`.

Open quick chat and choose “开启语音陪伴”. Only this visible trusted window can acquire the microphone. Muting stops tracks and queued playback; resuming reacquires them. Ending, hiding, reloading or closing quick chat releases the device and cancels only its foreground dialogue. A lost client lease stops its worker. Background work remains independently governed.

Opt-in checks (real provider requests; separate synthetic data):

```bash
node desktop/tests/voice-download-smoke.cjs --download
.venv/bin/python -m scripts.voice_smoke --model-dir .local-upgrade/p8-voice-smoke/data/voice-models/small --clip .local-upgrade/p8-voice-smoke/input.wav --rounds 10
node desktop/tests/voice-smoke.cjs
```

The Node test uses a synthetic browser MediaStream and a fake OS permission response. It tests real AudioWorklet, ASR, DSH, Fish, playback and release, but does not qualify physical microphone authorization, headphone/speaker echo or human conversational quality. These remain manual acceptance checks. Never disable the production renderer sandbox to make a WAV test fixture readable by Chromium's audio service.

`LOBUDDY_PACKAGE` can also select a generated app executable for the voice smoke. The test uses a temporary Chromium profile to avoid taking over an open user instance. Lifecycle unit tests control delayed permission/poll responses and verify stale callbacks cannot revive capture or stop a new voice session. Historical measurements are in `reports/2026-10-16_p8_voice.md`; 10.19 synthetic latency/interruption samples and remaining human checks are in `reports/2026-10-19_n6_integration.md`.


## 10.19 独立本地包

`npm run package` 使用现有锁定环境生成内含 Python/DSH/语音依赖的 macOS arm64 `.app`，不再写 development-runtime.json。运行前需已构建 `bridge/dsh`。构建器输出运行依赖版本和文件 SHA256 清单，不打包 `.env` 或用户资料。

`node tests/package-smoke.cjs` 将整个应用搬到隔离临时目录，清除 Python 开发环境变量后验证启动和资料任务。真实模型检查可显式设置 `LOBUDDY_PACKAGE_REAL=1` 并从进程环境配置模型；凭据不得写入测试。

参见 `docs/2026-10-19_personal_agent_guide.md`。语音真人验收与持续运行结果单独记录，不以可构建替代完整交付。
