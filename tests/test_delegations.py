"""PA-01: explicit authority, durable requests, late events and verified outcomes."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import JsonValue, ValidationError

from core.agent.dsh.runtime import BridgeEvent
from core.config import Settings
from core.service.application import ApplicationService
from core.service.delegation_protocol import (
    DelegationChange,
    DelegationConfirm,
    DelegationEdit,
    DelegationSpec,
)
from core.service.protocol import RpcRequest
from core.storage.chat_repo import ChatRepository
from core.storage.db import Database
from core.storage.delegation_repo import DelegationRepository


def spec(**values: object) -> DelegationSpec:
    return DelegationSpec.model_validate(
        {
            "goal": "整理本次资料",
            "kind": "source-digest",
            "sources": ["note.txt"],
            "criteria": ["资料来源覆盖且引用可追溯"],
            **values,
        }
    )


@pytest.fixture
def repository(tmp_path: Path) -> DelegationRepository:
    settings = Settings(
        llm_api_key="synthetic", data_dir=tmp_path / "data", workspace_path=tmp_path
    )
    db = Database(settings)
    db.init_database(allow_desktop=True)
    ChatRepository(db)
    return DelegationRepository(db, lambda: 1000.0)


def ready(repo: DelegationRepository):
    value = repo.create("create", spec())
    return repo.change(
        "confirm",
        "confirm",
        DelegationConfirm(delegation_id=value.id, revision=value.revision, expires_at=2000.0),
    )


class TestDelegationIdentity:
    def test_creation_survives_restart_and_request_replay(self, repository):
        first = repository.create("one", spec())
        second = DelegationRepository(repository.db, repository.clock)
        assert second.create("one", spec()).id == first.id
        assert second.get(first.id) == first
        assert len(second.list()) == 1
        with pytest.raises(ValueError, match="请求 ID"):
            second.create("one", spec(goal="另一件事"))

    def test_confirmation_is_explicit_revision_checked_and_replayable(self, repository):
        draft = repository.create("create", spec())
        with pytest.raises(ValueError, match="就绪"):
            repository.claim("run", DelegationChange(delegation_id=draft.id, revision=1), "v1")
        confirmed = ready(repository)
        assert confirmed.status == "ready" and confirmed.authorized_at == 1000
        assert confirmed.revision == 2
        with pytest.raises(ValueError, match="已更新"):
            repository.change(
                "stale", "cancel", DelegationChange(delegation_id=draft.id, revision=1)
            )
        assert ready(repository) == confirmed

    @pytest.mark.parametrize("action,status", [("pause", "paused"), ("cancel", "cancelled")])
    def test_pausing_and_cancelling_are_not_failures(self, repository, action, status):
        value = ready(repository)
        changed = repository.change(
            "action", action, DelegationChange(delegation_id=value.id, revision=2)
        )
        assert changed.status == status
        assert (
            repository.change(
                "action", action, DelegationChange(delegation_id=value.id, revision=2)
            )
            == changed
        )
        with pytest.raises(ValueError):
            repository.claim(
                "late", DelegationChange(delegation_id=value.id, revision=changed.revision), "v1"
            )

    def test_edit_invalidates_authority_and_preserves_revisions(self, repository):
        value = ready(repository)
        edited = repository.change(
            "edit",
            "edit",
            DelegationEdit(delegation_id=value.id, revision=2, spec=spec(goal="更新目标")),
        )
        assert edited.status == "draft" and edited.expires_at is None
        assert len(repository.detail(value.id).revisions) == 3
        with pytest.raises(ValueError):
            repository.claim("run", DelegationChange(delegation_id=value.id, revision=3), "v1")

    def test_pause_resume_without_run_retains_scope(self, repository):
        value = ready(repository)
        repository.change("pause", "pause", DelegationChange(delegation_id=value.id, revision=2))
        resumed = repository.change(
            "resume", "resume", DelegationChange(delegation_id=value.id, revision=3)
        )
        assert resumed.status == "ready" and resumed.spec == value.spec

    @pytest.mark.parametrize("expires", [999.0, 1000.0])
    def test_expired_confirmation_rejected(self, repository, expires):
        value = repository.create("create", spec())
        with pytest.raises(ValueError, match="有效期"):
            repository.change(
                "confirm",
                "confirm",
                DelegationConfirm(delegation_id=value.id, revision=1, expires_at=expires),
            )

    def test_confirmation_expires_before_execution(self, repository):
        value = ready(repository)
        repository.clock = lambda: 2000.0
        with pytest.raises(ValueError, match="到期"):
            repository.claim("late", DelegationChange(delegation_id=value.id, revision=2), "v1")

    @pytest.mark.parametrize(
        "source", [{"session_id": "missing"}, {"source_message_id": "missing"}]
    )
    def test_forged_source_is_rejected(self, repository, source):
        with pytest.raises(ValueError, match="来源"):
            repository.create("bad", spec(**source))


class TestDelegationRun:
    def test_claim_is_unique_and_pins_version(self, repository):
        value = ready(repository)
        params = DelegationChange(delegation_id=value.id, revision=2)
        run, created = repository.claim("trigger", params, "v1")
        repeated, created_twice = repository.claim("trigger", params, "v2")
        assert created and not created_twice and run == repeated and run.workflow_version == "v1"
        with pytest.raises(ValueError):
            repository.claim("another", params, "v2")
        repository.bind(run.id, "turn1")
        with pytest.raises(ValueError):
            repository.bind(run.id, "turn2")

    @pytest.mark.parametrize(
        "status,verdict,expected",
        [
            ("completed", "verified", "completed"),
            ("completed", "unknown", "needs_review"),
            ("failed", "failed", "failed"),
            ("cancelled", "unknown", "needs_review"),
        ],
    )
    def test_execution_completion_is_not_goal_success(self, repository, status, verdict, expected):
        value = ready(repository)
        run, _ = repository.claim(
            "trigger", DelegationChange(delegation_id=value.id, revision=2), "v1"
        )
        repository.bind(run.id, "turn")
        repository.settle("turn", status, verdict, "trusted evidence")
        settled = repository.detail(value.id)
        repository.settle("turn", status, verdict, "duplicate")
        assert repository.detail(value.id) == settled
        assert settled.delegation.status == expected
        assert settled.runs[0].verdict == verdict

    @pytest.mark.parametrize("action", ["pause", "cancel"])
    def test_late_success_cannot_revive_mutated_delegation(self, repository, action):
        value = ready(repository)
        run, _ = repository.claim(
            "trigger", DelegationChange(delegation_id=value.id, revision=2), "v1"
        )
        repository.bind(run.id, "turn")
        changed = repository.change(
            "change", action, DelegationChange(delegation_id=value.id, revision=3)
        )
        assert not repository.active(run.id)
        repository.settle("turn", "completed", "verified", "late evidence")
        assert repository.get(value.id) == changed
        assert repository.detail(value.id).runs[0].verdict == "verified"

    def test_restart_marks_unknown_and_never_replays(self, repository):
        value = ready(repository)
        run, _ = repository.claim(
            "trigger", DelegationChange(delegation_id=value.id, revision=2), "v1"
        )
        restarted = DelegationRepository(repository.db, repository.clock)
        restarted.recover()
        once = restarted.detail(value.id)
        restarted.recover()
        assert once == restarted.detail(value.id)
        assert once.delegation.status == "needs_review"
        assert once.runs[0].status == "interrupted" and once.runs[0].verdict == "unknown"
        assert not restarted.active(run.id)


@pytest.mark.parametrize(
    "bad",
    [
        {"goal": " "},
        {"max_tool_calls": 0},
        {"timeout_seconds": 601},
        {"sources": []},
        {"kind": "shell"},
        {"sources": [""]},
        {"criteria": ["模型说完成了"]},
        {"output_directory": "unauthorized"},
        {"extra": "not allowed"},
        {"wait": {"kind": "time"}},
        {"wait": {"timezone": "No/SuchZone"}},
        {"wait": {"kind": "event", "event": "delegation_completed"}},
    ],
)
def test_invalid_scope_and_wait_are_rejected(bad):
    with pytest.raises(ValidationError):
        spec(**bad)


class Backend:
    def __init__(self) -> None:
        self.ready = asyncio.Event()

    async def start(self) -> None:
        raise AssertionError("Synthetic workflow must not call the model")

    async def close(self) -> None:
        pass

    async def call(self, method: str, params: dict[str, JsonValue]) -> JsonValue:
        raise AssertionError("Synthetic workflow must not call the model")

    async def events(self) -> AsyncIterator[BridgeEvent]:
        while True:
            await asyncio.sleep(1)
            if False:
                yield BridgeEvent.model_validate({})


async def rpc(service, method, params, identity=None):
    return await service.handle(
        RpcRequest(jsonrpc="2.0", id=identity or uuid.uuid4().hex, method=method, params=params)
    )


class TestDelegationService:
    def test_queue_execution_deduplication_and_cross_session_history(self, tmp_path):
        async def run():
            settings = Settings(
                llm_api_key="synthetic",
                data_dir=tmp_path / "data",
                workspace_path=tmp_path / "workspace",
            )
            settings.workspace_path.mkdir()
            (settings.workspace_path / "note.txt").write_text("决定：保留来源。\n待办：测试委托。")
            db = Database(settings)
            db.init_database(allow_desktop=True)
            events = []
            service = ApplicationService(settings, db, Backend(), events.append)
            try:
                await rpc(service, "learning.configure", {"enabled": False})
                draft = await rpc(
                    service, "delegation.create", spec().model_dump(mode="json"), "create"
                )
                await rpc(
                    service,
                    "delegation.confirm",
                    {"delegation_id": draft["id"], "revision": 1, "expires_at": time.time() + 3600},
                )
                params = {"delegation_id": draft["id"], "revision": 2}
                first = await rpc(service, "delegation.run", params, "execute")
                async with asyncio.timeout(5):
                    while service.delegation_repo.get(draft["id"]).status == "running":
                        await asyncio.sleep(0.01)
                repeated = await rpc(service, "delegation.run", params, "execute")
                assert first["id"] == repeated["id"] and repeated["verdict"] == "verified"
                await rpc(service, "session.create", {"title": "另一个会话"})
                result = await rpc(service, "delegation.get", {"delegation_id": draft["id"]})
                assert result["delegation"]["status"] == "completed" and len(result["runs"]) == 1
                assert any(
                    event.delegation_id == draft["id"] and event.run_id == first["id"]
                    for event in events
                )
            finally:
                await service.close()

        asyncio.run(run())
