"""Tests for the unified runtime maintenance module."""

import time
from pathlib import Path

from core.config import Settings
from core.services.maintenance_scheduler import MaintenanceScheduler
from core.services.runtime_maintenance import RuntimeMaintenance


class _Maintenance:
    def __init__(self, report: dict[str, int]) -> None:
        self.report = report
        self.calls = 0

    def run_maintenance(self) -> dict[str, int]:
        self.calls += 1
        return self.report


class _TraceRepository:
    def __init__(self) -> None:
        self.older_than_seconds = 0.0

    def clear_old(self, older_than_seconds: float) -> int:
        self.older_than_seconds = older_than_seconds
        return 3


class TestRuntimeMaintenance:
    def test_scheduler_stop_interrupts_long_start_delay(self):
        scheduler = MaintenanceScheduler(
            start_delay_seconds=60,
            poll_interval_seconds=10,
        )
        scheduler.start()

        started = time.monotonic()
        scheduler.stop()

        assert time.monotonic() - started < 1
        assert scheduler._thread is None

    def test_registers_one_task_per_maintenance_concern(self, tmp_path: Path):
        runtime, _, _, _ = _make_runtime(tmp_path)

        names = {item["name"] for item in runtime.get_status()}

        assert names == {
            "memory_cleanup",
            "skill_review",
            "trace_cleanup",
            "asset_cache_cleanup",
        }

    def test_run_now_uses_the_same_registered_implementations(self, tmp_path: Path):
        runtime, memory, skills, traces = _make_runtime(tmp_path)

        results = runtime.run_now()

        assert memory.calls == 1
        assert skills.calls == 1
        assert traces.older_than_seconds == 300
        assert results["memory_cleanup"] == "expired=2"
        assert results["skill_review"] == "reviewed=1"
        assert results["trace_cleanup"] == "traces_cleaned=3"

    def test_asset_cleanup_is_scoped_to_workspace_cache(self, tmp_path: Path):
        runtime, _, _, _ = _make_runtime(tmp_path)
        cache_dir = tmp_path / "workspace" / "cache"
        cache_dir.mkdir(parents=True)
        old_file = cache_dir / "old.bin"
        old_file.write_bytes(b"old")
        outside_file = tmp_path / "outside.bin"
        outside_file.write_bytes(b"keep")

        import os
        import time

        old = time.time() - 600
        os.utime(old_file, (old, old))
        result = runtime.run_now("asset_cache_cleanup")

        assert result == {"asset_cache_cleanup": "cache_files_removed=1"}
        assert not old_file.exists()
        assert outside_file.exists()


def _make_runtime(
    tmp_path: Path,
) -> tuple[RuntimeMaintenance, _Maintenance, _Maintenance, _TraceRepository]:
    settings = Settings(
        llm_api_key="test",
        workspace_path=tmp_path / "workspace",
        maintenance_start_delay_seconds=0,
        maintenance_poll_interval_seconds=1,
        maintenance_memory_cleanup_interval_seconds=100,
        maintenance_skill_review_interval_seconds=200,
        maintenance_trace_cleanup_interval_seconds=300,
        maintenance_asset_cache_cleanup_interval_seconds=400,
    )
    memory = _Maintenance({"expired": 2})
    skills = _Maintenance({"reviewed": 1})
    traces = _TraceRepository()
    runtime = RuntimeMaintenance(
        settings,
        memory_maintenance=memory,
        skill_maintenance=skills,
        trace_repository=traces,
    )
    return runtime, memory, skills, traces
