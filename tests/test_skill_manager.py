"""Tests for SkillManager."""

from pathlib import Path

from core.skills.skill_manager import SkillManager
from core.skills.skill_schema import SkillRecord, SkillStatus, SkillCandidate, CandidateStatus
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
            proposed_content=(
                "---\nname: test-candidate\ndescription: Test skill\n---\n\n"
                "# Test Candidate\n\n## When to use\n\n"
                "Use this skill when the user asks for a validation workflow.\n\n"
                "## Workflow\n\n1. Inspect the input safely.\n"
                "2. Verify the result before returning it.\n"
            ),
        )
        mgr.create_candidate(candidate)

        loaded = mgr.get_candidate("c1")
        assert loaded is not None
        assert loaded.status == CandidateStatus.PENDING

        created = mgr.approve_candidate("c1")
        assert created is not None
        assert created.name == "test-candidate"

    def test_list_candidates(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        mgr.create_candidate(
            SkillCandidate(
                id="c1", title="A", rationale="R", proposed_name="a", proposed_content="C"
            )
        )
        mgr.create_candidate(
            SkillCandidate(
                id="c2", title="B", rationale="R", proposed_name="b", proposed_content="C"
            )
        )

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

    def test_enable_skill(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        record = SkillRecord(id="s1", name="test-skill", path="", description="Test")
        mgr.create_skill(record, "Content")
        mgr.disable_skill("s1")

        ok = mgr.enable_skill("s1")
        assert ok is True
        assert mgr.get_skill("s1").status == SkillStatus.ACTIVE

    def test_get_content(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        content = "# Test\n\nContent"
        record = SkillRecord(id="s1", name="test-skill", path="", description="Test")
        mgr.create_skill(record, content)
        assert mgr.get_content("s1") == content

    def test_get_events(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        record = SkillRecord(id="s1", name="test-skill", path="", description="Test")
        mgr.create_skill(record, "Content")
        mgr.disable_skill("s1")
        events = mgr.get_events("s1")
        assert len(events) >= 2

    def test_reject_candidate(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        candidate = SkillCandidate(
            id="c1", title="Test", rationale="R", proposed_name="test", proposed_content="C"
        )
        mgr.create_candidate(candidate)
        ok = mgr.reject_candidate("c1", "Bad")
        assert ok is True
        assert mgr.get_candidate("c1").status == CandidateStatus.REJECTED

    def test_get_candidate_stats(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        mgr.create_candidate(
            SkillCandidate(
                id="c1", title="A", rationale="R", proposed_name="a", proposed_content="C"
            )
        )
        mgr.reject_candidate("c1")
        stats = mgr.get_candidate_stats()
        assert stats["pending"] == 0
        assert stats["rejected"] == 1

    def test_cleanup_keeps_active_managed_skill(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        record = SkillRecord(
            id="s1",
            name="active-skill",
            path="",
            description="Active",
            status=SkillStatus.ACTIVE,
        )
        mgr.create_skill(record, "# Active")

        assert mgr.cleanup_orphan_workspace_files() == 0
        assert (tmp_path / "workspace" / "skills" / "active-skill" / "SKILL.md").exists()

    def test_cleanup_keeps_unmanaged_workspace_skill(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        skill_file = tmp_path / "workspace" / "skills" / "user-installed" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text("# User installed", encoding="utf-8")

        assert mgr.cleanup_orphan_workspace_files() == 0
        assert skill_file.exists()

    def test_cleanup_removes_file_for_disabled_managed_skill(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        record = SkillRecord(
            id="s1",
            name="disabled-skill",
            path="",
            description="Disabled",
            status=SkillStatus.ACTIVE,
        )
        mgr.create_skill(record, "# Disabled")
        assert mgr.disable_skill("s1") is True

        skill_file = tmp_path / "workspace" / "skills" / "disabled-skill" / "SKILL.md"
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text("# Stale projection", encoding="utf-8")

        assert mgr.cleanup_orphan_workspace_files() == 1
        assert not skill_file.exists()


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
