"""Integration tests for _ToolTracker HITL behavior (P0-4).

Tests _ToolTracker.before_execute_tools() with fake HitlApprovalProvider
to verify the full HITL approval pipeline.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from core.safety.hitl_approval import (
    HitlApprovalDecision,
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


class CapturingApproveProvider:
    def __init__(self):
        self.requests = []

    async def request_approval(self, request):
        self.requests.append(request)
        return HitlApprovalDecision.approved_now(request.request_id, "approved by test")


class FakeComputerCoordinator:
    def __init__(self, high_impact=False):
        self.authorized: list[str] = []
        self.high_impact_grants = []
        self.validated = []
        self.high_impact = high_impact

    def authorization_preview(self, plan_id):
        return f"plan={plan_id}; max_actions=3; no screenshots persisted"

    def authorize_plan(self, plan_id):
        self.authorized.append(plan_id)

    def validate_action_request(self, plan_id, action):
        self.validated.append((plan_id, action))

    def requires_individual_confirmation(self, action):
        return self.high_impact

    def grant_high_impact_action(self, plan_id, action):
        self.high_impact_grants.append((plan_id, action))


class FakeExecTool:
    name = "exec"
    description = "fake exec"
    parameters = {}
    read_only = False
    concurrency_safe = False
    exclusive = True

    def __init__(self):
        self.calls = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return "executed"


@pytest.fixture
def guardrails():
    with tempfile.TemporaryDirectory() as tmpdir:
        from core.safety.guardrails import SafetyGuardrails

        yield SafetyGuardrails(Path(tmpdir))


def _make_tracker(
    guardrails,
    provider=None,
    guardrails_enabled=True,
    computer_use_coordinator=None,
):
    from core.agent.nanobot_adapter import _ToolTracker

    return _ToolTracker(
        guardrails=guardrails,
        guardrails_enabled=guardrails_enabled,
        hitl_approval_provider=provider,
        session_id="test-session",
        hitl_timeout_seconds=5,
        computer_use_coordinator=computer_use_coordinator,
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


class TestComputerUseHitl:
    def test_plan_authorization_requires_approval_and_activates_plan(self, guardrails):
        provider = CapturingApproveProvider()
        coordinator = FakeComputerCoordinator()
        tracker = _make_tracker(
            guardrails,
            provider=provider,
            computer_use_coordinator=coordinator,
        )
        ctx = FakeContext(
            [FakeToolCall("computer_authorize", {"plan_id": "plan-1"})]
        )

        asyncio.run(tracker.before_execute_tools(ctx))

        assert coordinator.authorized == ["plan-1"]
        assert provider.requests[0].tool_name == "computer_authorize"
        assert "max_actions=3" in provider.requests[0].command
        assert "computer_authorize" in tracker.tools_used

    def test_plan_rejection_does_not_activate_plan(self, guardrails):
        coordinator = FakeComputerCoordinator()
        tracker = _make_tracker(
            guardrails,
            provider=RejectProvider(),
            computer_use_coordinator=coordinator,
        )
        ctx = FakeContext(
            [FakeToolCall("computer_authorize", {"plan_id": "plan-1"})]
        )

        with pytest.raises(HumanApprovalDenied):
            asyncio.run(tracker.before_execute_tools(ctx))

        assert coordinator.authorized == []

    def test_high_impact_action_gets_separate_confirmation_without_text_leak(
        self,
        guardrails,
    ):
        provider = CapturingApproveProvider()
        coordinator = FakeComputerCoordinator(high_impact=True)
        tracker = _make_tracker(
            guardrails,
            provider=provider,
            computer_use_coordinator=coordinator,
        )
        ctx = FakeContext(
            [
                FakeToolCall(
                    "computer_act",
                    {
                        "plan_id": "plan-1",
                        "action": "type_text",
                        "description": "提交前填写备注",
                        "observation_id": "observation-1",
                        "target_id": "target-note",
                        "target_label": "备注",
                        "target_role": "text field",
                        "expected_outcome": "备注字段显示已填写状态",
                        "text": "private content",
                    },
                )
            ]
        )

        asyncio.run(tracker.before_execute_tools(ctx))

        assert len(coordinator.validated) == 1
        request = provider.requests[0]
        assert request.tool_name == "computer_act"
        assert "private content" not in request.command
        assert "text_length=15" in request.command
        assert "目标：备注 · text field" in request.command
        assert "预期结果：备注字段显示已填写状态" in request.command
        assert "high_impact" in request.risk_tags
        assert len(coordinator.high_impact_grants) == 1

    def test_low_impact_action_validates_without_extra_dialog(self, guardrails):
        provider = CapturingApproveProvider()
        coordinator = FakeComputerCoordinator(high_impact=False)
        tracker = _make_tracker(
            guardrails,
            provider=provider,
            computer_use_coordinator=coordinator,
        )
        ctx = FakeContext(
            [
                FakeToolCall(
                    "computer_act",
                    {
                        "plan_id": "plan-1",
                        "action": "click",
                        "description": "打开主题列表",
                        "observation_id": "observation-1",
                        "target_id": "target-theme",
                        "target_label": "主题",
                        "target_role": "button",
                        "expected_outcome": "主题列表可见",
                        "x": 20,
                        "y": 30,
                    },
                )
            ]
        )

        asyncio.run(tracker.before_execute_tools(ctx))

        assert len(coordinator.validated) == 1
        assert provider.requests == []
        assert "computer_act" in tracker.tools_used


class TestFailClosedToolBoundary:
    def test_rejected_shell_command_cannot_execute_after_hook_error_is_swallowed(
        self,
        guardrails,
    ):
        from core.agent.tools.governed_tool_proxy import GovernedToolProxy

        ws = guardrails.workspace_path
        target = ws / "test.txt"
        target.write_text("test")
        tracker = _make_tracker(guardrails, provider=RejectProvider())
        arguments = {"command": f"rm {target}", "working_dir": str(ws)}
        context = FakeContext([FakeToolCall("exec", arguments)])
        with pytest.raises(HumanApprovalDenied):
            asyncio.run(tracker.before_execute_tools(context))

        delegate = FakeExecTool()
        proxy = GovernedToolProxy(delegate, tracker)
        result = asyncio.run(proxy.execute(**arguments))

        assert "not approved" in result
        assert delegate.calls == []

    def test_approved_shell_command_receives_one_execution_grant(self, guardrails):
        from core.agent.tools.governed_tool_proxy import GovernedToolProxy

        ws = guardrails.workspace_path
        target = ws / "test.txt"
        target.write_text("test")
        tracker = _make_tracker(guardrails, provider=ApproveProvider())
        arguments = {"command": f"rm {target}", "working_dir": str(ws)}
        asyncio.run(
            tracker.before_execute_tools(
                FakeContext([FakeToolCall("exec", arguments)])
            )
        )
        delegate = FakeExecTool()
        proxy = GovernedToolProxy(delegate, tracker)

        assert asyncio.run(proxy.execute(**arguments)) == "executed"
        assert "not approved" in asyncio.run(proxy.execute(**arguments))
        assert len(delegate.calls) == 1
