"""FG-02: real persistence, cancellation, idle ownership and bounded retry."""

import asyncio
from pathlib import Path

import pytest

from core.config import Settings
from core.service.learning import LearningHandler, LearningService, maintenance_handler
from core.service.learning_protocol import LearningPolicy
from core.storage.db import Database
from core.storage.learning_repo import LearningRepository


def make_service(tmp_path: Path) -> tuple[LearningService, list[float]]:
    settings = Settings(
        llm_api_key="test",
        _env_file=None,
        data_dir=tmp_path,
        workspace_path=tmp_path / "workspace",
        skill_archive_dir=tmp_path / "archive",
    )
    db = Database(settings)
    db.init_database(allow_desktop=True)
    now = [1000.0]
    return LearningService(db, settings, lambda: False, lambda: now[0]), now


class TestLearningService:
    async def test_idle_preemption_disable_and_resume(self, tmp_path: Path) -> None:
        service, now = make_service(tmp_path)
        started = asyncio.Event()

        async def run(_source: str) -> dict:
            started.set()
            await asyncio.Event().wait()
            return {}

        service.handlers["test"] = LearningHandler(run, calls=1, input_tokens=100, output_tokens=10)
        service.repo.enqueue("test", "one", now[0])
        await service.tick()
        assert service.current is None
        now[0] += 61
        await service.tick()
        await started.wait()
        await service.tick()
        assert service.repo.jobs()[0].attempts == 1
        await service.activity()
        assert service.repo.jobs()[0].status == "interrupted"
        assert service.repo.usage(now[0]).calls == 1
        await service.configure(LearningPolicy(enabled=False))
        now[0] += 400
        await service.tick()
        assert service.repo.jobs()[0].attempts == 1
        assert service.worker is None
        await service.close()

    async def test_completed_job_not_replayed_after_restart(self, tmp_path: Path) -> None:
        service, now = make_service(tmp_path)

        async def run(_source: str) -> dict:
            return {"checked": True}

        service.handlers["test"] = LearningHandler(run)
        service.repo.enqueue("test", "one", now[0])
        now[0] += 61
        await service.tick()
        await service.current
        await service.close()
        restored, new_now = make_service(tmp_path)
        restored.handlers["test"] = LearningHandler(run)
        restored.repo.enqueue("test", "one", new_now[0])
        new_now[0] += 400
        await restored.tick()
        assert restored.current is None
        assert len(restored.repo.jobs()) == 1
        assert restored.repo.jobs()[0].result == {"checked": True}
        await restored.close()

    @pytest.mark.parametrize("limit", ["daily_calls", "daily_input_tokens", "daily_output_tokens"])
    def test_budget_atomic_and_persisted(self, tmp_path: Path, limit: str) -> None:
        service, now = make_service(tmp_path)
        policy = LearningPolicy(**{limit: 1})
        repo = service.repo
        for name in ["one", "two"]:
            repo.enqueue("test", name, now[0])
        assert repo.claim("test", now[0], policy, calls=1, input_tokens=1, output_tokens=1)
        restored = LearningRepository(repo.db)
        restored.recover(now[0])
        assert (
            restored.claim("test", now[0], policy, calls=1, input_tokens=1, output_tokens=1) is None
        )
        assert restored.usage(now[0]).calls == 1
        assert restored.jobs()[0].status in ("pending", "interrupted")
        assert restored.claim(
            "test", now[0] + 86400, policy, calls=1, input_tokens=1, output_tokens=1
        )

    async def test_failure_retry_bounded_and_sanitized(self, tmp_path: Path) -> None:
        service, now = make_service(tmp_path)

        async def run(_source: str) -> dict:
            raise RuntimeError("secret-provider-response")

        service.handlers["test"] = LearningHandler(run, calls=1)
        service.repo.enqueue("test", "one", now[0])
        for attempt in range(3):
            now[0] += 400
            await service.tick()
            await service.current
            assert service.repo.jobs()[0].attempts == attempt + 1
        now[0] += 400
        await service.tick()
        assert service.repo.jobs()[0].attempts == 3
        assert "secret" not in service.repo.jobs()[0].model_dump_json()
        await service.close()

    async def test_busy_defers_and_close_cancels(self, tmp_path: Path) -> None:
        service, now = make_service(tmp_path)
        service.busy = lambda: True
        now[0] += 100
        await service.tick()
        assert service.last_activity == now[0]
        service.start()
        await service.close()
        assert service.worker.done()
        assert service.view().state == "closed"

    async def test_readonly_maintenance_keeps_expired_memory(self, tmp_path: Path) -> None:
        from datetime import datetime, timedelta

        from core.memory.memory_repository import MemoryRepository
        from core.memory.memory_schema import MemoryItem, MemoryStatus, MemoryType
        from core.skills.skill_manager import SkillManager

        service, now = make_service(tmp_path)
        memories = MemoryRepository(service.repo.db)
        SkillManager(service.settings, service.repo.db)
        item = MemoryItem(
            id="expired",
            memory_type=MemoryType.USER_PROFILE,
            content="plain",
            expires_at=datetime.now() - timedelta(days=1),
        )
        memories.save(item)
        service.handlers["maintenance"] = maintenance_handler(service.settings, service.repo.db)
        service.repo.enqueue("maintenance", "day", now[0])
        now[0] += 61
        await service.tick()
        await service.current
        assert service.repo.jobs()[0].result["expired_memories"] == 1
        assert memories.get("expired").status == MemoryStatus.ACTIVE
        await service.close()
