"""Tests for MemoryService."""

import pytest
from pathlib import Path

from core.memory.memory_service import MemoryService
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import MemoryItem, MemoryPatch, MemoryPatchItem, MemoryType, MemoryPatchAction
from core.config import Settings


class TestMemoryService:
    def test_save_and_get_memory(self, tmp_path: Path):
        service = _make_service(tmp_path)
        item = MemoryItem(
            id="test-1",
            memory_type=MemoryType.USER_PROFILE,
            content="User likes Python",
        )
        saved = service.save_memory(item)
        assert saved.id == "test-1"

        loaded = service.get_memory("test-1")
        assert loaded is not None
        assert loaded.content == "User likes Python"

    def test_list_memories(self, tmp_path: Path):
        service = _make_service(tmp_path)
        service.save_memory(MemoryItem(id="a", memory_type=MemoryType.USER_PROFILE, content="A"))
        service.save_memory(MemoryItem(id="b", memory_type=MemoryType.USER_PROFILE, content="B"))

        results = service.list_memories(MemoryType.USER_PROFILE)
        assert len(results) == 2

    def test_search_memories(self, tmp_path: Path):
        service = _make_service(tmp_path)
        service.save_memory(MemoryItem(id="a", memory_type=MemoryType.PROJECT_MEMORY, content="React project", title="React"))
        service.save_memory(MemoryItem(id="b", memory_type=MemoryType.PROJECT_MEMORY, content="Vue project", title="Vue"))

        results = service.search_memories("React")
        assert len(results) == 1
        assert results[0].id == "a"

    def test_deprecate_memory(self, tmp_path: Path):
        service = _make_service(tmp_path)
        service.save_memory(MemoryItem(id="a", memory_type=MemoryType.USER_PROFILE, content="A"))

        ok = service.deprecate_memory("a")
        assert ok is True

        loaded = service.get_memory("a")
        assert loaded is not None
        assert loaded.status.value == "deprecated"

    def test_delete_memory(self, tmp_path: Path):
        service = _make_service(tmp_path)
        service.save_memory(MemoryItem(id="a", memory_type=MemoryType.USER_PROFILE, content="A"))

        ok = service.delete_memory("a")
        assert ok is True
        assert service.get_memory("a") is None

    def test_apply_patch_add(self, tmp_path: Path):
        service = _make_service(tmp_path)
        patch = MemoryPatch(
            items=[
                MemoryPatchItem(
                    memory_type=MemoryType.USER_PROFILE,
                    action=MemoryPatchAction.ADD,
                    content="User prefers dark mode",
                    confidence=0.9,
                ),
            ]
        )
        accepted, rejected = service.apply_patch(patch)
        assert len(accepted) == 1
        assert len(rejected) == 0
        assert accepted[0].content == "User prefers dark mode"

    def test_apply_patch_uncertain_rejected(self, tmp_path: Path):
        service = _make_service(tmp_path)
        patch = MemoryPatch(
            items=[
                MemoryPatchItem(
                    memory_type=MemoryType.USER_PROFILE,
                    action=MemoryPatchAction.UNCERTAIN,
                    content="Maybe something",
                    confidence=0.3,
                ),
            ]
        )
        accepted, rejected = service.apply_patch(patch)
        assert len(accepted) == 0
        assert len(rejected) == 1

    def test_build_prompt_context(self, tmp_path: Path):
        service = _make_service(tmp_path)
        service.save_memory(MemoryItem(id="a", memory_type=MemoryType.USER_PROFILE, content="User likes Python"))
        service.save_memory(MemoryItem(id="b", memory_type=MemoryType.SYSTEM_PROFILE, content="Be helpful"))

        bundle = service.build_prompt_context()
        assert "User likes Python" in bundle.user_profile
        assert "Be helpful" in bundle.system_profile
        assert bundle.total_chars > 0

    def test_migration_from_legacy_user_md(self, tmp_path: Path):
        from core.memory.user_profile_manager import UserProfileManager
        from core.memory.user_profile_schema import ProfileSection
        from core.storage.db import Database

        memory_dir = tmp_path / "data" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        profile_path = memory_dir / "USER.md"
        manager = UserProfileManager(profile_path)
        default_profile = manager.load_profile()
        default_profile.sections[ProfileSection.BASIC_NOTES] = ["Legacy note 1", "Legacy note 2"]
        manager.save_profile(default_profile)

        settings = Settings(
            llm_api_key="test",
            data_dir=tmp_path / "data",
            logs_dir=tmp_path / "logs",
            workspace_path=tmp_path / "workspace",
            memory_enable_migration=True,
            memory_profile_file=profile_path,
        )
        db = Database(settings)
        repo = MemoryRepository(db)
        service = MemoryService(settings, repo)

        results = service.list_memories(MemoryType.USER_PROFILE)
        assert len(results) == 2
        assert any(r.content == "Legacy note 1" for r in results)
        assert any(r.content == "Legacy note 2" for r in results)


def _make_service(tmp_path: Path) -> MemoryService:
    from core.storage.db import Database
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
    )
    db = Database(settings)
    repo = MemoryRepository(db)
    return MemoryService(settings, repo)
