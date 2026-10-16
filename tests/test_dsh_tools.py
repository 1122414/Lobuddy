"""DSH governed effects: denial, cancellation, budgets and path identity."""

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.agent.dsh.tools import GovernedTools, ToolRequest
from core.safety.guardrails import SafetyGuardrails
from core.safety.hitl_approval import HitlApprovalDecision, HitlApprovalRequest


class Approval:
    def __init__(self, mode: str = "allow") -> None:
        self.mode = mode
        self.requested = asyncio.Event()
        self.release = asyncio.Event()

    async def request_approval(self, request: HitlApprovalRequest) -> HitlApprovalDecision:
        self.requested.set()
        if self.mode == "wait":
            await self.release.wait()
        if self.mode == "deny":
            return HitlApprovalDecision.rejected_now(request.request_id)
        return HitlApprovalDecision.approved_now(
            "wrong-id" if self.mode == "wrong" else request.request_id
        )


def write_request(path: str = "result.txt", call: str = "call") -> ToolRequest:
    return ToolRequest.model_validate(
        {
            "callId": call,
            "name": "lobuddy_write_file",
            "arguments": {"path": path, "content": "hello"},
        }
    )


class TestDshGovernance:
    @pytest.mark.parametrize("mode", ["deny", "wrong", "wait"])
    async def test_rejection_and_timeout_have_no_effect(self, tmp_path: Path, mode: str) -> None:
        tools = GovernedTools(tmp_path, Approval(mode), timeout=0 if mode == "wait" else 1)
        with pytest.raises(RuntimeError):
            await tools.execute(
                write_request(), session_id="s", turn_id="t", is_active=lambda: True
            )
        assert not (tmp_path / "result.txt").exists()

    async def test_cancel_while_approval_pending(self, tmp_path: Path) -> None:
        approval = Approval("wait")
        tools = GovernedTools(tmp_path, approval)
        active = True
        task = asyncio.create_task(
            tools.execute(write_request(), session_id="s", turn_id="t", is_active=lambda: active)
        )
        await approval.requested.wait()
        active = False
        approval.release.set()
        with pytest.raises(RuntimeError, match="cancelled"):
            await task
        assert not (tmp_path / "result.txt").exists()

    async def test_approved_write_and_duplicate_not_repeated(self, tmp_path: Path) -> None:
        tools = GovernedTools(tmp_path, Approval())
        await tools.execute(write_request(), session_id="s", turn_id="t", is_active=lambda: True)
        assert (tmp_path / "result.txt").read_text() == "hello"
        (tmp_path / "result.txt").write_text("changed")
        with pytest.raises(RuntimeError, match="Repeated"):
            await tools.execute(
                write_request(), session_id="s", turn_id="t", is_active=lambda: True
            )
        assert (tmp_path / "result.txt").read_text() == "changed"

    @pytest.mark.parametrize(
        "path",
        ["../escape", "..\\escape", ".env", ".git/config", "C:/secret", "nested/../../escape"],
    )
    async def test_protected_and_traversal_paths(self, tmp_path: Path, path: str) -> None:
        approval = Approval()
        tools = GovernedTools(tmp_path, approval)
        with pytest.raises((ValueError, OSError)):
            await tools.execute(
                write_request(path), session_id="s", turn_id="t", is_active=lambda: True
            )
        assert not approval.requested.is_set()

    async def test_symlink_changed_during_approval(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_file = outside / "result.txt"
        outside_file.write_text("preserve")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "nested").mkdir()
        approval = Approval("wait")
        tools = GovernedTools(workspace, approval)
        task = asyncio.create_task(
            tools.execute(
                write_request("nested/result.txt"),
                session_id="s",
                turn_id="t",
                is_active=lambda: True,
            )
        )
        await approval.requested.wait()
        (workspace / "nested").rmdir()
        (workspace / "nested").symlink_to(outside, target_is_directory=True)
        approval.release.set()
        with pytest.raises(OSError):
            await task
        assert outside_file.read_text() == "preserve"

    async def test_budget_and_safe_read(self, tmp_path: Path) -> None:
        (tmp_path / "read.txt").write_text("content")
        tools = GovernedTools(tmp_path, Approval())
        for count in range(6):
            request = ToolRequest.model_validate(
                {
                    "callId": str(count),
                    "name": "lobuddy_read_file",
                    "arguments": {"path": "read.txt"},
                }
            )
            assert (
                await tools.execute(request, session_id="s", turn_id="t", is_active=lambda: True)
                == "content"
            )
        with pytest.raises(RuntimeError, match="budget"):
            await tools.execute(
                write_request(), session_id="s", turn_id="t", is_active=lambda: True
            )
        assert not (tmp_path / "result.txt").exists()

    def test_unmapped_tool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ToolRequest.model_validate(
                {"callId": "x", "name": "exec", "arguments": {"command": "echo hi"}}
            )

    def test_foreign_paths_are_checked_before_native_resolution(self, tmp_path: Path) -> None:
        guards = SafetyGuardrails(tmp_path)
        assert guards.validate_path("..\\outside")
        assert guards.validate_path("D:/outside")
        assert guards.validate_path("safe/file.txt") is None

    def test_unresolvable_protected_root_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        guards = SafetyGuardrails(tmp_path)

        def unavailable_home() -> Path:
            raise RuntimeError("No home directory")

        monkeypatch.setattr(Path, "home", unavailable_home)
        assert guards._is_protected_delete_target(tmp_path / "file.txt")
