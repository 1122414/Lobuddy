"""Functional test script for Lobuddy 5.8 system optimization.

Run with: python tests/test_58_functional.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.events import (
    EventBus,
    TaskCompleted,
    TaskFailed,
    TaskQueued,
    TaskStarted,
)
from core.services.maintenance_scheduler import MaintenanceScheduler, MaintenanceTask
from core.services.observability_service import ObservabilityService


def test_event_bus_roundtrip():
    print("[TEST] EventBus roundtrip...")
    bus = EventBus()
    received = []

    bus.subscribe(TaskQueued, lambda e: received.append(e))
    bus.subscribe(TaskStarted, lambda e: received.append(e))
    bus.subscribe(TaskCompleted, lambda e: received.append(e))
    bus.subscribe(TaskFailed, lambda e: received.append(e))

    bus.publish(TaskQueued(task_id="t1", session_id="s1"))
    bus.publish(TaskStarted(task_id="t1"))
    bus.publish(TaskCompleted(task_id="t1", session_id="s1", success=True, summary="done", error_message=""))

    assert len(received) == 3, f"Expected 3 events, got {len(received)}"
    print("  PASS: EventBus roundtrip works")


def test_event_payload_safe():
    print("[TEST] Event payload safety...")
    event = TaskCompleted(
        task_id="t1",
        session_id="s1",
        success=True,
        summary="result",
        error_message="",
    )
    payload = str(event)
    sensitive = ("api_key", "secret", "token", "password", "bearer")
    for s in sensitive:
        assert s not in payload.lower(), f"Payload contains sensitive word: {s}"
    print("  PASS: Event payload is safe")


def test_maintenance_scheduler():
    print("[TEST] Maintenance scheduler...")
    scheduler = MaintenanceScheduler(start_delay_seconds=0.1, poll_interval_seconds=0.1)
    results = []

    def dummy_task():
        results.append("ran")
        return "ok"

    scheduler.register(
        MaintenanceTask(name="test_task", fn=dummy_task, interval_seconds=0.2)
    )
    scheduler.start()
    time.sleep(0.5)
    scheduler.stop()

    assert len(results) >= 1, f"Expected at least 1 run, got {len(results)}"
    print(f"  PASS: Maintenance scheduler ran {len(results)} time(s)")


def test_maintenance_scheduler_failure_isolation():
    print("[TEST] Maintenance failure isolation...")
    scheduler = MaintenanceScheduler(start_delay_seconds=0.1, poll_interval_seconds=0.1)
    good_runs = []

    def failing_task():
        raise RuntimeError("intentional failure")

    def good_task():
        good_runs.append("ran")
        return "ok"

    scheduler.register(
        MaintenanceTask(name="fail", fn=failing_task, interval_seconds=0.2)
    )
    scheduler.register(
        MaintenanceTask(name="good", fn=good_task, interval_seconds=0.2)
    )
    scheduler.start()
    time.sleep(0.5)
    scheduler.stop()

    assert len(good_runs) >= 1, "Good task should still run despite neighbor failure"
    print(f"  PASS: Failure isolation works ({len(good_runs)} good run(s))")


def test_observability_service():
    print("[TEST] Observability service...")
    svc = ObservabilityService()
    summary = svc.get_summary()

    assert "token" in summary
    assert "recent_tasks" in summary
    assert "recent_traces" in summary
    assert "hitl_decisions" in summary
    assert "recent_errors" in summary
    print("  PASS: Observability service returns expected structure")


def test_settings_env_var_coverage():
    print("[TEST] Settings env var coverage...")
    from app.config import _ENV_VAR_MAP

    required_58_keys = [
        "maintenance_start_delay_seconds",
        "maintenance_poll_interval_seconds",
        "maintenance_memory_cleanup_interval_seconds",
        "maintenance_skill_review_interval_seconds",
        "maintenance_trace_cleanup_interval_seconds",
        "maintenance_asset_cache_cleanup_interval_seconds",
        "observability_max_traces",
        "observability_max_hitl_records",
        "observability_max_token_sessions",
    ]

    missing = [k for k in required_58_keys if k not in _ENV_VAR_MAP]
    assert not missing, f"Missing env var mappings: {missing}"
    print(f"  PASS: All {len(required_58_keys)} 5.8 settings have env var mappings")


async def main():
    print("=" * 60)
    print("Lobuddy 5.8 System Optimization — Functional Tests")
    print("=" * 60)

    test_event_bus_roundtrip()
    test_event_payload_safe()
    test_maintenance_scheduler()
    test_maintenance_scheduler_failure_isolation()
    test_observability_service()
    test_settings_env_var_coverage()

    print("=" * 60)
    print("All functional tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
