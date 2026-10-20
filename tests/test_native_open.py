"""Bounded candidate provenance, approval and platform dispatch."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.agent.dsh.tools import GovernedTools, ToolRequest
from core.safety.hitl_approval import HitlApprovalDecision, HitlApprovalRequest
from core.services.local_open import LocalOpenService, open_native


class Approval:
    def __init__(self, approved: bool) -> None:
        self.approved = approved

    async def request_approval(self, request: HitlApprovalRequest) -> HitlApprovalDecision:
        return (
            HitlApprovalDecision.approved_now(request.request_id)
            if self.approved
            else HitlApprovalDecision.rejected_now(request.request_id)
        )


class TestNativeOpen:
    def test_candidates_exclude_scripts_links_and_changed_files(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        service = LocalOpenService(tmp_path)
        monkeypatch.setattr(service, "sources", lambda: [("test", tmp_path)])
        file = tmp_path / "demo.txt"
        file.write_text("hello")
        (tmp_path / "demo.sh").write_text("exit 0")
        (tmp_path / "demo-link.txt").symlink_to(file)
        result = service.resolve("demo")
        assert len(result) == 1 and result[0]["path"] == str(file)
        assert service.validate(str(file)) == file
        file.write_text("changed")
        with pytest.raises(ValueError, match="变化"):
            service.validate(str(file))
        with pytest.raises(ValueError, match="候选"):
            service.validate("/Applications/Unknown.app")

    @pytest.mark.parametrize("approved", [False, True])
    async def test_governed_open_checks_candidate_and_approval(
        self, tmp_path: Path, monkeypatch, approved: bool
    ) -> None:
        (tmp_path / "demo.txt").write_text("test")
        tools = GovernedTools(tmp_path, Approval(approved))
        monkeypatch.setattr(tools.local, "sources", lambda: [("test", tmp_path)])
        opened = AsyncMock()
        monkeypatch.setattr("core.agent.dsh.tools.open_native", opened)

        async def execute(call_id: str, name: str, args: dict):
            return await tools.execute(
                ToolRequest(callId=call_id, name=name, arguments=args),
                session_id="session",
                turn_id="turn",
                is_active=lambda: True,
            )

        result = json.loads(await execute("lookup", "lobuddy_local_resolve", {"query": "demo"}))
        if approved:
            await execute("open", "lobuddy_local_open", {"path": result[0]["path"]})
            opened.assert_awaited_once_with(tmp_path / "demo.txt")
            with pytest.raises(RuntimeError, match="one local open"):
                await execute("again", "lobuddy_local_open", {"path": result[0]["path"]})
        else:
            with pytest.raises(RuntimeError, match="denied"):
                await execute("open", "lobuddy_local_open", {"path": result[0]["path"]})
            opened.assert_not_awaited()

    async def test_macos_uses_argument_vector_and_no_secret_environment(self, monkeypatch) -> None:
        monkeypatch.setattr("core.services.local_open.sys.platform", "darwin")
        monkeypatch.setenv("LLM_API_KEY", "fixture-must-not-be-inherited")
        child = AsyncMock()
        child.returncode = 0
        spawn = AsyncMock(return_value=child)
        monkeypatch.setattr("core.services.local_open.asyncio.create_subprocess_exec", spawn)
        await open_native(Path("/tmp/file with spaces.txt"))
        assert spawn.call_args.args == ("/usr/bin/open", "/tmp/file with spaces.txt")
        assert "LLM_API_KEY" not in spawn.call_args.kwargs["env"]
