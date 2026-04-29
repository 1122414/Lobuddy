"""Tests for Skill Registry."""

import pytest
from core.skills.skill_registry import SkillDefinition, SkillRegistry


class TestSkillDefinition:
    """Test SkillDefinition dataclass."""

    def test_basic_creation(self):
        skill = SkillDefinition(
            id="test",
            name="Test Skill",
            description="A test skill",
        )
        assert skill.id == "test"
        assert skill.name == "Test Skill"
        assert skill.enabled is True
        assert skill.examples == []

    def test_with_examples(self):
        skill = SkillDefinition(
            id="test",
            name="Test",
            description="Test",
            examples=["example1", "example2"],
        )
        assert len(skill.examples) == 2


class TestSkillRegistry:
    """Test SkillRegistry."""

    def test_register(self):
        registry = SkillRegistry()
        skill = SkillDefinition(
            id="custom",
            name="Custom",
            description="Custom skill",
        )
        registry.register(skill)
        assert registry.get("custom") is skill

    def test_get_nonexistent(self):
        registry = SkillRegistry()
        assert registry.get("nonexistent") is None

    def test_get_all(self):
        registry = SkillRegistry()
        all_skills = registry.get_all()
        assert len(all_skills) > 0

    def test_get_enabled(self):
        registry = SkillRegistry()
        enabled = registry.get_enabled()
        assert all(s.enabled for s in enabled)

    def test_builtin_skills(self):
        registry = SkillRegistry()
        assert registry.get("chat") is not None
        assert registry.get("code") is not None
        assert registry.get("image") is not None
        assert registry.get("task") is not None
        assert registry.get("pet") is not None

    def test_is_available_without_model(self):
        from unittest.mock import MagicMock

        registry = SkillRegistry()
        settings = MagicMock()
        settings.llm_multimodal_model = "gpt-4o"

        assert registry.is_available("chat", settings)
        assert registry.is_available("image", settings)

    def test_is_available_multimodal_requires_model(self):
        from unittest.mock import MagicMock

        registry = SkillRegistry()
        settings = MagicMock()
        settings.llm_multimodal_model = ""

        assert registry.is_available("chat", settings)
        assert not registry.is_available("image", settings)

    def test_get_by_category(self):
        registry = SkillRegistry()
        core_skills = registry.get_by_category("core")
        assert len(core_skills) > 0
        assert all(s.category == "core" for s in core_skills)

    def test_disabled_skill_not_in_enabled(self):
        registry = SkillRegistry()
        skill = SkillDefinition(
            id="disabled",
            name="Disabled",
            description="Disabled skill",
            enabled=False,
        )
        registry.register(skill)
        assert registry.get("disabled") is not None
        assert registry.get("disabled") not in registry.get_enabled()

    def test_is_available_nonexistent_skill(self):
        from unittest.mock import MagicMock

        registry = SkillRegistry()
        settings = MagicMock()
        assert not registry.is_available("nonexistent", settings)
