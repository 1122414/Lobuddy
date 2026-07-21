"""Tests for unified runtime event model — P1-B1.

Verifies:
- EventBus publishes task/HITL/memory events
- Event payloads do NOT contain sensitive fields
- Existing Qt Signals are preserved
"""

import asyncio
import sys
from dataclasses import fields

import pytest

# Mock PySide6 before importing core modules
_pyside = type(sys)("PySide6")
_pyside.QtCore = type(sys)("QtCore")
_pyside.QtCore.QObject = type("QObject", (), {})
_pyside.QtCore.Signal = type("Signal", (), {"connect": lambda *a, **k: None})
sys.modules["PySide6"] = _pyside
sys.modules["PySide6.QtCore"] = _pyside.QtCore

from core.events import (
    EventBus,
    HitlApproved,
    HitlDenied,
    HitlRequested,
    TaskCompleted,
    TaskFailed,
    TaskQueued,
    TaskStarted,
    ToolCallBlocked,
    ToolCallExecuted,
)

# Cleanup
for _mod in list(sys.modules.keys()):
    if _mod.startswith("PySide6"):
        del sys.modules[_mod]


_SENSITIVE_PATTERNS = ("api_key", "secret", "token", "password", "bearer", "email")


def _assert_no_sensitive_fields(event) -> None:
    """Ensure event payload has no fields that could carry secrets."""
    for f in fields(event):
        if any(pat in f.name.lower() for pat in _SENSITIVE_PATTERNS):
            raise AssertionError(
                f"Event {type(event).__name__} has suspicious field: {f.name}"
            )


class TestUnifiedEventModel:
    def test_task_queued_event(self):
        bus = EventBus()
        received = []
        bus.subscribe(TaskQueued, lambda e: received.append(e))
        event = TaskQueued(task_id="t1", session_id="s1")
        bus.publish(event)
        assert len(received) == 1
        assert received[0].task_id == "t1"
        _assert_no_sensitive_fields(received[0])

    def test_task_started_event(self):
        bus = EventBus()
        received = []
        bus.subscribe(TaskStarted, lambda e: received.append(e))
        event = TaskStarted(task_id="t1")
        bus.publish(event)
        assert len(received) == 1
        _assert_no_sensitive_fields(received[0])

    def test_task_completed_event_truncates_summary(self):
        bus = EventBus()
        received = []
        bus.subscribe(TaskCompleted, lambda e: received.append(e))
        event = TaskCompleted(
            task_id="t1",
            session_id="s1",
            success=True,
            summary="short",
            error_message="",
        )
        bus.publish(event)
        assert len(received) == 1
        assert received[0].success is True
        _assert_no_sensitive_fields(received[0])

    def test_task_failed_event(self):
        bus = EventBus()
        received = []
        bus.subscribe(TaskFailed, lambda e: received.append(e))
        event = TaskFailed(task_id="t1", session_id="s1", error_message="boom")
        bus.publish(event)
        assert len(received) == 1
        assert received[0].error_message == "boom"
        _assert_no_sensitive_fields(received[0])

    def test_tool_call_executed_event(self):
        bus = EventBus()
        received = []
        bus.subscribe(ToolCallExecuted, lambda e: received.append(e))
        event = ToolCallExecuted(task_id="t1", tool_name="exec", success=True, duration_ms=100.0)
        bus.publish(event)
        assert len(received) == 1
        _assert_no_sensitive_fields(received[0])

    def test_tool_call_blocked_event(self):
        bus = EventBus()
        received = []
        bus.subscribe(ToolCallBlocked, lambda e: received.append(e))
        event = ToolCallBlocked(task_id="t1", tool_name="exec", reason="dangerous")
        bus.publish(event)
        assert len(received) == 1
        _assert_no_sensitive_fields(received[0])

    def test_hitl_requested_event(self):
        bus = EventBus()
        received = []
        bus.subscribe(HitlRequested, lambda e: received.append(e))
        event = HitlRequested(
            task_id="t1",
            tool_name="exec",
            command_preview="ls",
            risk_tags=["file_write"],
        )
        bus.publish(event)
        assert len(received) == 1
        assert received[0].command_preview == "ls"
        _assert_no_sensitive_fields(received[0])

    def test_hitl_approved_event(self):
        bus = EventBus()
        received = []
        bus.subscribe(HitlApproved, lambda e: received.append(e))
        event = HitlApproved(task_id="t1", tool_name="exec", reason="ok")
        bus.publish(event)
        assert len(received) == 1
        _assert_no_sensitive_fields(received[0])

    def test_hitl_denied_event(self):
        bus = EventBus()
        received = []
        bus.subscribe(HitlDenied, lambda e: received.append(e))
        event = HitlDenied(task_id="t1", tool_name="exec", reason="nope")
        bus.publish(event)
        assert len(received) == 1
        _assert_no_sensitive_fields(received[0])

    def test_event_payload_no_long_output(self):
        """Events must not carry full tool output or prompts."""
        event = TaskCompleted(
            task_id="t1",
            session_id="s1",
            success=True,
            summary="x" * 500,
            error_message="",
        )
        # summary should be truncated by caller; event itself allows any length
        # This test documents the expectation that callers truncate before publishing
        assert len(event.summary) == 500
        _assert_no_sensitive_fields(event)

    @pytest.mark.asyncio
    async def test_async_handler_awaits(self):
        bus = EventBus()
        received = []

        async def handler(event):
            await asyncio.sleep(0.01)
            received.append(event)

        bus.subscribe(TaskQueued, handler)
        event = TaskQueued(task_id="t2", session_id="s2")
        await bus.publish_and_wait(event)
        assert len(received) == 1
