"""Unified runtime maintenance module.

This module owns maintenance registration, scheduling, manual execution, and
cache cleanup. Callers only need the small start/stop/status interface.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Protocol

from core.config import Settings
from core.services.maintenance_scheduler import MaintenanceScheduler, MaintenanceTask
from core.storage.execution_trace_repository import ExecutionTraceRepository

logger = logging.getLogger(__name__)


class _MaintenanceOperation(Protocol):
    def run_maintenance(self) -> dict[str, int]: ...


class _TraceCleanup(Protocol):
    def clear_old(self, older_than_seconds: float) -> int: ...


class RuntimeMaintenance:
    """Own all recurring runtime maintenance behind one deep interface."""

    def __init__(
        self,
        settings: Settings,
        memory_maintenance: _MaintenanceOperation,
        skill_maintenance: _MaintenanceOperation,
        trace_repository: _TraceCleanup | None = None,
        scheduler: MaintenanceScheduler | None = None,
    ) -> None:
        self._settings = settings
        self._memory_maintenance = memory_maintenance
        self._skill_maintenance = skill_maintenance
        self._trace_repository = trace_repository or ExecutionTraceRepository()
        self.scheduler = scheduler or MaintenanceScheduler(
            start_delay_seconds=settings.maintenance_start_delay_seconds,
            poll_interval_seconds=settings.maintenance_poll_interval_seconds,
        )
        self._operations = {
            "memory_cleanup": self._run_memory_cleanup,
            "skill_review": self._run_skill_review,
            "trace_cleanup": self._run_trace_cleanup,
            "asset_cache_cleanup": self._run_asset_cache_cleanup,
        }
        self._register_operations()

    def start(self) -> None:
        self.scheduler.start()

    def stop(self) -> None:
        self.scheduler.stop()

    def get_status(self) -> list[dict]:
        return self.scheduler.get_status()

    def run_now(self, name: str | None = None) -> dict[str, str]:
        """Run one or all operations through the registered implementations."""
        if name is not None:
            operation = self._operations.get(name)
            if operation is None:
                raise KeyError(f"Unknown maintenance operation: {name}")
            return {name: operation()}
        return {
            operation_name: operation() for operation_name, operation in self._operations.items()
        }

    def _register_operations(self) -> None:
        intervals = {
            "memory_cleanup": self._settings.maintenance_memory_cleanup_interval_seconds,
            "skill_review": self._settings.maintenance_skill_review_interval_seconds,
            "trace_cleanup": self._settings.maintenance_trace_cleanup_interval_seconds,
            "asset_cache_cleanup": (
                self._settings.maintenance_asset_cache_cleanup_interval_seconds
            ),
        }
        for name, operation in self._operations.items():
            interval = intervals[name]
            if interval <= 0:
                continue
            self.scheduler.register(
                MaintenanceTask(name=name, fn=operation, interval_seconds=interval)
            )

    def _run_memory_cleanup(self) -> str:
        return self._format_report(self._memory_maintenance.run_maintenance())

    def _run_skill_review(self) -> str:
        return self._format_report(self._skill_maintenance.run_maintenance())

    def _run_trace_cleanup(self) -> str:
        count = self._trace_repository.clear_old(
            self._settings.maintenance_trace_cleanup_interval_seconds
        )
        return f"traces_cleaned={count}"

    def _run_asset_cache_cleanup(self) -> str:
        cache_dir = (self._settings.workspace_path / "cache").resolve()
        if not cache_dir.exists():
            return "no_cache_dir"

        cutoff = datetime.now() - timedelta(
            seconds=self._settings.maintenance_asset_cache_cleanup_interval_seconds
        )
        removed = 0
        for candidate in cache_dir.iterdir():
            if not candidate.is_file() or candidate.is_symlink():
                continue
            try:
                resolved = candidate.resolve(strict=True)
                if resolved.parent != cache_dir:
                    continue
                mtime = datetime.fromtimestamp(os.path.getmtime(resolved))
                if mtime < cutoff:
                    resolved.unlink()
                    removed += 1
            except OSError as exc:
                logger.warning("Cache cleanup skipped %s: %s", candidate, exc)
        return f"cache_files_removed={removed}"

    @staticmethod
    def _format_report(report: dict[str, int]) -> str:
        if not report:
            return "ok"
        return ",".join(f"{key}={value}" for key, value in sorted(report.items()))
