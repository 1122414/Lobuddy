"""Tests for HITL approval protocol and deny-all provider."""
import asyncio

import pytest

from core.safety.hitl_approval import (
    DenyAllHitlApprovalProvider,
    HitlApprovalDecision,
    HitlApprovalRequest,
    request_approval_with_timeout,
)


class TestHitlApprovalProtocol:
    def test_deny_all_provider_rejects(self):
        provider = DenyAllHitlApprovalProvider()
        request = HitlApprovalRequest.create(
            session_id="test-session",
            tool_name="exec",
            command="rm temp.txt",
            reason="delete command",
        )

        async def run():
            return await provider.request_approval(request)

        decision = asyncio.run(run())
        assert decision.approved is False
        assert "not available" in decision.reason

    def test_approval_request_immutable(self):
        request = HitlApprovalRequest.create(
            session_id="test",
            tool_name="exec",
            command="rm tmp.txt",
        )
        with pytest.raises(Exception):
            request.approved = True  # type: ignore

    def test_decision_factory_methods(self):
        approved = HitlApprovalDecision.approved_now("req-1", "user confirmed")
        assert approved.approved is True
        assert approved.request_id == "req-1"

        rejected = HitlApprovalDecision.rejected_now("req-2", "user cancelled")
        assert rejected.approved is False

    def test_timeout_wrapper_rejects_on_timeout(self):
        class SlowProvider:
            async def request_approval(self, request):
                await asyncio.sleep(10)

        provider = SlowProvider()
        request = HitlApprovalRequest.create(
            session_id="test",
            tool_name="exec",
            command="rm tmp.txt",
            timeout_seconds=1,
        )

        async def run():
            return await request_approval_with_timeout(provider, request)

        decision = asyncio.run(run())
        assert decision.approved is False
        assert "timed out" in decision.reason

    def test_request_create_generates_unique_id(self):
        r1 = HitlApprovalRequest.create(session_id="s1", tool_name="exec", command="ls")
        r2 = HitlApprovalRequest.create(session_id="s2", tool_name="exec", command="ls")
        assert r1.request_id != r2.request_id

    def test_import_does_not_depend_on_qt(self):
        from core.safety.hitl_approval import HitlApprovalProvider

        assert HitlApprovalProvider is not None
