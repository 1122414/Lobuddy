"""Functional test script for Lobuddy 5.8 system optimization features.

Usage:
    python scripts/test_system_optimization.py

Tests: event model, maintenance scheduler, observability service, compile check.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_event_model():
    """Verify all event types are importable and instantiable."""
    from core.events import (
        EventBus,
        FocusSessionChanged,
        HitlApproved,
        HitlDenied,
        HitlRequested,
        HitlTimeout,
        MemoryAccepted,
        MemoryProposed,
        MemoryRejected,
        QueueLengthUpdated,
        SkillCandidateApproved,
        SkillCandidateCreated,
        SkillCandidateDisabled,
        TaskAbilityUnlocked,
        TaskCompleted,
        TaskExpGained,
        TaskLevelUp,
        TaskQueued,
        TaskStarted,
        ToolCallBlocked,
        ToolCallExecuted,
        ToolCallPlanned,
    )

    # Instantiate each event type
    events = [
        TaskQueued(task_id="t1", session_id="s1"),
        TaskStarted(task_id="t1"),
        TaskCompleted(task_id="t1", session_id="s1", success=True, summary="done", error_message=""),
        ToolCallPlanned(task_id="t1", tool_name="read_file"),
        ToolCallExecuted(task_id="t1", tool_name="read_file", success=True),
        ToolCallBlocked(task_id="t1", tool_name="rm", reason="dangerous"),
        HitlRequested(task_id="t1", tool_name="rm", command_preview="rm -rf /", risk_tags=["destructive"]),
        HitlApproved(task_id="t1", tool_name="rm"),
        HitlDenied(task_id="t1", tool_name="rm", reason="too dangerous"),
        HitlTimeout(task_id="t1", tool_name="rm"),
        MemoryProposed(memory_type="episodic", title="test", confidence=0.9),
        MemoryAccepted(memory_type="episodic", memory_id="m1", title="test"),
        MemoryRejected(memory_type="episodic", title="test", reason="low confidence"),
        SkillCandidateCreated(skill_name="test-skill", rationale="needed", confidence=0.8),
        SkillCandidateApproved(skill_name="test-skill", skill_id="sk1"),
        SkillCandidateDisabled(skill_name="test-skill", skill_id="sk1", reason="stale"),
        TaskExpGained(amount=10, current_exp=50, required_exp=100, level_up=False),
        TaskLevelUp(level=5, stage=2),
        TaskAbilityUnlocked(ability_id="a1", ability_name="super_search"),
        FocusSessionChanged(state="focusing", seconds_remaining=1500),
        QueueLengthUpdated(length=3),
    ]
    print(f"  [OK] {len(events)} event types instantiated")

    # Test EventBus pub/sub
    bus = EventBus()
    received = []

    bus.subscribe(TaskStarted, lambda e: received.append(e.task_id))
    bus.publish(TaskStarted(task_id="bus-test"))
    assert received == ["bus-test"], f"Expected ['bus-test'], got {received}"
    print("  [OK] EventBus pub/sub works")


def test_maintenance_scheduler():
    """Verify maintenance scheduler registers and runs tasks."""
    from core.services.maintenance_scheduler import MaintenanceScheduler, MaintenanceTask

    scheduler = MaintenanceScheduler(start_delay_seconds=0)
    results = []

    scheduler.register(
        MaintenanceTask(
            name="test_task",
            fn=lambda: results.append("ran") or "ok",
            interval_seconds=0.1,
        )
    )

    scheduler.start()
    time.sleep(0.5)
    scheduler.stop()

    status = scheduler.get_status()
    assert len(status) == 1, f"Expected 1 task, got {len(status)}"
    assert status[0]["name"] == "test_task"
    assert status[0]["run_count"] >= 1, f"Expected >=1 runs, got {status[0]['run_count']}"
    assert len(results) >= 1, f"Expected >=1 results, got {len(results)}"
    print(f"  [OK] Maintenance scheduler: {status[0]['run_count']} runs")


def test_observability_service():
    """Verify observability service handles missing dependencies gracefully."""
    from core.services.observability_service import ObservabilityService

    obs = ObservabilityService()
    summary = obs.get_summary()

    assert "token" in summary
    assert "recent_traces" in summary
    assert "hitl_decisions" in summary
    assert summary["token"].get("available") is False
    assert summary["recent_traces"] == []
    assert summary["hitl_decisions"] == []
    print("  [OK] ObservabilityService handles missing deps gracefully")


def test_py_compile():
    """Verify all new modules compile."""
    import py_compile

    files = [
        "core/events/events.py",
        "core/events/__init__.py",
        "core/services/maintenance_scheduler.py",
        "core/services/observability_service.py",
        "ui/observability_panel.py",
        "app/service_wiring.py",
        "app/ui_controller.py",
        "app/container.py",
        "app/main.py",
    ]
    for f in files:
        py_compile.compile(f, doraise=True)
    print(f"  [OK] {len(files)} files compile")


def main():
    print("Lobuddy 5.8 System Optimization — Functional Test")
    print("=" * 50)

    tests = [
        ("Event Model", test_event_model),
        ("Maintenance Scheduler", test_maintenance_scheduler),
        ("Observability Service", test_observability_service),
        ("PyCompile Check", test_py_compile),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            print(f"\n[{name}]")
            fn()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {e}")
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
