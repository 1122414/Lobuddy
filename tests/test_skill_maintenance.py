"""Tests for SkillMaintenance."""

import pytest
from pathlib import Path
from datetime import datetime, timedelta

from core.skills.skill_maintenance import SkillMaintenance
from core.skills.skill_manager import SkillManager
from core.skills.skill_schema import SkillRecord, SkillStatus
from core.storage.db import Database
from core.config import Settings


class TestSkillMaintenance:
    def test_run_maintenance_no_manager(self):
        settings = Settings(llm_api_key="test")
        maint = SkillMaintenance(settings)
        report = maint.run_maintenance()
        assert report["reviewed"] == 0
        assert report["disabled"] == 0

    def test_stale_skill_marked_for_review(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        maint = SkillMaintenance(mgr._settings, mgr)

        record = SkillRecord(
            id="s1",
            name="stale-skill",
            path="",
            description="Old skill",
            status=SkillStatus.ACTIVE,
            last_used_at=datetime.now() - timedelta(days=65),
        )
        mgr.create_skill(record, "# Stale")

        report = maint.run_maintenance()
        assert report["reviewed"] >= 1 or report["disabled"] >= 1

    def test_stale_skill_disabled(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        maint = SkillMaintenance(mgr._settings, mgr)

        record = SkillRecord(
            id="s1",
            name="very-stale",
            path="",
            description="Very old skill",
            status=SkillStatus.ACTIVE,
            last_used_at=datetime.now() - timedelta(days=95),
        )
        mgr.create_skill(record, "# Very Stale")

        report = maint.run_maintenance()
        assert report["disabled"] >= 1

    def test_high_failure_rate_skill_reviewed(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        maint = SkillMaintenance(mgr._settings, mgr)

        record = SkillRecord(id="s1", name="failing", path="", description="Failing skill", status=SkillStatus.ACTIVE)
        mgr.create_skill(record, "# Failing")
        for _ in range(6):
            mgr.record_result("s1", False)

        report = maint.run_maintenance()
        assert report["reviewed"] >= 1


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
