# Async lifecycle ownership across UI and process boundaries

Signals: duplicate processors after concurrent enqueue, native child survives cancellation during SDK startup, or tests import incomplete Qt stubs after domain code no longer needs Qt.

Mechanism: creating an asyncio task schedules its body later. A flag set inside that body cannot establish ownership at submission time. Cancelling `to_thread` does not stop the worker thread. Global sys.modules stubs affect later unrelated tests, even after a target module stops using Qt.

Handling: retain the processor task at enqueue and check both ownership and running state; retain/shield SDK startup, await its completion before closing the harness; remove obsolete Qt stubs from Qt-free domain tests, keep Qt presentation dispatch in a compatibility adapter. Test in a temporary cwd: old fixtures can otherwise write default data directories (see baseline report B08).

Verified once on 2026-10-16: `tests/test_headless_service.py::TestHeadlessService::test_fifo_uses_one_processor_and_stop_cancels_all`, `tests/test_dsh_protocol.py::TestDshProtocol::test_cancel_during_sdk_start_waits_then_closes_child`, Qt-free real-model `scripts/smoke_headless_service.py`, and legacy UI startup. A recovered event fixture must retain assertions, not remove requirements. Runtime cleanup depends on the SDK's bounded startup timeout; this does not prove arbitrary third-party threads terminate.

## Voice callbacks outliving ownership

P8 applies the same ownership rule across JavaScript awaits. Stopping tracks is insufficient when an older permission request, polling response or AudioContext resume can still complete. Establish an operation revision before awaiting permission; invalidate it on mute/end, separately invalidate queued capture frames, and check both after asynchronous boundaries. Keep resume locally muted until the backend acknowledges it. Ignore old polling failures rather than letting them stop a replacement session.

`desktop/tests/voice-lifecycle.test.cjs` verifies four controlled delayed-Promise races. `tests/test_voice_service.py` verifies expired client leases, worker EOF, mute during worker exit, and cleanup when provider cancellation fails. Native developer-package playback/mute/resume/end also passed on 2026-10-16; physical echo and unplug behavior remain unverified. See `reports/2026-10-16_p8_voice.md`.

## Capture bursts and generation-scoped backpressure

On 2026-10-19, a packaged synthetic voice soak stopped with the explicit capture-overload UI error after 19 minutes. The eight-frame serial RPC queue allowed only 256 ms of audio. A controlled 600 ms renderer pause reproduced the same stop in the old package (`reports/2026-10-19_n6_voice_burst_before.json`). This establishes a failure mechanism, not the source or duration of the original scheduling stall.

The capture queue now allows at most 32 frames (1024 ms) and belongs to one capture generation. Short bursts drain in sequence; sustained backlog still releases the device rather than growing without limit. Release replaces the queue so a stale RPC tail cannot block a resumed microphone or decrement its pending count. No frames are silently dropped and no old generation is replayed. This changes burst tolerance, not the normal playback/interrupt latency target.

`desktop/tests/voice-lifecycle.test.cjs` covers a 16-frame burst, 33-frame sustained overload, and replacement while an old request is unresolved. All seven lifecycle tests passed. Native after-fix and full-duration results belong in the N6 report; do not infer two-hour reliability from these unit tests. Physical device quality remains unverified.

## TypeScript speech process and startup ownership (2026-10-21)

The main process must wait for the speech worker's explicit `booted` acknowledgement before forwarding commands. Installing its listener after asynchronous imports otherwise loses immediately posted requests. Main retains pending IDs and rejects them when stop kills inference, so a killed load cannot hold mute/end waiting for a reply that will never arrive. Generation checks apply both before and after model preparation and submit; repeated transcripts in the same round are ignored. Physical device behaviour remains separate.

Verified once by `packages/service/src/{speech,voice,application}.test.ts` and `qualification/ts-runtime/voice-process-probe.cts`: bounded queues, ten synthetic rounds, stale results, suspend, native load and forced worker death. Real DSH/Fish integrated probe was blocked before a provider request by Keychain timeout; do not treat local ASR success as that integration result.

Directly loading ONNX Runtime 1.30.0 without its startup privacy flag created a 51-byte `:memory:.ses` device/session marker under the sandbox (no audio). The official runtime switch is `ORT_DISABLE_TELEMETRY=1` **before native initialization**, not after loading the model. `packages/speech/src/electron-host.ts` sets the child environment and `recognizer.ts` sets it before dynamic import. Native repeat passed without creating this file. This verifies the observed file effect, not a network traffic audit. Source: [official privacy documentation](https://github.com/microsoft/onnxruntime/blob/main/docs/Privacy.md).
