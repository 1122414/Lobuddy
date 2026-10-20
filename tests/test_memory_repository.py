"""Tests for MemoryRepository."""

import pytest
from datetime import datetime

from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import ConversationSummary, MemoryItem, MemoryStatus, MemoryType
from core.storage.db import Database


class TestMemoryRepository:
    def test_save_and_get_memory(self, tmp_path):
        db = Database(_settings_for_test(tmp_path))
        repo = MemoryRepository(db)
        item = MemoryItem(
            id="test-1",
            memory_type=MemoryType.USER_PROFILE,
            content="User likes Python",
            confidence=0.9,
        )
        saved = repo.save(item)
        assert saved.id == "test-1"

        loaded = repo.get("test-1")
        assert loaded is not None
        assert loaded.content == "User likes Python"
        assert loaded.memory_type == MemoryType.USER_PROFILE

    def test_list_by_type(self, tmp_path):
        db = Database(_settings_for_test(tmp_path))
        repo = MemoryRepository(db)
        repo.save(MemoryItem(id="a", memory_type=MemoryType.USER_PROFILE, content="A"))
        repo.save(MemoryItem(id="b", memory_type=MemoryType.USER_PROFILE, content="B"))
        repo.save(MemoryItem(id="c", memory_type=MemoryType.SYSTEM_PROFILE, content="C"))

        results = repo.list_by_type(MemoryType.USER_PROFILE)
        assert len(results) == 2

    def test_list_by_type_and_status(self, tmp_path):
        db = Database(_settings_for_test(tmp_path))
        repo = MemoryRepository(db)
        repo.save(MemoryItem(id="a", memory_type=MemoryType.USER_PROFILE, content="A", status=MemoryStatus.ACTIVE))
        repo.save(MemoryItem(id="b", memory_type=MemoryType.USER_PROFILE, content="B", status=MemoryStatus.DEPRECATED))

        active = repo.list_by_type(MemoryType.USER_PROFILE, MemoryStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].id == "a"

    def test_search_by_keyword(self, tmp_path):
        db = Database(_settings_for_test(tmp_path))
        repo = MemoryRepository(db)
        repo.save(MemoryItem(id="a", memory_type=MemoryType.PROJECT_MEMORY, content="React project setup", title="React"))
        repo.save(MemoryItem(id="b", memory_type=MemoryType.PROJECT_MEMORY, content="Vue project setup", title="Vue"))

        results = repo.search_by_keyword("React")
        assert len(results) == 1
        assert results[0].id == "a"

    def test_update_status(self, tmp_path):
        db = Database(_settings_for_test(tmp_path))
        repo = MemoryRepository(db)
        repo.save(MemoryItem(id="a", memory_type=MemoryType.USER_PROFILE, content="A"))

        ok = repo.update_status("a", MemoryStatus.DEPRECATED)
        assert ok is True

        loaded = repo.get("a")
        assert loaded is not None
        assert loaded.status == MemoryStatus.DEPRECATED

    def test_delete(self, tmp_path):
        db = Database(_settings_for_test(tmp_path))
        repo = MemoryRepository(db)
        repo.save(MemoryItem(id="a", memory_type=MemoryType.USER_PROFILE, content="A"))

        ok = repo.delete("a")
        assert ok is True
        assert repo.get("a") is None

    def test_save_and_get_summary(self, tmp_path):
        db = Database(_settings_for_test(tmp_path))
        repo = MemoryRepository(db)
        summary = ConversationSummary(
            id="s1",
            session_id="session-1",
            summary_type="rolling",
            content="User asked about Python",
        )
        repo.save_summary(summary)

        loaded = repo.get_latest_summary("session-1")
        assert loaded is not None
        assert loaded.content == "User asked about Python"

    def test_list_summaries(self, tmp_path):
        db = Database(_settings_for_test(tmp_path))
        repo = MemoryRepository(db)
        repo.save_summary(ConversationSummary(id="s1", session_id="sess", summary_type="rolling", content="A"))
        repo.save_summary(ConversationSummary(id="s2", session_id="sess", summary_type="rolling", content="B"))

        results = repo.list_summaries("sess")
        assert len(results) == 2

    def test_scope_filter(self, tmp_path):
        db = Database(_settings_for_test(tmp_path))
        repo = MemoryRepository(db)
        repo.save(MemoryItem(id="a", memory_type=MemoryType.PROJECT_MEMORY, content="A", scope="lobuddy"))
        repo.save(MemoryItem(id="b", memory_type=MemoryType.PROJECT_MEMORY, content="B", scope="other"))

        results = repo.list_by_type(MemoryType.PROJECT_MEMORY, scope="lobuddy")
        assert len(results) == 1
        assert results[0].id == "a"


def _settings_for_test(tmp_path):
    from core.config import Settings
    return Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
    )
