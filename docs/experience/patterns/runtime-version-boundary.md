# Match plugin types, runtime and resolution target

## Signals and mechanism

An exact DSH SDK pin does not pin TypeScript peer dependencies. DSH 0.1.5-rc.1 packages declare caret peers; npm selected rc.3 for a transitive peer while the root agent remained rc.1, causing ERESOLVE. Also, uv's generic macOS platform resolves against macOS 13, while the official SDK runtime wheel requires macOS 14.

## Diagnosis and handling

Read installed SDK code and the exact npm release declarations. Pin the transitive DSH peer closure with overrides and a package lock, rather than force-installing incompatible peers. Compile the Python lock with MACOSX_DEPLOYMENT_TARGET=14.0. Check real startup independently of type checking: the packaged runtime also extracts native modules and opens loopback sockets.

Only deliver authenticated commands to a custom plugin and let Python own governed effects. An event-stream loss must revoke pending approval and work; restoring a session must not resume its old inbox. Validate this by killing the owned process while approval is pending, then checking persisted effects after resume.

## Boundaries and evidence

Verified once on macOS arm64, SDK/runtime 0.1.5rc1 and npm types 0.1.5-rc.1. Not a guarantee for newer releases or Windows. Review the peer closure and profile row IDs on upgrades.

- `bridge/dsh/package.json`, `bridge/dsh/package-lock.json`
- `requirements-dev-macos.in`, `core/agent/dsh/runtime.py`
- `scripts/smoke_dsh_bridge.py`: real model, midstream cancellation, approval-time crash and no replay
- `reports/2026-10-16_p1_dsh_bridge.md`: observed results and limitations

## Recheck live configuration before blaming a new transport

On 2026-10-16, P1/P2 real model checks had passed, while a later Electron test and the independent stdio smoke both failed. A sanitized SDK startup check reported an empty exact model name. Presence-only inspection showed all three local LLM settings empty; their file modification time had changed. Restoring configuration made both transports work. The reason for the external file change was not established. Do not treat an earlier successful check as evidence that mutable configuration is still present; compare the known-good transport and inspect presence/model/host without displaying key values. `DshRuntime.start` now rejects empty settings before SDK initialization; desktop health reports `model_configured`. Verified once; this is not a general diagnosis for every JsonRpcError.

## TypeScript SDK launch semantics and npm resolution (2026-10-21)

The rc.1 TypeScript SDK's `dshBin` is a JavaScript module argument to `process.execPath`, despite its suggestive name. Passing the Python distribution's standalone Mach-O directly is not supported by that public option. The T1 qualification uses a compiled TS entry which calls POSIX `process.execve` with the verified native runtime. The bridge-reported PID equals the entry PID; normal SDK shutdown and injected SIGKILL both left that PID absent. This was verified once inside Electron 44.8.0 utilityProcess / Node 24.22.0 on macOS arm64. The final package must preserve/verify Node-mode fuse support; do not generalize to Windows or a different SDK release.

Set `ELECTRON_RUN_AS_NODE` only for the SDK-created entry. Setting it on `utilityProcess.fork` caused the Electron Helper to reject `--type=utility` and other Chromium arguments before the worker could run. This is an environment ownership issue, not an ONNX binary incompatibility.

The SDK imports a larger DSH dependency tree than the original bridge. Reusing the bridge's partial overrides selected rc.3 packages; even after adding overrides, the initial installed tree/lock retained 43 nested rc.3 entries. A fresh task-owned install with the complete DSH-family overrides resolved everything to rc.1. `qualification/ts-runtime/verify-dependencies.ts` checks the entire lock, rather than only top-level versions. No force/legacy-peer install was used. Keep original user work and lockfiles intact; the discarded tree in this case was generated solely for qualification.

Evidence: `qualification/ts-runtime/native-entry.cts`, `worker.cts`, `verify-dependencies.ts`, and `reports/2026-10-21_t1_typescript_qualification.md`. This is component feasibility, not completion of the TS business migration or independent application packaging. The earlier Python ownership description applies to the still-default backend; T4 will move that owner to TS without changing the governed-effects boundary.
