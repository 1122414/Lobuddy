# Process termination and incident evidence

Signals: a native test reports only “page/context/browser closed”; closing the app after a child crash takes the entire shutdown timeout.

Mechanism: in Node, a child terminated by a signal has a non-null `signalCode` while `exitCode` remains null. Checking only `exitCode === null` treats a terminated child as live and installs an exit listener after its exit event has already occurred. Browser target closure alone cannot distinguish application quit, renderer failure, service failure, or runner interruption.

Diagnosis and handling:

- Record child role, PID, exit code and signal alongside Electron quit/renderer events. Never persist child arguments, environment, provider payloads or raw stderr in this diagnostic stream.
- Separate events preceding failure from deliberate test cleanup. A cleanup-generated quit cannot establish the cause of an earlier failure.
- Check both `exitCode` and `signalCode` before writing a request or waiting for termination. Keep existing ownership and bounded cleanup rules for live processes.
- Isolate native tests with their own Electron userData and business directories; keep real microphone/model processing outside synthetic stability claims.

Supporting case: `reports/2026-10-19_n0_baseline.md` (PA-03). Native SIGKILL injection observed about 50 seconds between cleanup start and application exit before the fix, versus 0.049 seconds after the fix. `desktop/tests/service-lifecycle.test.cjs` covers rejection of new requests and repeated stop after signal termination. `desktop/tests/runtime-evidence.test.cjs` covers incomplete evidence and cleanup attribution; `desktop/tests/runtime-soak.cjs` records native process evidence and checks orphan processes.

Verification: verified once on macOS arm64 on 2026-10-19, including a HEAD + N0-only isolated build. The two-hour run is a separate gate; see its report for final status. This finding does not establish the cause of the historical 2026-10-16 closed-page incident, and does not prove Windows signal semantics or voice-device stability.
