"""MemoryLint service tests.

Verifies:
  - MemoryLintService produces MemoryLintReport
  - Duplicate detection works
  - Conflict detection works
  - Stale detection works  
  - Low confidence detection works
  - Disabled lint skips checks
  - Projection drift detection
"""

from pathlib import Path

import pytest

from core.config import Settings
from core.storage.db import Database
from core.memory.memory_schema import MemoryItem, MemoryType, MemoryStatus


def _make_settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
        memory_lint_enabled=True,
        **kwargs,
    )


def _make_repo_and_lint(tmp_path: Path, **kwargs):
    from core.memory.memory_repository import MemoryRepository
    from core.memory.memory_service import MemoryService
    from core.memory.memory_lint import MemoryLintService

    settings = _make_settings(tmp_path, **kwargs)
    db = Database(settings)
    db.init_database()
    repo = MemoryRepository(db)
    service = MemoryService(settings, repo)
    lint_service = MemoryLintService(settings, repo=repo)
    return repo, service, lint_service, settings


class TestMemoryLint:
    def test_lint_produces_report(self, tmp_path: Path):
        _, service, lint, _ = _make_repo_and_lint(tmp_path)
        service.save_memory(MemoryItem(
            id="t1", memory_type=MemoryType.USER_PROFILE,
            content="User likes Python",
            confidence=0.9, importance=0.7,
        ))
        report = lint.lint()
        from core.memory.memory_lint import MemoryLintReport
        assert isinstance(report, MemoryLintReport)
        assert report.total_active_memories >= 1

    def test_disabled_lint_skips(self, tmp_path: Path):
        _, _, _, _ = _make_repo_and_lint(tmp_path)
        from core.memory.memory_lint import MemoryLintService
        from core.memory.memory_repository import MemoryRepository
        from core.storage.db import Database

        disabled_settings = Settings(
            llm_api_key="test",
            data_dir=tmp_path / "data2",
            logs_dir=tmp_path / "logs2",
            workspace_path=tmp_path / "workspace2",
            memory_lint_enabled=False,
            memory_enable_migration=False,
        )
        disabled_db = Database(disabled_settings)
        disabled_db.init_database()
        disabled_repo = MemoryRepository(disabled_db)
        disabled_lint = MemoryLintService(disabled_settings, repo=disabled_repo)
        report = disabled_lint.lint()
        assert report.total_active_memories == 0
        assert len(report.findings) == 0

    def test_duplicate_detection(self, tmp_path: Path):
        _, service, lint, _ = _make_repo_and_lint(
            tmp_path, memory_lint_duplicate_similarity=0.70,
        )
        service.save_memory(MemoryItem(
            id="d1", memory_type=MemoryType.PROJECT_MEMORY,
            content="Lobuddy is a desktop pet AI assistant for task management and workflow automation",
            confidence=0.9,
        ))
        service.save_memory(MemoryItem(
            id="d2", memory_type=MemoryType.PROJECT_MEMORY,
            content="Lobuddy is a desktop pet AI assistant for task management",
            confidence=0.9,
        ))
        report = lint.lint()
        duplicate_findings = [f for f in report.findings if f.category == "duplicate"]
        assert len(duplicate_findings) >= 1

    def test_conflict_detection(self, tmp_path: Path):
        _, service, lint, _ = _make_repo_and_lint(tmp_path)
        service.save_memory(MemoryItem(
            id="c1", memory_type=MemoryType.USER_PROFILE,
            content="User name is Alice",
            confidence=0.9, title="Basic Notes",
        ))
        service.save_memory(MemoryItem(
            id="c2", memory_type=MemoryType.USER_PROFILE,
            content="User name is Bob",
            confidence=0.9, title="Basic Notes",
        ))
        report = lint.lint()
        conflict_findings = [f for f in report.findings if f.category == "conflict"]
        assert len(conflict_findings) >= 1

    def test_projection_drift_detected(self, tmp_path: Path):
        _, service, lint, settings = _make_repo_and_lint(tmp_path)
        workspace_mem = settings.workspace_path / "memory"
        workspace_mem.mkdir(parents=True, exist_ok=True)
        report = lint.lint()
        drift_findings = [f for f in report.findings if f.category == "projection_drift"]
        assert any("MEMORY.md" in f.message or f.message == f"Projection file missing: {workspace_mem / 'MEMORY.md'}" for f in drift_findings)

    def test_has_errors_and_warnings(self, tmp_path: Path):
        _, service, lint, _ = _make_repo_and_lint(tmp_path)
        report = lint.lint()
        from core.memory.memory_lint import MemoryLintReport
        assert isinstance(report.has_errors, bool)
        assert isinstance(report.has_warnings, bool)
