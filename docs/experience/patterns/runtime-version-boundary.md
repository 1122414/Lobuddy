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
