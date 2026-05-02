"""Tests for PromptBudget and MemorySelector."""

import pytest
from pathlib import Path

from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import MemoryItem, MemoryType
from core.memory.memory_selector import MemorySelector
from core.memory.prompt_budget import MemoryBundle, PromptBudget
from core.storage.db import Database
from core.config import Settings


class TestPromptBudget:
    def test_allocate_respects_max_chars(self):
        budget = PromptBudget(max_chars=100, max_percent=1.0)
        bundles = [
            MemoryBundle("A" * 60, priority=100),
            MemoryBundle("B" * 60, priority=90),
        ]
        selected = budget.allocate("p" * 200, bundles)
        assert len(selected) == 1
        assert selected[0].content == "A" * 60

    def test_allocate_respects_percent(self):
        budget = PromptBudget(max_chars=1000, max_percent=0.1)
        bundles = [MemoryBundle("A" * 50, priority=100)]
        selected = budget.allocate("p" * 1000, bundles)
        assert len(selected) == 1

    def test_get_budget(self):
        budget = PromptBudget(max_chars=100, max_percent=0.5)
        assert budget.get_budget("test") == 2


class TestMemorySelector:
    def test_select_for_prompt_with_memories(self, tmp_path: Path):
        db = Database(_settings(tmp_path))
        repo = MemoryRepository(db)
        repo.save(MemoryItem(id="a", memory_type=MemoryType.USER_PROFILE, content="Likes Python"))
        repo.save(MemoryItem(id="b", memory_type=MemoryType.SYSTEM_PROFILE, content="Be helpful"))

        long_prompt = "h" * 500
        selector = MemorySelector(_settings(tmp_path), repo)
        bundle = selector.select_for_prompt(long_prompt)

        assert "Likes Python" in bundle.user_profile
        assert "Be helpful" in bundle.system_profile
        assert bundle.total_chars > 0

    def test_search_keyword_recall(self, tmp_path: Path):
        db = Database(_settings(tmp_path))
        repo = MemoryRepository(db)
        repo.save(MemoryItem(id="a", memory_type=MemoryType.PROJECT_MEMORY, content="React setup guide"))
        repo.save(MemoryItem(id="b", memory_type=MemoryType.EPISODIC_MEMORY, content="Used React before"))

        results = repo.search_by_keyword("React", limit=10)
        contents = [r.content for r in results]
        assert "React setup guide" in contents or "Used React before" in contents


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
    )
