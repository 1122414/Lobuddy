"""Tests for grounded prompt-memory selection."""

from datetime import datetime, timedelta
from pathlib import Path

from core.config import Settings
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import MemoryItem, MemoryStatus, MemoryType, PromptContextBundle
from core.memory.memory_selector import MemorySelector
from core.memory.memory_service import MemoryService
from core.memory.privacy_mode import PrivacyModeManager
from core.memory.prompt_budget import MemoryBundle, PromptBudget
from core.storage.db import Database


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

    def test_short_prompt_gets_configured_floor_without_exceeding_cap(self):
        budget = PromptBudget(max_chars=1000, max_percent=0.2, min_chars=600)
        assert budget.get_budget("short") == 600

        clamped = PromptBudget(max_chars=400, max_percent=0.2, min_chars=600)
        assert clamped.get_budget("short") == 400


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

    def test_short_chinese_request_recalls_grounded_episodic_memory(self, tmp_path: Path):
        db = Database(_settings(tmp_path))
        repo = MemoryRepository(db)
        repo.save(
            MemoryItem(
                id="release-failure",
                memory_type=MemoryType.EPISODIC_MEMORY,
                content="上次发布项目时测试在签名步骤失败",
            )
        )
        repo.save(
            MemoryItem(
                id="unrelated",
                memory_type=MemoryType.EPISODIC_MEMORY,
                content="周末喜欢在公园散步",
            )
        )

        bundle = MemorySelector(_settings(tmp_path), repo).select_for_prompt(
            "还记得我上次发布项目遇到的问题吗？"
        )

        assert "签名步骤失败" in bundle.retrieved_memories
        assert "公园散步" not in bundle.retrieved_memories
        assert bundle.type_counts() == {"episodic_memory": 1}

    def test_procedural_memory_can_be_recalled_for_english_request(self, tmp_path: Path):
        db = Database(_settings(tmp_path))
        repo = MemoryRepository(db)
        repo.save(
            MemoryItem(
                id="deploy-checklist",
                memory_type=MemoryType.PROCEDURAL_MEMORY,
                title="Deployment checklist",
                content="For deployment, run the signed release checklist",
            )
        )

        bundle = MemorySelector(_settings(tmp_path), repo).select_for_prompt(
            "Do you remember the deployment issue?"
        )

        assert "signed release checklist" in bundle.retrieved_memories
        assert bundle.memory_evidence[0].memory_type == MemoryType.PROCEDURAL_MEMORY

    def test_expired_and_other_session_scoped_memories_are_excluded(self, tmp_path: Path):
        db = Database(_settings(tmp_path))
        repo = MemoryRepository(db)
        repo.save(
            MemoryItem(
                id="expired",
                memory_type=MemoryType.EPISODIC_MEMORY,
                content="Deployment signing expired memory",
                expires_at=datetime.now() - timedelta(minutes=1),
            )
        )
        repo.save(
            MemoryItem(
                id="other-session",
                memory_type=MemoryType.PROCEDURAL_MEMORY,
                scope="session:other",
                content="Deployment signing private workflow",
            )
        )

        bundle = MemorySelector(_settings(tmp_path), repo).select_for_prompt(
            "deployment signing workflow",
            session_id="current",
        )

        assert bundle.retrieved_memories == ""
        assert bundle.memory_evidence == []

    def test_all_sections_share_one_hard_budget(self, tmp_path: Path):
        settings = _settings(
            tmp_path,
            memory_prompt_budget_chars=1000,
            memory_prompt_budget_min_chars=1000,
            memory_prompt_budget_percent=1.0,
        )
        db = Database(settings)
        repo = MemoryRepository(db)
        for index in range(12):
            for memory_type in (
                MemoryType.USER_PROFILE,
                MemoryType.SYSTEM_PROFILE,
                MemoryType.PROJECT_MEMORY,
            ):
                repo.save(
                    MemoryItem(
                        id=f"{memory_type.value}-{index}",
                        memory_type=memory_type,
                        content=f"deployment {memory_type.value} " + ("x" * 110),
                    )
                )

        bundle = MemorySelector(settings, repo).select_for_prompt("deployment")

        assert bundle.total_chars <= 1000
        assert bundle.total_chars == sum(bundle.memory_budget_report.values())

    def test_injection_setting_and_privacy_return_explicit_empty_evidence(self, tmp_path: Path):
        disabled_settings = _settings(tmp_path, memory_profile_inject_enabled=False)
        disabled_repo = MemoryRepository(Database(disabled_settings))
        disabled_bundle = MemorySelector(
            disabled_settings,
            disabled_repo,
        ).select_for_prompt("deployment")
        assert disabled_bundle.injection_enabled is False
        assert disabled_bundle.selected_count == 0

        private_settings = _settings(tmp_path)
        privacy = PrivacyModeManager(private_settings)
        privacy.enable_privacy("private-session")
        private_repo = MemoryRepository(Database(private_settings))
        private_bundle = MemorySelector(
            private_settings,
            private_repo,
            privacy=privacy,
        ).select_for_prompt("deployment", "private-session")
        assert private_bundle.privacy_active is True
        assert private_bundle.selected_count == 0

    def test_selected_items_are_marked_used_but_unselected_items_are_not(self, tmp_path: Path):
        db = Database(_settings(tmp_path))
        repo = MemoryRepository(db)
        repo.save(
            MemoryItem(
                id="selected",
                memory_type=MemoryType.EPISODIC_MEMORY,
                content="Deployment signing failed before release",
            )
        )
        repo.save(
            MemoryItem(
                id="unselected",
                memory_type=MemoryType.EPISODIC_MEMORY,
                content="The user likes watercolor painting",
            )
        )

        bundle = MemorySelector(_settings(tmp_path), repo).select_for_prompt(
            "deployment signing release"
        )

        assert bundle.selected_count == 1
        assert repo.get("selected").last_used_at is not None
        assert repo.get("unselected").last_used_at is None

    def test_injection_text_treats_current_request_as_source_of_truth(self):
        bundle = PromptContextBundle(user_profile="- Likes concise answers")
        injection = bundle.build_injection_text()
        assert "may be incomplete or outdated" in injection
        assert "current request or correction first" in injection
        assert "authoritative structured context" not in injection

    def test_memory_service_applies_recall_settings_without_restart(self, tmp_path: Path):
        settings = _settings(tmp_path)
        repo = MemoryRepository(Database(settings))
        service = MemoryService(settings, repo)
        disabled = settings.model_copy(update={"memory_profile_inject_enabled": False})

        service.update_settings(disabled)
        bundle = service.build_prompt_context("deployment", "session-a")

        assert bundle.injection_enabled is False
        assert bundle.selected_count == 0


def _settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        **overrides,
    )
