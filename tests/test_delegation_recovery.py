"""PA-01: checkpoint reuse must not bypass provenance, authority or cumulative budgets."""

import asyncio
import sys
import time
from pathlib import Path

import pytest

from core.agent.dsh.practical import PracticalTools
from core.agent.dsh.runtime import DshRuntime
from core.config import Settings
from core.service.application import ApplicationService
from core.service.protocol import RpcRequest
from core.storage.db import Database
from core.storage.runtime_lock import RuntimeLock


def make_service(tmp_path: Path):
    settings = Settings(
        llm_api_key="synthetic-unused",
        data_dir=tmp_path / "data",
        workspace_path=tmp_path / "workspace",
    )
    settings.workspace_path.mkdir(exist_ok=True)
    db = Database(settings)
    db.init_database(allow_desktop=True)
    backend = DshRuntime(
        home=tmp_path / "dsh",
        workspace=settings.workspace_path,
        plugin=tmp_path / "unused",
        api_key="synthetic-unused",
        base_url="https://invalid.example",
        model="unused",
    )
    return ApplicationService(settings, db, backend, lambda event: None)


async def call(service, method, params, identity="request"):
    return await service.handle(
        RpcRequest(jsonrpc="2.0", id=identity, method=method, params=params)
    )


async def interrupted_read(service, monkeypatch):
    await call(service, "learning.configure", {"enabled": False})
    draft = await call(
        service,
        "delegation.create",
        {
            "goal": "归纳资料",
            "kind": "source-digest",
            "sources": ["note.txt"],
            "criteria": ["资料来源覆盖且引用可追溯"],
        },
        "create",
    )
    await call(
        service,
        "delegation.confirm",
        {"delegation_id": draft["id"], "revision": 1, "expires_at": time.time() + 3600},
        "confirm",
    )
    original = service.recovery.save

    def stop_after_checkpoint(identity, values):
        original(identity, values)
        raise asyncio.CancelledError

    monkeypatch.setattr(service.recovery, "save", stop_after_checkpoint)
    run = await call(
        service, "delegation.run", {"delegation_id": draft["id"], "revision": 2}, "run"
    )
    async with asyncio.timeout(3):
        while service.delegation_repo.get(draft["id"]).status == "running":
            await asyncio.sleep(0.01)
    monkeypatch.setattr(service.recovery, "save", original)
    return service.delegation_repo.get(draft["id"]), run


class TestReadonlyRecovery:
    def test_completed_read_is_reused_without_a_second_tool_call(self, tmp_path, monkeypatch):
        async def run():
            service = make_service(tmp_path)
            (service.settings.workspace_path / "note.txt").write_text("决定：使用来源。")
            original = PracticalTools.digest
            count = 0

            async def counted(owner, args, active):
                nonlocal count
                count += 1
                return await original(owner, args, active)

            monkeypatch.setattr(PracticalTools, "digest", counted)
            try:
                value, execution = await interrupted_read(service, monkeypatch)
                assert value.status == "needs_review" and count == 1
                await call(
                    service,
                    "delegation.recover",
                    {
                        "delegation_id": value.id,
                        "revision": value.revision,
                        "action": "resume_readonly",
                    },
                    "resume",
                )
                async with asyncio.timeout(3):
                    while service.delegation_repo.get(value.id).status == "running":
                        await asyncio.sleep(0.01)
                assert service.delegation_repo.get(value.id).status == "completed"
                assert count == 1
                assert service.delegation_repo.detail(value.id).runs[0].id == execution["id"]
                assert not service.backend.ready.is_set()
            finally:
                await service.close()

        asyncio.run(run())

    @pytest.mark.parametrize("change", ["content", "missing", "expired", "disabled"])
    def test_changed_sources_expired_authority_and_disabled_version_cannot_resume(
        self, tmp_path, monkeypatch, change
    ):
        async def run():
            service = make_service(tmp_path)
            source = service.settings.workspace_path / "note.txt"
            source.write_text("原始资料")
            try:
                value, execution = await interrupted_read(service, monkeypatch)
                if change == "content":
                    source.write_text("更新资料")
                if change == "missing":
                    source.unlink()
                if change == "expired":
                    service.delegation_repo.clock = lambda: time.time() + 7200
                if change == "disabled":
                    service.knowledge.workflows.disable(execution["workflow_version"])
                with pytest.raises(ValueError):
                    await call(
                        service,
                        "delegation.recover",
                        {
                            "delegation_id": value.id,
                            "revision": value.revision,
                            "action": "resume_readonly",
                        },
                        "resume",
                    )
                assert service.delegation_repo.get(value.id).status == "needs_review"
            finally:
                await service.close()

        asyncio.run(run())

    def test_persistent_call_budget_does_not_reset_when_resuming(self, tmp_path):
        service = make_service(tmp_path)
        service.recovery.start_budget("run", 120)
        service.recovery.reserve_call("run", 2)
        service.recovery.reserve_call("run", 2)
        service.recovery.finish_budget("run")
        service.recovery.start_budget("run", 120)
        with pytest.raises(ValueError, match="预算"):
            service.recovery.reserve_call("run", 2)
        service.recovery.finish_budget("run")
        asyncio.run(service.close())

    def test_sleep_stops_scheduler_until_resumed(self, tmp_path):
        async def run():
            service = make_service(tmp_path)
            try:
                await call(service, "runtime.power", {"suspended": True})
                assert service.scheduler.suspended and service.scheduler.quiet()
                await call(service, "runtime.power", {"suspended": False})
                assert not service.scheduler.suspended
            finally:
                await service.close()

        asyncio.run(run())


class TestRuntimeLock:
    def test_two_services_cannot_open_one_store_and_release_preserves_inode(self, tmp_path):
        with RuntimeLock(tmp_path):
            inode = (tmp_path / "service.lock").stat().st_ino
            with pytest.raises(RuntimeError, match="已有"), RuntimeLock(tmp_path):
                pytest.fail("second owner acquired the lock")
        with RuntimeLock(tmp_path):
            assert (tmp_path / "service.lock").stat().st_ino == inode

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink protection")
    def test_lock_never_follows_symlink(self, tmp_path):
        victim = tmp_path / "victim"
        victim.write_text("unchanged")
        (tmp_path / "service.lock").symlink_to(victim)
        with pytest.raises(OSError), RuntimeLock(tmp_path):
            pytest.fail("followed symbolic link")
        assert victim.read_text() == "unchanged"


class TestWriteReconciliation:
    @pytest.mark.parametrize("damage", ["none", "missing", "changed"])
    def test_completed_write_is_inspected_and_never_replayed(self, tmp_path, monkeypatch, damage):
        async def run():
            service = make_service(tmp_path)
            source = service.settings.workspace_path / "input"
            source.mkdir()
            (source / "a.txt").write_text("original")
            calls = 0
            original_tool = PracticalTools.organize

            async def counted(owner, args, active):
                nonlocal calls
                calls += 1
                return await original_tool(owner, args, active)

            monkeypatch.setattr(PracticalTools, "organize", counted)
            original_finish = service.recovery.finish_budget

            def interrupt_after_write(identity):
                original_finish(identity)
                raise asyncio.CancelledError

            monkeypatch.setattr(service.recovery, "finish_budget", interrupt_after_write)
            try:
                await call(service, "learning.configure", {"enabled": False})
                draft = await call(
                    service,
                    "delegation.create",
                    {
                        "goal": "保留原文件，整理副本",
                        "kind": "organize-files",
                        "source_directory": "input",
                        "output_directory": "output",
                        "criteria": ["副本数量和内容校验通过，原文件保留"],
                    },
                    "create",
                )
                await call(
                    service,
                    "delegation.confirm",
                    {"delegation_id": draft["id"], "revision": 1, "expires_at": time.time() + 3600},
                    "confirm",
                )
                await call(
                    service, "delegation.run", {"delegation_id": draft["id"], "revision": 2}, "run"
                )
                async with asyncio.timeout(3):
                    while not service.approvals:
                        await asyncio.sleep(0.01)
                approval = next(iter(service.approvals))
                await call(
                    service,
                    "approval.resolve",
                    {"approval_id": approval, "approved": True},
                    "approve",
                )
                async with asyncio.timeout(3):
                    while service.delegation_repo.get(draft["id"]).status == "running":
                        await asyncio.sleep(0.01)
                monkeypatch.setattr(service.recovery, "finish_budget", original_finish)
                value = service.delegation_repo.get(draft["id"])
                assert value.status == "needs_review" and calls == 2
                output = service.settings.workspace_path / "output/txt/a.txt"
                assert output.read_text() == "original"
                if damage == "missing":
                    output.unlink()
                if damage == "changed":
                    (source / "a.txt").write_text("changed")
                with pytest.raises(ValueError, match="不得重放"):
                    await call(
                        service,
                        "delegation.recover",
                        {
                            "delegation_id": value.id,
                            "revision": value.revision,
                            "action": "resume_readonly",
                        },
                        "unsafe",
                    )
                if damage == "none":
                    await call(
                        service,
                        "delegation.recover",
                        {
                            "delegation_id": value.id,
                            "revision": value.revision,
                            "action": "inspect",
                        },
                        "inspect",
                    )
                    assert service.delegation_repo.get(value.id).status == "completed"
                else:
                    with pytest.raises((OSError, ValueError)):
                        await call(
                            service,
                            "delegation.recover",
                            {
                                "delegation_id": value.id,
                                "revision": value.revision,
                                "action": "inspect",
                            },
                            "inspect",
                        )
                    assert service.delegation_repo.get(value.id).status == "needs_review"
                assert calls == 2
            finally:
                await service.close()

        asyncio.run(run())
