"""Integration tests for _ToolTracker HITL behavior (P0-4).

Tests _ToolTracker.before_execute_tools() with fake HitlApprovalProvider
to verify the full HITL approval pipeline.
"""

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from core.safety.hitl_approval import (
    HitlApprovalDecision,
    HitlApprovalRequest,
)
from core.safety.command_risk import HumanApprovalDenied


class FakeToolCall:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeContext:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


class ApproveProvider:
    async def request_approval(self, request):
        return HitlApprovalDecision.approved_now(request.request_id, "approved by test")


class RejectProvider:
    async def request_approval(self, request):
        return HitlApprovalDecision.rejected_now(request.request_id, "rejected by test")


class TimeoutProvider:
    async def request_approval(self, request):
        await asyncio.sleep(10)


class ErrorProvider:
    async def request_approval(self, request):
        raise RuntimeError("provider failed")


@pytest.fixture
def guardrails():
    with tempfile.TemporaryDirectory() as tmpdir:
        from core.safety.guardrails import SafetyGuardrails

        yield SafetyGuardrails(Path(tmpdir))


def _make_tracker(guardrails, provider=None, guardrails_enabled=True):
    from core.agent.nanobot_adapter import _ToolTracker

    return _ToolTracker(
        guardrails=guardrails,
        guardrails_enabled=guardrails_enabled,
        hitl_approval_provider=provider,
        session_id="test-session",
        hitl_timeout_seconds=5,
    )


class TestToolTrackerHitl:
    def test_provider_approve_allows_command(self, guardrails, monkeypatch):
        ws = guardrails.workspace_path
        target = ws / "test.txt"
        target.write_text("test")

        tracker = _make_tracker(guardrails, provider=ApproveProvider())
        tc = FakeToolCall("exec", {"command": f"rm {target}", "working_dir": str(ws)})
        ctx = FakeContext([tc])

        async def run():
            await tracker.before_execute_tools(ctx)

        asyncio.run(run())
        assert "exec" in tracker.tools_used

    def test_provider_reject_raises_human_approval_denied(self, guardrails):
        ws = guardrails.workspace_path
        target = ws / "test.txt"
        target.write_text("test")

        tracker = _make_tracker(guardrails, provider=RejectProvider())
        tc = FakeToolCall("exec", {"command": f"rm {target}", "working_dir": str(ws)})
        ctx = FakeContext([tc])

        async def run():
            await tracker.before_execute_tools(ctx)

        with pytest.raises(HumanApprovalDenied):
            asyncio.run(run())
        assert "exec" not in tracker.tools_used

    def test_no_provider_denies_command(self, guardrails):
        ws = guardrails.workspace_path
        target = ws / "test.txt"
        target.write_text("test")

        tracker = _make_tracker(guardrails, provider=None)
        tc = FakeToolCall("exec", {"command": f"rm {target}", "working_dir": str(ws)})
        ctx = FakeContext([tc])

        async def run():
            await tracker.before_execute_tools(ctx)

        with pytest.raises(HumanApprovalDenied):
            asyncio.run(run())

    def test_multiple_hitl_commands_rejected(self, guardrails):
        ws = guardrails.workspace_path
        (ws / "a.txt").write_text("a")
        (ws / "b.txt").write_text("b")

        tracker = _make_tracker(guardrails, provider=ApproveProvider())
        tcs = [
            FakeToolCall("exec", {"command": f"rm {ws / 'a.txt'}", "working_dir": str(ws)}),
            FakeToolCall("exec", {"command": f"rm {ws / 'b.txt'}", "working_dir": str(ws)}),
        ]
        ctx = FakeContext(tcs)

        async def run():
            await tracker.before_execute_tools(ctx)

        with pytest.raises(RuntimeError) as exc_info:
            asyncio.run(run())
        assert "Multiple dangerous commands" in str(exc_info.value)

    def test_safe_command_passes_through(self, guardrails):
        tracker = _make_tracker(guardrails)
        tc = FakeToolCall("exec", {"command": "ls -la", "working_dir": str(guardrails.workspace_path)})
        ctx = FakeContext([tc])

        async def run():
            await tracker.before_execute_tools(ctx)

        asyncio.run(run())
        assert "exec" in tracker.tools_used

    def test_deny_command_raises_runtime_error(self, guardrails):
        tracker = _make_tracker(guardrails)
        tc = FakeToolCall("exec", {"command": "format C:"})
        ctx = FakeContext([tc])

        async def run():
            await tracker.before_execute_tools(ctx)

        with pytest.raises(RuntimeError) as exc_info:
            asyncio.run(run())
        assert "blocked" in str(exc_info.value).lower()

    def test_guardrails_disabled_still_triggers_hitl(self, guardrails):
        ws = guardrails.workspace_path
        target = ws / "test.txt"
        target.write_text("test")

        tracker = _make_tracker(guardrails, provider=RejectProvider(), guardrails_enabled=False)
        tc = FakeToolCall("exec", {"command": f"rm {target}", "working_dir": str(ws)})
        ctx = FakeContext([tc])

        async def run():
            await tracker.before_execute_tools(ctx)

        with pytest.raises(HumanApprovalDenied):
            asyncio.run(run())

    def test_timeout_provider_rejects(self, guardrails):
        ws = guardrails.workspace_path
        target = ws / "test.txt"
        target.write_text("test")

        tracker = _make_tracker(
            guardrails, provider=TimeoutProvider(), guardrails_enabled=True
        )
        tracker._hitl_timeout_seconds = 1
        tc = FakeToolCall("exec", {"command": f"rm {target}", "working_dir": str(ws)})
        ctx = FakeContext([tc])

        async def run():
            await tracker.before_execute_tools(ctx)

        with pytest.raises(HumanApprovalDenied):
            asyncio.run(run())

    def test_error_provider_rejects(self, guardrails):
        ws = guardrails.workspace_path
        target = ws / "test.txt"
        target.write_text("test")

        tracker = _make_tracker(guardrails, provider=ErrorProvider())
        tc = FakeToolCall("exec", {"command": f"rm {target}", "working_dir": str(ws)})
        ctx = FakeContext([tc])

        async def run():
            await tracker.before_execute_tools(ctx)

        with pytest.raises(HumanApprovalDenied):
            asyncio.run(run())
