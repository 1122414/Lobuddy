# Async lifecycle ownership across UI and process boundaries

Signals: duplicate processors after concurrent enqueue, native child survives cancellation during SDK startup, or tests import incomplete Qt stubs after domain code no longer needs Qt.

Mechanism: creating an asyncio task schedules its body later. A flag set inside that body cannot establish ownership at submission time. Cancelling `to_thread` does not stop the worker thread. Global sys.modules stubs affect later unrelated tests, even after a target module stops using Qt.

Handling: retain the processor task at enqueue and check both ownership and running state; retain/shield SDK startup, await its completion before closing the harness; remove obsolete Qt stubs from Qt-free domain tests, keep Qt presentation dispatch in a compatibility adapter. Test in a temporary cwd: old fixtures can otherwise write default data directories (see baseline report B08).

Verified once on 2026-10-16: `tests/test_headless_service.py::TestHeadlessService::test_fifo_uses_one_processor_and_stop_cancels_all`, `tests/test_dsh_protocol.py::TestDshProtocol::test_cancel_during_sdk_start_waits_then_closes_child`, Qt-free real-model `scripts/smoke_headless_service.py`, and legacy UI startup. A recovered event fixture must retain assertions, not remove requirements. Runtime cleanup depends on the SDK's bounded startup timeout; this does not prove arbitrary third-party threads terminate.
