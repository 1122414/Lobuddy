"""Functional tests for Lobuddy 4.29.1 - Companion Core MVP.

This script tests the three main features:
1. User Profile Memory (USER.md)
2. Focus Companion (Pomodoro mode)
3. Skill Panel

Run with: pytest tests/test_4291_features.py -v
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.memory.user_profile_manager import UserProfileManager, build_default_profile
from core.memory.user_profile_schema import (
    PatchAction,
    ProfilePatch,
    ProfilePatchItem,
    ProfileSection,
    UserProfile,
)
from core.memory.user_profile_triggers import has_strong_signal, should_update_on_message_count
from core.memory.user_profile_service import UserProfileService
from core.focus.focus_companion import FocusCompanion, FocusSession, FocusState
from core.skills.skill_registry import SkillDefinition, SkillRegistry


# ===========================================================================
# Memory Profile Tests
# ===========================================================================


class TestMemoryProfile:
    """Test user profile memory feature."""

    def test_profile_file_creation(self, tmp_path: Path):
        """Test that USER.md is created with default sections."""
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)
        manager.ensure_profile_file()

        assert profile_path.exists()
        content = profile_path.read_text(encoding="utf-8")
        for section in ProfileSection:
            assert section.value in content

    def test_profile_load_save_roundtrip(self, tmp_path: Path):
        """Test that profile data survives load/save cycle."""
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)

        profile = build_default_profile()
        profile.sections[ProfileSection.BASIC_NOTES] = ["Test note 1", "Test note 2"]
        profile.sections[ProfileSection.PREFERENCES] = ["Prefers dark mode"]
        manager.save_profile(profile)

        loaded = manager.load_profile()
        assert loaded.sections[ProfileSection.BASIC_NOTES] == ["Test note 1", "Test note 2"]
        assert loaded.sections[ProfileSection.PREFERENCES] == ["Prefers dark mode"]

    def test_patch_add_item(self, tmp_path: Path):
        """Test adding item to profile via patch."""
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)
        manager.ensure_profile_file()

        patch = ProfilePatch(items=[
            ProfilePatchItem(
                section=ProfileSection.PREFERENCES,
                action=PatchAction.ADD,
                content="Likes Python",
                confidence=0.9,
            )
        ])

        profile, rejected = manager.apply_patch(patch)
        assert "Likes Python" in profile.sections[ProfileSection.PREFERENCES]
        assert len(rejected) == 0

    def test_patch_reject_low_confidence(self, tmp_path: Path):
        """Test that low confidence items are rejected."""
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)
        manager.ensure_profile_file()

        patch = ProfilePatch(items=[
            ProfilePatchItem(
                section=ProfileSection.BASIC_NOTES,
                action=PatchAction.ADD,
                content="Uncertain info",
                confidence=0.3,
            )
        ])

        _, rejected = manager.apply_patch(
            patch,
            require_high_confidence=True,
            min_confidence=0.75,
        )
        assert len(rejected) == 1

    def test_secret_redaction(self, tmp_path: Path):
        """Test that secrets are redacted before writing."""
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)
        manager.ensure_profile_file()

        patch = ProfilePatch(items=[
            ProfilePatchItem(
                section=ProfileSection.BASIC_NOTES,
                action=PatchAction.ADD,
                content="API key is sk-abc123def456ghi789jkl012mno345pqr",
                confidence=0.9,
            )
        ])

        profile, _ = manager.apply_patch(patch)
        note = profile.sections[ProfileSection.BASIC_NOTES][0]
        assert "sk-abc123def456ghi789jkl012mno345pqr" not in note
        assert "[REDACTED]" in note

    def test_compact_profile_for_prompt(self, tmp_path: Path):
        """Test that compact profile respects max_chars."""
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)

        profile = build_default_profile()
        profile.sections[ProfileSection.BASIC_NOTES] = ["A" * 1000]
        manager.save_profile(profile)

        compact = manager.compact_profile_for_prompt(max_chars=500)
        assert len(compact) <= 500

    def test_strong_signal_detection(self):
        """Test strong signal detection for memory triggers."""
        assert has_strong_signal("please remember this about me")
        assert has_strong_signal("I like Python more than Java")
        assert has_strong_signal("I prefer dark mode")
        assert has_strong_signal("from now on, use tabs")
        assert not has_strong_signal("what is the weather today?")

    def test_message_count_trigger(self):
        """Test message count trigger logic."""
        assert should_update_on_message_count(6, 6)
        assert should_update_on_message_count(12, 6)
        assert not should_update_on_message_count(5, 6)
        assert not should_update_on_message_count(0, 6)

    def test_profile_service_integration(self, tmp_path: Path):
        """Test UserProfileService orchestration."""
        settings = MagicMock()
        settings.memory_profile_enabled = True
        settings.memory_profile_file = tmp_path / "USER.md"
        settings.memory_profile_inject_enabled = True
        settings.memory_profile_max_inject_chars = 2000
        settings.memory_profile_update_every_n_user_messages = 6
        settings.memory_profile_update_on_strong_signal = True
        settings.memory_profile_require_high_confidence = True
        settings.memory_profile_min_confidence = 0.75
        settings.memory_profile_max_patch_items = 8
        settings.memory_profile_max_recent_messages = 30

        service = UserProfileService(settings)

        # Test context injection
        context = service.get_profile_context()
        assert context is not None

        # Test trigger check
        service._user_message_count = 5
        assert not service.should_update_profile("hello")
        service._user_message_count = 6
        assert service.should_update_profile("hello")

        # Test strong signal trigger
        service._user_message_count = 1
        assert service.should_update_profile("remember this about me")


# ===========================================================================
# Focus Companion Tests
# ===========================================================================


class TestFocusCompanion:
    """Test focus companion feature."""

    def test_session_state_transitions(self):
        """Test FocusSession state machine."""
        session = FocusSession(focus_minutes=1)
        assert session.state == FocusState.IDLE

        session.start_focus()
        assert session.state == FocusState.FOCUSING
        assert session.seconds_remaining > 0

        session.stop()
        assert session.state == FocusState.STOPPED

    def test_session_reset(self):
        """Test session reset to idle."""
        session = FocusSession()
        session.start_focus()
        session.reset()
        assert session.state == FocusState.IDLE

    def test_companion_lifecycle(self):
        """Test FocusCompanion start/stop lifecycle."""
        settings = MagicMock()
        settings.focus_default_minutes = 25
        settings.focus_break_minutes = 5
        settings.focus_auto_loop = False

        companion = FocusCompanion(settings)
        assert not companion.is_active

        session = companion.start_focus()
        assert companion.is_active
        assert session.state == FocusState.FOCUSING

        companion.stop()
        assert not companion.is_active
        assert companion.current_session is None

    def test_custom_duration(self):
        """Test starting focus with custom duration."""
        settings = MagicMock()
        settings.focus_default_minutes = 25
        settings.focus_break_minutes = 5

        companion = FocusCompanion(settings)
        session = companion.start_focus(minutes=10)
        assert session.focus_minutes == 10

    def test_auto_loop_behavior(self):
        """Test auto-loop from focus to break."""
        settings = MagicMock()
        settings.focus_default_minutes = 25
        settings.focus_break_minutes = 5
        settings.focus_auto_loop = True

        companion = FocusCompanion(settings)
        session = companion.start_focus(minutes=1)

        # Simulate focus completion
        session._state = FocusState.COMPLETED
        session.completed.emit()

        if settings.focus_auto_loop:
            assert session.state == FocusState.BREAK


# ===========================================================================
# Skill Panel Tests
# ===========================================================================


class TestSkillPanel:
    """Test skill panel feature."""

    def test_skill_registry_builtin_skills(self):
        """Test that built-in skills are registered."""
        registry = SkillRegistry()
        assert registry.get("chat") is not None
        assert registry.get("code") is not None
        assert registry.get("image") is not None
        assert registry.get("task") is not None
        assert registry.get("pet") is not None
        assert registry.get("focus") is not None

    def test_skill_registry_custom_skill(self):
        """Test registering custom skill."""
        registry = SkillRegistry()
        skill = SkillDefinition(
            id="custom",
            name="Custom Skill",
            description="A custom skill",
            examples=["example1"],
        )
        registry.register(skill)
        assert registry.get("custom") is skill

    def test_skill_availability_with_model(self):
        """Test skill availability with multimodal model."""
        registry = SkillRegistry()
        settings = MagicMock()
        settings.llm_multimodal_model = "gpt-4o"

        assert registry.is_available("chat", settings)
        assert registry.is_available("image", settings)

    def test_skill_availability_without_model(self):
        """Test skill availability without multimodal model."""
        registry = SkillRegistry()
        settings = MagicMock()
        settings.llm_multimodal_model = ""

        assert registry.is_available("chat", settings)
        assert not registry.is_available("image", settings)

    def test_get_enabled_skills(self):
        """Test getting only enabled skills."""
        registry = SkillRegistry()
        enabled = registry.get_enabled()
        assert all(s.enabled for s in enabled)

    def test_get_by_category(self):
        """Test getting skills by category."""
        registry = SkillRegistry()
        core_skills = registry.get_by_category("core")
        assert len(core_skills) > 0
        assert all(s.category == "core" for s in core_skills)


# ===========================================================================
# Integration Tests
# ===========================================================================


class TestIntegration:
    """Test feature integration."""

    def test_settings_have_all_fields(self):
        """Test that Settings model has all 4.29.1 fields."""
        from core.config.settings import Settings

        settings = Settings(llm_api_key="test-key")

        # Memory fields
        assert hasattr(settings, "memory_profile_enabled")
        assert hasattr(settings, "memory_profile_file")
        assert hasattr(settings, "memory_profile_inject_enabled")
        assert hasattr(settings, "memory_profile_max_inject_chars")

        # Focus fields
        assert hasattr(settings, "focus_mode_enabled")
        assert hasattr(settings, "focus_default_minutes")
        assert hasattr(settings, "focus_break_minutes")
        assert hasattr(settings, "focus_status_text")
        assert hasattr(settings, "focus_auto_loop")

        # Skill fields
        assert hasattr(settings, "skill_panel_enabled")
        assert hasattr(settings, "skill_panel_show_examples")
        assert hasattr(settings, "skill_panel_click_to_fill_input")

    def test_env_var_mapping(self):
        """Test that all settings have env var mappings."""
        from app.config import _ENV_VAR_MAP

        assert "memory_profile_enabled" in _ENV_VAR_MAP
        assert "focus_mode_enabled" in _ENV_VAR_MAP
        assert "skill_panel_enabled" in _ENV_VAR_MAP

    def test_all_modules_compile(self):
        """Test that all new modules compile."""
        import py_compile

        modules = [
            "core/memory/__init__.py",
            "core/memory/user_profile_schema.py",
            "core/memory/user_profile_manager.py",
            "core/memory/user_profile_triggers.py",
            "core/memory/user_profile_prompts.py",
            "core/memory/user_profile_service.py",
            "core/focus/__init__.py",
            "core/focus/focus_companion.py",
            "core/skills/__init__.py",
            "core/skills/skill_registry.py",
            "ui/skill_panel.py",
        ]

        for module in modules:
            py_compile.compile(module, doraise=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
