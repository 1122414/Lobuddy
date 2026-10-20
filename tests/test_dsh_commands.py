"""Governed commands cannot bypass approval, file boundaries or cancellation."""

import asyncio
from pathlib import Path

import pytest

from core.agent.dsh.commands import command_arguments, run_command
from core.agent.dsh.tools import GovernedTools, ToolRequest
from core.config import Settings
from core.safety.hitl_approval import HitlApprovalDecision, HitlApprovalRequest


class Approval:
    def __init__(self, approve: bool) -> None:
        self.approve = approve
        self.requests = 0

    async def request_approval(self, request: HitlApprovalRequest) -> HitlApprovalDecision:
        self.requests += 1
        return (
            HitlApprovalDecision.approved_now if self.approve else HitlApprovalDecision.rejected_now
        )(request.request_id)


class TestDshCommands:
    @pytest.mark.parametrize(
        "command",
        [
            "echo ok; rm a",
            "find . -exec cat .env ;",
            "python3 script.py",
            "curl https://example.com",
            "git -c core.pager=malicious log",
            "ls -R",
            "cp -r a b",
        ],
    )
    def test_unmapped_and_escaping_commands_denied(self, tmp_path: Path, command: str) -> None:
        with pytest.raises(ValueError):
            command_arguments(command, tmp_path)

    @pytest.mark.parametrize("approved", [False, True])
    async def test_creation_requires_approval(self, tmp_path: Path, approved: bool) -> None:
        approval = Approval(approved)
        tools = GovernedTools(tmp_path, approval, settings=Settings(llm_api_key="test"))
        request = ToolRequest(
            callId="one", name="lobuddy_exec", arguments={"command": "touch result.txt"}
        )
        if approved:
            assert "退出码 0" in await tools.execute(
                request, session_id="s", turn_id="t", is_active=lambda: True
            )
        else:
            with pytest.raises(RuntimeError, match="denied"):
                await tools.execute(request, session_id="s", turn_id="t", is_active=lambda: True)
        assert (tmp_path / "result.txt").exists() == approved
        assert approval.requests == 1

    async def test_protected_and_symlink_paths_never_reach_approval(self, tmp_path: Path) -> None:
        secret = tmp_path / ".env"
        secret.write_text("synthetic")
        (tmp_path / "ordinary.txt").symlink_to(secret)
        approval = Approval(True)
        tools = GovernedTools(tmp_path, approval, settings=Settings(llm_api_key="test"))
        for index, command in enumerate(
            ["cat ordinary.txt", "touch USER.md", "cat .ENV", "cat /etc/passwd"]
        ):
            with pytest.raises(ValueError):
                await tools.execute(
                    ToolRequest(
                        callId=str(index), name="lobuddy_exec", arguments={"command": command}
                    ),
                    session_id="s",
                    turn_id=str(index),
                    is_active=lambda: True,
                )
        assert approval.requests == 0

    async def test_cancel_terminates_owned_process(self, tmp_path: Path) -> None:
        # Sleep is used only to test the process executor, never admitted as a model tool.
        task = asyncio.create_task(run_command(["/bin/sleep", "30"], tmp_path, 60, 100))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)

    async def test_output_is_bounded(self, tmp_path: Path) -> None:
        result = await run_command(["/bin/echo", "a" * 10000], tmp_path, 5, 100)
        assert len(result) < 150 and "截断" in result
