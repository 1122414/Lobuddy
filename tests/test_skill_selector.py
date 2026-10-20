"""Tests for SkillSelector."""

import pytest
from pathlib import Path

from core.skills.skill_selector import SkillSelector
from core.skills.skill_manager import SkillManager
from core.skills.skill_schema import SkillRecord, SkillStatus
from core.storage.db import Database
from core.config import Settings


class TestSkillSelector:
    def test_select_active_skills_empty(self, tmp_path: Path):
        selector = SkillSelector()
        assert selector.select_active_skills() == []

    def test_select_active_skills(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        selector = SkillSelector(mgr)

        record = SkillRecord(id="s1", name="skill-1", path="", description="First skill", status=SkillStatus.ACTIVE)
        mgr.create_skill(record, "# Skill 1")

        active = selector.select_active_skills()
        assert len(active) == 1
        assert active[0].name == "skill-1"

    def test_disabled_skills_excluded(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        selector = SkillSelector(mgr)

        record = SkillRecord(id="s1", name="skill-1", path="", description="First skill", status=SkillStatus.ACTIVE)
        mgr.create_skill(record, "# Skill 1")
        mgr.disable_skill("s1")

        active = selector.select_active_skills()
        assert len(active) == 0

    def test_build_skills_summary(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        selector = SkillSelector(mgr)

        record = SkillRecord(id="s1", name="skill-1", path="", description="A useful skill", status=SkillStatus.ACTIVE)
        mgr.create_skill(record, "# Skill 1")

        summary = selector.build_skills_summary()
        assert "skill-1" in summary
        assert "A useful skill" in summary

    def test_build_skills_summary_empty(self, tmp_path: Path):
        selector = SkillSelector()
        assert selector.build_skills_summary() == ""


def _make_manager(tmp_path: Path) -> SkillManager:
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        skill_archive_dir=tmp_path / "archive",
    )
    db = Database(settings)
    return SkillManager(settings, db)
