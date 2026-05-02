"""Integration test script for Lobuddy 5.2 Memory & Skill Upgrade.

Usage:
    python tests/test_52_integration.py

This script verifies the core functionality of the 5.2 upgrade:
1. MemoryService: SQLite authority, markdown projection, prompt context
2. SkillManager: CRUD, lifecycle, candidate workflow
3. MemorySelector: budget-aware retrieval
4. Maintenance: stale cleanup
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import tempfile
from datetime import datetime, timedelta


def _setup():
    from core.config import Settings

    tmp = Path(tempfile.mkdtemp(prefix="lobuddy_52_test_"))
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp / "data",
        logs_dir=tmp / "logs",
        workspace_path=tmp / "workspace",
        skill_archive_dir=tmp / "archive",
        memory_enable_migration=False,
    )
    return settings, tmp


def test_memory_service():
    from core.memory.memory_service import MemoryService
    from core.memory.memory_repository import MemoryRepository
    from core.memory.memory_schema import MemoryItem, MemoryType
    from core.storage.db import Database

    settings, tmp = _setup()
    db = Database(settings)
    repo = MemoryRepository(db)
    service = MemoryService(settings, repo)

    service.save_memory(MemoryItem(id="u1", memory_type=MemoryType.USER_PROFILE, content="Likes Python"))
    service.save_memory(MemoryItem(id="s1", memory_type=MemoryType.SYSTEM_PROFILE, content="Be helpful"))
    service.save_memory(MemoryItem(id="p1", memory_type=MemoryType.PROJECT_MEMORY, content="React setup", scope="frontend"))

    user_items = service.list_memories(MemoryType.USER_PROFILE)
    assert len(user_items) == 1, f"Expected 1 user profile, got {len(user_items)}"

    ctx = service.build_prompt_context("Python")
    assert "Likes Python" in ctx.user_profile, "User profile missing from context"
    assert ctx.total_chars > 0, "Context should have chars"

    projection_path = settings.data_dir / "memory" / "USER.md"
    assert projection_path.exists(), "USER.md projection not created"

    print("[PASS] MemoryService")
    return True


def test_skill_manager():
    from core.skills.skill_manager import SkillManager
    from core.skills.skill_schema import SkillRecord, SkillStatus, SkillCandidate
    from core.storage.db import Database

    settings, tmp = _setup()
    db = Database(settings)
    mgr = SkillManager(settings, db)

    record = SkillRecord(id="sk1", name="test-skill", path="", description="A test skill")
    created = mgr.create_skill(record, "---\nname: test-skill\n---\n\n# Test\n")
    assert created.name == "test-skill", "Skill creation failed"

    loaded = mgr.get_skill("sk1")
    assert loaded is not None, "Skill not found"

    mgr.record_result("sk1", True)
    mgr.record_result("sk1", False)
    updated = mgr.get_skill("sk1")
    assert updated.success_count == 1 and updated.failure_count == 1, "Result recording failed"

    candidate = SkillCandidate(
        id="c1",
        title="Test Candidate",
        rationale="Useful pattern",
        proposed_name="auto-skill",
        proposed_content="---\nname: auto-skill\n---\n\n# Auto\n",
    )
    mgr.create_candidate(candidate)
    c = mgr.get_candidate("c1")
    assert c is not None, "Candidate not saved"

    approved = mgr.approve_candidate("c1")
    assert approved is not None, "Candidate approval failed"
    loaded = mgr.get_skill(approved.id)
    assert loaded is not None, "Approved skill not found"
    assert loaded.status == SkillStatus.ACTIVE, "Approved skill should be active"

    print("[PASS] SkillManager")
    return True


def test_memory_selector_budget():
    from core.memory.memory_repository import MemoryRepository
    from core.memory.memory_schema import MemoryItem, MemoryType
    from core.memory.memory_selector import MemorySelector
    from core.storage.db import Database

    settings, tmp = _setup()
    db = Database(settings)
    repo = MemoryRepository(db)

    for i in range(5):
        repo.save(MemoryItem(id=f"u{i}", memory_type=MemoryType.USER_PROFILE, content=f"Note {i}"))

    selector = MemorySelector(settings, repo)
    bundle = selector.select_for_prompt("x" * 1000)

    assert bundle.total_chars <= settings.memory_prompt_budget_chars, "Budget exceeded"
    assert bundle.user_profile != "", "User profile should be injected"

    print("[PASS] MemorySelector budget: pass")
    return True


def test_skill_candidate_extractor():
    from core.skills.skill_candidate_extractor import SkillCandidateExtractor

    extractor = SkillCandidateExtractor(min_tools_used=2)

    assert extractor.should_extract(True, ["read_file", "write_file"], "Do this") is True
    assert extractor.should_extract(True, ["read_file"], "Do this") is False
    assert extractor.should_extract(True, ["read_file"], "以后这样处理") is True

    candidate = extractor.extract_candidate("Sort a list", ["read_file", "exec"], "Used Python sorted()", "sess1", "task1")
    assert candidate is not None, "Should extract candidate"
    assert candidate.proposed_name == "sort-a-list", f"Unexpected name: {candidate.proposed_name}"

    print("[PASS] SkillCandidateExtractor: pass")
    return True


def test_skill_validator():
    from core.skills.skill_validator import SkillValidator
    from core.skills.skill_schema import SkillCandidate

    validator = SkillValidator()

    good = SkillCandidate(id="c1", title="Good", rationale="R", proposed_name="good", proposed_content="A" * 100)
    ok, errors = validator.validate(good)
    assert ok is True, f"Good candidate rejected: {errors}"

    bad = SkillCandidate(id="c2", title="Bad", rationale="R", proposed_name="bad", proposed_content="short", confidence=0.3)
    ok, errors = validator.validate(bad)
    assert ok is False, "Bad candidate should be rejected"

    secret = SkillCandidate(id="c3", title="Secret", rationale="R", proposed_name="secret", proposed_content="Key: sk-123456789012345678901234567890")
    ok, errors = validator.validate(secret)
    assert ok is False, "Secret-containing candidate should be rejected"

    dup = validator.check_duplicate(good, ["good", "other"])
    assert dup == "good", "Duplicate not detected"

    print("[PASS] SkillValidator: pass")
    return True


def test_maintenance():
    from core.memory.memory_maintenance import MemoryMaintenance
    from core.memory.memory_service import MemoryService
    from core.memory.memory_schema import MemoryItem, MemoryType, MemoryStatus
    from core.skills.skill_maintenance import SkillMaintenance
    from core.skills.skill_manager import SkillManager
    from core.skills.skill_schema import SkillRecord

    settings, tmp = _setup()
    from core.storage.db import Database
    db = Database(settings)
    from core.memory.memory_repository import MemoryRepository
    repo = MemoryRepository(db)
    service = MemoryService(settings, repo)
    service.save_memory(MemoryItem(id="e1", memory_type=MemoryType.USER_PROFILE, content="Expired", status=MemoryStatus.ACTIVE, expires_at=datetime.now() - timedelta(days=1)))

    mem_maint = MemoryMaintenance(settings, repo=repo)
    report = mem_maint.run_maintenance()
    assert report["deprecated"] >= 1, "Expired memory not deprecated"

    db = Database(settings)
    mgr = SkillManager(settings, db)
    record = SkillRecord(id="sk1", name="stale", path="", description="Stale skill")
    mgr.create_skill(record, "# Stale")

    skill_maint = SkillMaintenance(settings, mgr)
    report2 = skill_maint.run_maintenance()
    assert isinstance(report2, dict), "Maintenance report should be dict"

    print("[PASS] Maintenance: pass")
    return True


def main():
    print("=" * 60)
    print("Lobuddy 5.2 Memory & Skill Integration Test")
    print("=" * 60)

    tests = [
        test_memory_service,
        test_skill_manager,
        test_memory_selector_budget,
        test_skill_candidate_extractor,
        test_skill_validator,
        test_maintenance,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: FAIL - {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
