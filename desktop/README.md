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

`package` produces a timestamped `release/Lobuddy-*.app`; `release/latest.txt` locates it. **This P3 development package still needs this checkout and its Python environment.** It is not the P9 standalone installation. The generated development-runtime.json contains local paths, no credentials. No signing, notarization, or public release is performed.

The desktop smoke uses real configured model calls and disposable files. It checks sandboxing, multiple turns, rejection/allowance, approval on refresh, cancellation, task navigation and actual close/reopen. It never auto-approves user tasks: approvals in this test are confined to the newly created test workspace. `LOBUDDY_PACKAGE` may point to a generated app's `Contents/MacOS/Lobuddy` executable to test the package itself. Unit/transport tests need no model access.

`npm run preview --prefix desktop` serves built UI for visual inspection only. A normal browser has no business bridge; the UI clearly reports this and cannot send messages. Native functional tests use Playwright's Electron driver because the in-app browser cannot access the sandboxed Electron preload.

Source ownership: electron/ manages lifecycle and IPC; src/components/ owns views; src/useDesktop.ts reconciles real state/events; shared/desktop-protocol.ts is generated from Python (`scripts/generate_desktop_protocol.py`). Changes to protocol source must regenerate that file. Automatic retries of mutations are prohibited; cancelled, failed and interrupted states remain distinct.
