"""Integration tests for skill lab features (P2-D1, P2-D2, P2-D3, P2-D4)."""

from pathlib import Path

from core.skills.skill_manager import SkillManager
from core.skills.skill_schema import SkillRecord, SkillStatus, SkillCandidate, CandidateStatus
from core.skills.skill_validator import SkillValidator
from core.skills.skill_usage import (
    SkillUsageEvent,
    SkillUsageEventType,
    NoOpSkillUsageSink,
    NanobotSkillHookAdapter,
)
from core.storage.db import Database
from core.config import Settings


class TestSkillLabMVP:
    """P2-D1: Skill lab MVP tests."""

    def test_enable_skill(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        record = SkillRecord(id="s1", name="test-skill", path="", description="Test")
        mgr.create_skill(record, "# Test Skill\n\nContent")
        mgr.disable_skill("s1")

        ok = mgr.enable_skill("s1")
        assert ok is True

        loaded = mgr.get_skill("s1")
        assert loaded is not None
        assert loaded.status == SkillStatus.ACTIVE

    def test_get_content(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        content = "# Test Skill\n\nThis is the skill content."
        record = SkillRecord(id="s1", name="test-skill", path="", description="Test")
        mgr.create_skill(record, content)

        loaded_content = mgr.get_content("s1")
        assert loaded_content == content

    def test_get_events(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        record = SkillRecord(id="s1", name="test-skill", path="", description="Test")
        mgr.create_skill(record, "Content")
        mgr.disable_skill("s1")

        events = mgr.get_events("s1")
        assert len(events) >= 2
        event_types = [e.event_type for e in events]
        assert "create" in event_types
        assert "disable" in event_types

    def test_list_by_status(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        r1 = SkillRecord(
            id="s1",
            name="active-skill",
            path="",
            description="Active",
            status=SkillStatus.ACTIVE,
        )
        r2 = SkillRecord(
            id="s2",
            name="disabled-skill",
            path="",
            description="Disabled",
            status=SkillStatus.DISABLED,
        )
        mgr.create_skill(r1, "# Active")
        mgr.create_skill(r2, "# Disabled")

        active = mgr.list_skills(status=SkillStatus.ACTIVE)
        disabled = mgr.list_skills(status=SkillStatus.DISABLED)
        assert len(active) == 1
        assert len(disabled) == 1
        assert active[0].name == "active-skill"
        assert disabled[0].name == "disabled-skill"


class TestSkillCandidateReview:
    """P2-D2: Skill candidate review tests."""

    def test_reject_candidate(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        candidate = SkillCandidate(
            id="c1",
            title="Test Candidate",
            rationale="Useful",
            proposed_name="test-candidate",
            proposed_content="---\nname: test-candidate\n---\n\n# Test\n",
        )
        mgr.create_candidate(candidate)

        ok = mgr.reject_candidate("c1", "Not useful enough")
        assert ok is True

        loaded = mgr.get_candidate("c1")
        assert loaded is not None
        assert loaded.status == CandidateStatus.REJECTED
        assert loaded.reject_reason == "Not useful enough"

    def test_rejected_candidate_not_in_prompt(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        candidate = SkillCandidate(
            id="c1",
            title="Test",
            rationale="R",
            proposed_name="test",
            proposed_content="---\nname: test\n---\n\n# Test\n",
        )
        mgr.create_candidate(candidate)
        mgr.reject_candidate("c1")

        from core.skills.skill_selector import SkillSelector

        selector = SkillSelector(mgr)
        active = selector.select_active_skills()
        assert not any("test" in s.name for s in active)

    def test_approve_candidate_with_validation(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        candidate = SkillCandidate(
            id="c1",
            title="Test",
            rationale="R",
            proposed_name="test",
            proposed_content="---\nname: test\n---\n\n# Test\n",
            confidence=0.3,
        )
        mgr.create_candidate(candidate)

        result = mgr.approve_candidate("c1")
        assert result is None

    def test_candidate_stats(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        mgr.create_candidate(
            SkillCandidate(
                id="c1",
                title="A",
                rationale="R",
                proposed_name="a",
                proposed_content="C",
            )
        )
        mgr.create_candidate(
            SkillCandidate(
                id="c2",
                title="B",
                rationale="R",
                proposed_name="b",
                proposed_content="C",
            )
        )
        mgr.reject_candidate("c2")

        stats = mgr.get_candidate_stats()
        assert stats["pending"] == 1
        assert stats["rejected"] == 1
        assert stats["approved"] == 0


class TestSkillValidation:
    """P2-D3: Skill validation sandbox tests."""

    def test_validate_static_valid(self):
        validator = SkillValidator()
        content = """---
name: test-skill
description: A test skill
---

# Test Skill

## Trigger

When user asks about testing.

## Workflow

1. Do something useful.
"""
        valid, errors = validator.validate_static(content)
        assert valid is True
        assert len(errors) == 0

    def test_validate_static_missing_frontmatter(self):
        validator = SkillValidator()
        content = (
            "# Test Skill\n\nNo frontmatter here. This content is long enough "
            "to pass length check."
        )
        valid, errors = validator.validate_static(content)
        assert valid is False
        assert any("frontmatter" in e.lower() for e in errors)

    def test_validate_static_no_trigger_rules(self):
        validator = SkillValidator()
        content = """---
name: test-skill
description: A test skill
---

# Test Skill

Just some content without any activation rules.
"""
        valid, errors = validator.validate_static(content)
        assert valid is False
        assert any("trigger" in e.lower() for e in errors)

    def test_validate_static_dangerous_commands(self):
        validator = SkillValidator()
        content = """---
name: bad-skill
description: Bad skill
---

# Bad Skill

Run this: rm -rf /
"""
        valid, errors = validator.validate_static(content)
        assert valid is False
        assert any("dangerous" in e.lower() for e in errors)

    def test_validate_static_secrets(self):
        validator = SkillValidator()
        content = (
            """---
name: leaky-skill
description: Leaky skill
---

# Leaky

API key: """
            + "sk-"
            + "abcdefghijklmnopqrstuvwxyz123456"
            + "\n"
        )
        valid, errors = validator.validate_static(content)
        assert valid is False
        assert any("secret" in e.lower() or "sensitive" in e.lower() for e in errors)


class TestSkillUsageInterface:
    """P2-D4: Skill usage feedback interface tests."""

    def test_noop_sink(self):
        sink = NoOpSkillUsageSink()
        event = SkillUsageEvent(
            skill_id="s1",
            event_type=SkillUsageEventType.STARTED,
        )
        sink.record(event)
        events = sink.get_events()
        assert events == []

    def test_hook_adapter_placeholder(self):
        adapter = NanobotSkillHookAdapter()
        event = SkillUsageEvent(
            skill_id="s1",
            event_type=SkillUsageEventType.COMPLETED,
        )
        adapter.emit(event)

    def test_event_immutable(self):
        event = SkillUsageEvent(
            skill_id="s1",
            event_type=SkillUsageEventType.STARTED,
        )
        assert event.skill_id == "s1"
        assert event.event_type == SkillUsageEventType.STARTED


class TestSkillLabIntegration:
    """Integration tests covering multiple P2-D phases."""

    def test_full_candidate_lifecycle(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        candidate = SkillCandidate(
            id="c1",
            title="Auto Skill",
            rationale="Extracted from task",
            proposed_name="auto-skill",
            proposed_content=(
                "---\nname: auto-skill\ndescription: Auto skill\n---\n\n"
                "# Auto\n\n## Trigger\n\nWhen the user requests this workflow.\n\n"
                "## Workflow\n\n1. Inspect the request.\n2. Verify the result.\n"
            ),
            confidence=0.8,
        )
        mgr.create_candidate(candidate)

        stats_before = mgr.get_candidate_stats()
        assert stats_before["pending"] == 1

        created = mgr.approve_candidate("c1")
        assert created is not None
        assert created.status == SkillStatus.ACTIVE

        stats_after = mgr.get_candidate_stats()
        assert stats_after["approved"] == 1
        assert stats_after["pending"] == 0

        active = mgr.list_skills(status=SkillStatus.ACTIVE)
        assert any(s.name == "auto-skill" for s in active)

    def test_skill_status_transitions(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        record = SkillRecord(id="s1", name="lifecycle", path="", description="Test")
        mgr.create_skill(record, "# Lifecycle")

        mgr.disable_skill("s1")
        s = mgr.get_skill("s1")
        assert s.status == SkillStatus.DISABLED

        mgr.enable_skill("s1")
        s = mgr.get_skill("s1")
        assert s.status == SkillStatus.ACTIVE

        mgr.archive_skill("s1")
        s = mgr.get_skill("s1")
        assert s.status == SkillStatus.ARCHIVED

        assert not mgr.enable_skill("s1")

    def test_validation_blocks_bad_skills(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        candidate = SkillCandidate(
            id="c1",
            title="Bad",
            rationale="Bad",
            proposed_name="bad",
            proposed_content=("rm -rf / and " + "sk-" + "123456789012345678901234567890"),
            confidence=0.8,
        )
        mgr.create_candidate(candidate)

        created = mgr.approve_candidate("c1")
        assert created is None

        loaded = mgr.get_candidate("c1")
        assert loaded.status == CandidateStatus.PENDING


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
