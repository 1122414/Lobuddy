"""Tests for MemoryMaintenance."""

import pytest
from datetime import datetime, timedelta

from core.memory.memory_maintenance import MemoryMaintenance
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import MemoryItem, MemoryStatus, MemoryType
from core.storage.db import Database
from core.config import Settings


class TestMemoryMaintenance:
    def test_deprecate_expired_memory(self, tmp_path):
        settings = _settings_for_test(tmp_path)
        db = Database(settings)
        repo = MemoryRepository(db)
        maint = MemoryMaintenance(settings, repo)

        repo.save(MemoryItem(
            id="exp1",
            memory_type=MemoryType.USER_PROFILE,
            content="Expired preference",
            status=MemoryStatus.ACTIVE,
            expires_at=datetime.now() - timedelta(days=1),
        ))

        report = maint.run_maintenance()
        assert report["deprecated"] >= 1

        loaded = repo.get("exp1")
        assert loaded is not None
        assert loaded.status == MemoryStatus.DEPRECATED

    def test_no_deprecate_active_memory(self, tmp_path):
        settings = _settings_for_test(tmp_path)
        db = Database(settings)
        repo = MemoryRepository(db)
        maint = MemoryMaintenance(settings, repo)

        repo.save(MemoryItem(
            id="active1",
            memory_type=MemoryType.USER_PROFILE,
            content="Active preference",
            status=MemoryStatus.ACTIVE,
            expires_at=datetime.now() + timedelta(days=30),
        ))

        report = maint.run_maintenance()
        assert report["deprecated"] == 0

        loaded = repo.get("active1")
        assert loaded.status == MemoryStatus.ACTIVE

    def test_report_structure(self, tmp_path):
        settings = _settings_for_test(tmp_path)
        db = Database(settings)
        repo = MemoryRepository(db)
        maint = MemoryMaintenance(settings, repo)

        report = maint.run_maintenance()
        assert "deprecated" in report
        assert "merged" in report
        assert "errors" in report


def _settings_for_test(tmp_path):
    return Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
    )
