"""Workflow UI requests use durable turns, ordinary approvals and explicit cancellation."""

import asyncio
from pathlib import Path

import pytest

from tests.test_headless_service import call, make_service


async def finished(service, identity):
    async with asyncio.timeout(4):
        while service.repo.get(identity).status in ("queued", "running"):
            await asyncio.sleep(0.005)
    return service.repo.get(identity)


class TestWorkflowService:
    async def test_durable_workflow_request_and_outcome_without_engine(self, tmp_path: Path):
        service, backend = make_service(tmp_path, [])
        try:
            (service.settings.workspace_path / "note.txt").write_text("决定保持简短\n待办：测试")
            session = await call(service, "session.create", {}, "session")
            args = {
                "session_id": session["id"],
                "text": "归纳 note.txt",
                "workflow_id": "source-digest",
                "workflow_input": {"sources": ["note.txt"]},
                "lane": "background",
            }
            turn = await call(service, "turn.send", args, "send")
            state = await finished(service, turn["turn_id"])
            assert (
                state.status == "completed" and state.workflow_version == "builtin-source-digest-1"
            )
            assert service.ledger.outcomes.get(state.turn_id).verdict == "verified"
            assert (await call(service, "turn.send", args, "send"))["turn_id"] == turn["turn_id"]
            assert not backend.sent
            assert len(service.repo.list_turns()) == 1
        finally:
            await service.close()

    async def test_workflow_copy_approval_cancel_no_effect(self, tmp_path: Path):
        service, backend = make_service(tmp_path, [])
        try:
            (service.settings.workspace_path / "input").mkdir()
            (service.settings.workspace_path / "input/note.txt").write_text("test")
            session = await call(service, "session.create", {}, "session")
            turn = await call(
                service,
                "turn.send",
                {
                    "session_id": session["id"],
                    "text": "复制 input 到 output",
                    "workflow_id": "organize-files",
                    "workflow_input": {"source": "input", "output": "output"},
                    "lane": "background",
                },
                "send",
            )
            async with asyncio.timeout(4):
                while not service.approvals:
                    await asyncio.sleep(0.005)
            await service.cancel(turn["turn_id"])
            state = await finished(service, turn["turn_id"])
            assert state.status == "cancelled"
            assert service.ledger.outcomes.get(state.turn_id).verdict == "unknown"
            assert not (service.settings.workspace_path / "output").exists()
            assert not backend.sent
        finally:
            await service.close()

    async def test_disabled_workflow_rejects_before_submission(self, tmp_path: Path):
        service, _ = make_service(tmp_path, [])
        try:
            session = await call(service, "session.create", {}, "session")
            service.knowledge.workflows.disable("builtin-source-digest-1")
            with pytest.raises(ValueError):
                await call(
                    service,
                    "turn.send",
                    {
                        "session_id": session["id"],
                        "text": "归纳",
                        "workflow_id": "source-digest",
                        "workflow_input": {"sources": ["note.txt"]},
                    },
                    "send",
                )
            assert service.repo.list_turns() == []
        finally:
            await service.close()
