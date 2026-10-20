"""Tests for SkillManager."""

import pytest
from pathlib import Path

from core.skills.skill_manager import SkillManager
from core.skills.skill_schema import SkillRecord, SkillStatus, SkillCandidate
from core.storage.db import Database
from core.config import Settings


class TestSkillManager:
    def test_create_skill(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        record = SkillRecord(id="s1", name="test-skill", path="", description="Test skill")
        created = mgr.create_skill(record, "# Test Skill\n\nContent")
        assert created.name == "test-skill"
        assert (tmp_path / "workspace" / "skills" / "test-skill" / "SKILL.md").exists()

    def test_get_skill(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        record = SkillRecord(id="s1", name="test-skill", path="", description="Test")
        mgr.create_skill(record, "Content")

        loaded = mgr.get_skill("s1")
        assert loaded is not None
        assert loaded.name == "test-skill"

    def test_disable_and_enable(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        record = SkillRecord(id="s1", name="test-skill", path="", description="Test")
        mgr.create_skill(record, "Content")

        ok = mgr.disable_skill("s1")
        assert ok is True

        loaded = mgr.get_skill("s1")
        assert loaded is not None
        assert loaded.status == SkillStatus.DISABLED

    def test_delete_skill(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        record = SkillRecord(id="s1", name="test-skill", path="", description="Test")
        mgr.create_skill(record, "Content")

        ok = mgr.delete_skill("s1")
        assert ok is True
        assert mgr.get_skill("s1") is None

    def test_record_result(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        record = SkillRecord(id="s1", name="test-skill", path="", description="Test")
        mgr.create_skill(record, "Content")

        ok = mgr.record_result("s1", True)
        assert ok is True

        loaded = mgr.get_skill("s1")
        assert loaded is not None
        assert loaded.success_count == 1

    def test_create_and_approve_candidate(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        candidate = SkillCandidate(
            id="c1",
            title="Test Candidate",
            rationale="Useful",
            proposed_name="test-candidate",
            proposed_content="---\nname: test-candidate\n---\n\n# Test\n",
        )
        mgr.create_candidate(candidate)

        loaded = mgr.get_candidate("c1")
        assert loaded is not None
        assert loaded.status == "pending"

        created = mgr.approve_candidate("c1")
        assert created is not None
        assert created.name == "test-candidate"

    def test_list_candidates(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        mgr.create_candidate(SkillCandidate(id="c1", title="A", rationale="R", proposed_name="a", proposed_content="C"))
        mgr.create_candidate(SkillCandidate(id="c2", title="B", rationale="R", proposed_name="b", proposed_content="C"))

        results = mgr.list_candidates()
        assert len(results) == 2

    def test_failure_rate(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        record = SkillRecord(id="s1", name="test-skill", path="", description="Test")
        mgr.create_skill(record, "Content")
        mgr.record_result("s1", False)
        mgr.record_result("s1", False)
        mgr.record_result("s1", True)

        loaded = mgr.get_skill("s1")
        assert loaded is not None
        assert loaded.failure_rate() == 2 / 3


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
