"""Tests for SettingsRepository runtime overrides."""

from app.config import _ENV_VAR_MAP, apply_db_overrides
from core.config import Settings


class _FakeSettingsRepository:
    values: dict[str, str] = {}

    def get_setting(self, key: str):
        return self.values.get(key)


class TestApplyDbOverrides:
    def test_bool_aliases_and_missing_fields_are_loaded(self, monkeypatch):
        _FakeSettingsRepository.values = {
            "shell_enabled": "yes",
            "pet_clock_enabled": "off",
            "pet_exp_bar_enabled": "no",
            "pet_clock_hover_full_format": "0",
            "conversation_timeline_enabled": "1",
            "conversation_timeline_min_dot_gap_px": "16",
            "llm_multimodal_model": "qwen-vl",
            "llm_multimodal_base_url": "https://vision.example.com/v1",
            "llm_multimodal_api_key": "sk-mm",
        }
        monkeypatch.setattr(
            "core.storage.settings_repo.SettingsRepository",
            _FakeSettingsRepository,
        )

        settings = Settings(llm_api_key="sk-main", llm_model="gpt-4o")
        updated = apply_db_overrides(settings)

        assert updated.shell_enabled is True
        assert updated.pet_clock_enabled is False
        assert updated.pet_exp_bar_enabled is False
        assert updated.pet_clock_hover_full_format is False
        assert updated.conversation_timeline_enabled is True
        assert updated.conversation_timeline_min_dot_gap_px == 16
        assert updated.llm_multimodal_model == "qwen-vl"
        assert updated.llm_multimodal_base_url == "https://vision.example.com/v1"
        assert updated.llm_multimodal_api_key == "sk-mm"

    def test_invalid_bool_does_not_discard_other_overrides(self, monkeypatch):
        _FakeSettingsRepository.values = {
            "shell_enabled": "maybe",
            "pet_name": "Buddy",
        }
        monkeypatch.setattr(
            "core.storage.settings_repo.SettingsRepository",
            _FakeSettingsRepository,
        )

        settings = Settings(llm_api_key="sk-main", llm_model="gpt-4o", shell_enabled=False)
        updated = apply_db_overrides(settings)

        assert updated.shell_enabled is False
        assert updated.pet_name == "Buddy"

    def test_float_overrides_are_coerced_from_db_strings(self, monkeypatch):
        _FakeSettingsRepository.values = {
            "memory_prompt_budget_percent": "0.25",
            "memory_gateway_min_confidence": "0.85",
            "skill_candidate_auto_approve_threshold": "0.92",
            "skill_failure_rate_threshold": "0.35",
        }
        monkeypatch.setattr(
            "core.storage.settings_repo.SettingsRepository",
            _FakeSettingsRepository,
        )

        settings = Settings(llm_api_key="sk-main", llm_model="gpt-4o")
        updated = apply_db_overrides(settings)

        assert updated.memory_prompt_budget_percent == 0.25
        assert updated.memory_gateway_min_confidence == 0.85
        assert updated.skill_candidate_auto_approve_threshold == 0.92
        assert updated.skill_failure_rate_threshold == 0.35
        assert isinstance(updated.memory_prompt_budget_percent, float)
        assert isinstance(updated.memory_gateway_min_confidence, float)

    def test_env_export_map_covers_runtime_settings(self):
        expected_fields = {
            "llm_multimodal_model",
            "llm_multimodal_base_url",
            "llm_multimodal_api_key",
            "nanobot_max_iterations",
            "pet_clock_hover_full_format",
            "pet_exp_bar_enabled",
            "conversation_timeline_min_dot_gap_px",
            "memory_prompt_budget_percent",
            "skill_candidate_auto_approve_threshold",
            "skill_failure_rate_threshold",
            "history_max_turns",
            "history_compress_threshold",
            "history_compress_prompt",
        }

        assert expected_fields <= set(_ENV_VAR_MAP)
