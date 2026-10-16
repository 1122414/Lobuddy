# Protocol request retention must share one definition

Signals: a desktop works initially, then reports request capacity after repeated status polling; Node and Python maintain different read-method lists.

Mechanism: bounded duplicate-request storage is needed for side effects, but retaining every completed status query exhausts it. P6 added companion polling while only one transport layer released those queries.

Diagnosis and handling: inspect both retention owners. Define transient methods in `core/service/protocol.py`, generate the TypeScript constant through `scripts/generate_desktop_protocol.py`, and consume it in `desktop/electron/service-client.ts`. Keep mutations with side effects out of the list. A temporary presence heartbeat may be transient only when replay is harmless.

Supporting case: P7 `tests/test_companionship.py` performs 8300 reads through the real stdio request handler and verifies no retained completed requests. The full suite passed 778 tests; native companionship and model checks passed on 2026-10-16.

Validation: verified once. This establishes capacity behavior, not wall-clock memory stability or delivery guarantees for future methods. New high-frequency voice methods must be assessed against this same distinction.
