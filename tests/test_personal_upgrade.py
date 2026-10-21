"""PA-01/FG-01: additive personal-agent upgrade and matching-data rollback."""

import asyncio
from pathlib import Path

import pytest

from core.config import Settings
from core.memory.memory_schema import MemoryItem, MemoryType
from core.service.application import ApplicationService
from core.service.delegation_protocol import DelegationSpec, DelegationWait
from core.service.knowledge import KnowledgeService
from core.service.project_protocol import ProjectCreate
from core.storage.chat_repo import ChatRepository
from core.storage.db import Database
from core.storage.pet_repo import PetRepository
from core.storage.project_repo import ProjectRepository
from core.storage.upgrade_backup import create_backup, restore_snapshot
from tests.test_projects import Backend


@pytest.fixture
def original(tmp_path):
    root = tmp_path.resolve()
    settings = Settings(
        llm_api_key="synthetic", data_dir=root / "old/data", workspace_path=root / "old/workspace"
    )
    settings.workspace_path.mkdir(parents=True)
    db = Database(settings)
    db.init_database()
    PetRepository(db).get_or_create_pet("original-pet")
    ChatRepository(db).get_or_create_session("original-session")
    KnowledgeService(settings, db).gateway.save_manual(
        MemoryItem(
            id="original-memory", memory_type=MemoryType.USER_PROFILE, content="喜欢清楚的来源"
        )
    )
    (settings.workspace_path / "source.txt").write_text("决定：保留原始文件。")
    (settings.workspace_path / "SOUL.md").write_text("合成陪伴设定")
    return settings, db


def check_original(service):
    assert service.pet.get_pet("original-pet") is not None
    assert service.chat.get_session("original-session") is not None
    assert service.knowledge.memory.get_memory("original-memory") is not None


class TestPersonalUpgrade:
    def test_twice_preserves_original_ids_and_new_records(self, original):
        settings, db = original
        service = ApplicationService(settings, db, Backend(), lambda event: None)
        project = service.projects.repo.create("project-request", ProjectCreate(name="合成项目"))
        delegation = service.delegation_repo.create(
            "delegation-request",
            DelegationSpec(
                goal="待我确认",
                wait=DelegationWait(kind="user"),
                criteria=["通知按规则投递（不代表已读）"],
            ),
        )
        check_original(service)
        asyncio.run(service.close())
        second = ApplicationService(settings, db, Backend(), lambda event: None)
        check_original(second)
        assert second.projects.repo.project(project.id) == project
        assert second.delegation_repo.get(delegation.id).id == delegation.id
        with db.get_connection() as conn:
            assert conn.execute("SELECT count(*) FROM delegation").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM personal_project").fetchone()[0] == 1
        asyncio.run(second.close())

    def test_partial_schema_initialization_is_recoverable(self, original, monkeypatch):
        settings, db = original
        original_init = ProjectRepository.__init__

        def interrupted(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            raise RuntimeError("synthetic initialization interruption")

        with monkeypatch.context() as patch:
            patch.setattr(ProjectRepository, "__init__", interrupted)
            with pytest.raises(RuntimeError, match="synthetic initialization"):
                ApplicationService(settings, db, Backend(), lambda event: None)
        service = ApplicationService(settings, db, Backend(), lambda event: None)
        check_original(service)
        asyncio.run(service.close())

    def test_restore_matches_pre_upgrade_data(self, original, tmp_path: Path):
        settings, db = original
        backup = tmp_path / "backup"
        create_backup(settings.data_dir, settings.workspace_path, backup)
        service = ApplicationService(settings, db, Backend(), lambda event: None)
        service.projects.repo.create("new", ProjectCreate(name="升级后项目"))
        asyncio.run(service.close())
        restored = tmp_path / "restored"
        restore_snapshot(backup, restored)
        restored_settings = settings.model_copy(
            update={"data_dir": restored / "data", "workspace_path": restored / "workspace"}
        )
        old = Database(restored_settings)
        old.init_database()
        assert PetRepository(old).get_pet("original-pet") is not None
        assert ChatRepository(old).get_session("original-session") is not None
        assert (settings.workspace_path / "source.txt").read_text() == "决定：保留原始文件。"
        with old.get_connection() as conn:
            assert not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='personal_project'"
            ).fetchone()
        assert (restored_settings.workspace_path / "SOUL.md").read_text() == "合成陪伴设定"
        assert not (backup / "workspace" / "SOUL.md").is_symlink()
