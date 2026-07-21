"""Task Run lifecycle, prediction, recovery, and retry regressions."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.config import Settings
from core.models.model_usage import ModelUsageEvidence, ModelUsageSource
from core.models.pet import (
    TaskDifficulty,
    TaskRecord,
    TaskResult,
    TaskStatus,
)
from core.models.task_run import (
    RunUpdate,
    RunUpdateKind,
    RunUpdateStatus,
)
from core.services.observability_service import ObservabilityService
from core.storage.db import Database
from core.storage.execution_trace_repository import ExecutionTraceRepository
from core.storage.task_repo import TaskRepository
from core.tasks.task_run_service import TaskRunService


def _build_task_runs(
    tmp_path: Path,
) -> tuple[Settings, Database, TaskRepository, TaskRunService]:
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        task_timeout=180,
        task_retry_max_attempts=3,
        task_estimation_history_size=20,
    )
    database = Database(settings)
    database.init_database()
    repo = TaskRepository(database)
    return settings, database, repo, TaskRunService(settings, repo)


def _task(
    task_id: str,
    *,
    difficulty: TaskDifficulty = TaskDifficulty.MEDIUM,
    has_image: bool = False,
) -> TaskRecord:
    return TaskRecord(
        id=task_id,
        input_text="整理项目发布清单",
        status=TaskStatus.QUEUED,
        difficulty=difficulty,
        session_id="session-1",
        has_image=has_image,
    )


def test_task_run_records_ordered_progress_and_terminal_projection(
    tmp_path: Path,
) -> None:
    _settings, _database, repo, runs = _build_task_runs(tmp_path)
    created = runs.create(_task("run-1"))
    assert created.status == TaskStatus.QUEUED
    assert created.estimated_duration_seconds == 60

    started = runs.start("run-1")
    assert started.status == TaskStatus.RUNNING
    progressed = runs.progress(
        "run-1",
        key="verify-output",
        title="验证执行结果",
        detail="发布设置已经保存",
        step_index=2,
        max_actions=4,
    )
    assert 0.48 <= progressed.progress <= 0.5

    completed = runs.complete(
        "run-1",
        TaskResult(
            task_id="run-1",
            success=True,
            summary="发布清单已经整理完成",
        ),
    )

    assert completed.status == TaskStatus.SUCCESS
    assert completed.progress == 1.0
    assert completed.estimated_remaining_seconds == 0
    assert [update.kind for update in repo.list_run_updates("run-1")] == [
        RunUpdateKind.QUEUED,
        RunUpdateKind.STARTED,
        RunUpdateKind.PROGRESS,
        RunUpdateKind.COMPLETED,
    ]


def test_safe_stop_is_not_persisted_as_execution_failure(tmp_path: Path) -> None:
    _settings, _database, repo, runs = _build_task_runs(tmp_path)
    runs.create(_task("cancelled-run"))
    runs.start("cancelled-run")

    snapshot = runs.complete(
        "cancelled-run",
        TaskResult(
            task_id="cancelled-run",
            success=False,
            summary="任务已安全暂停",
            error_message="应用退出时停止；未自动重放",
            cancelled=True,
        ),
    )

    assert snapshot.status == TaskStatus.CANCELLED
    assert snapshot.retryable is True
    assert snapshot.updates[-1].kind == RunUpdateKind.INTERRUPTED
    assert snapshot.updates[-1].status == RunUpdateStatus.WARNING
    assert repo.get_task("cancelled-run").status == TaskStatus.CANCELLED


def test_task_result_rejects_successful_cancellation_and_wrong_owner(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError):
        TaskResult(
            task_id="invalid",
            success=True,
            cancelled=True,
        )

    _settings, _database, repo, runs = _build_task_runs(tmp_path)
    runs.create(_task("owned-run"))
    runs.start("owned-run")
    with pytest.raises(ValueError, match="reference the completed Task Run"):
        runs.complete(
            "owned-run",
            TaskResult(task_id="other-run", success=False),
        )

    assert repo.get_task("owned-run").status == TaskStatus.RUNNING
    assert repo.get_task_result("owned-run") is None


def test_duration_prediction_blends_history_with_safe_fallback(
    tmp_path: Path,
) -> None:
    _settings, _database, repo, runs = _build_task_runs(tmp_path)
    base = datetime.now() - timedelta(minutes=5)
    for index, duration in enumerate((30, 40, 50), start=1):
        repo.create_task(
            TaskRecord(
                id=f"history-{index}",
                input_text="历史任务",
                status=TaskStatus.SUCCESS,
                difficulty=TaskDifficulty.MEDIUM,
                started_at=base,
                finished_at=base + timedelta(seconds=duration),
            )
        )

    assert runs.estimate_duration(TaskDifficulty.MEDIUM) == 48


def test_restart_safe_stops_incomplete_run_and_never_replays_it(
    tmp_path: Path,
) -> None:
    settings, _database, repo, runs = _build_task_runs(tmp_path)
    runs.create(_task("interrupted"))
    runs.start("interrupted")

    recovered = TaskRunService(settings, repo).interrupt_incomplete()

    assert [snapshot.task_id for snapshot in recovered] == ["interrupted"]
    snapshot = runs.snapshot("interrupted")
    assert snapshot.status == TaskStatus.CANCELLED
    assert snapshot.retryable is True
    assert snapshot.updates[-1].kind == RunUpdateKind.INTERRUPTED
    assert "未自动重放" in snapshot.updates[-1].detail
    assert repo.get_pending_tasks() == []


def test_explicit_retry_creates_new_attempt_and_keeps_old_run_unchanged(
    tmp_path: Path,
) -> None:
    _settings, _database, repo, runs = _build_task_runs(tmp_path)
    runs.create(_task("failed"))
    runs.start("failed")
    runs.complete(
        "failed",
        TaskResult(
            task_id="failed",
            success=False,
            summary="网络暂时不可用",
            error_message="timeout",
        ),
    )

    new_task, retry = runs.retry("failed")

    assert new_task.id != "failed"
    assert retry.status == TaskStatus.QUEUED
    assert retry.attempt_no == 2
    assert retry.parent_task_id == "failed"
    assert runs.snapshot("failed").status == TaskStatus.FAILED
    assert runs.snapshot("failed").updates[-1].kind == RunUpdateKind.RETRIED
    assert repo.get_task(new_task.id) is not None


def test_retry_from_one_attempt_can_only_create_one_child(tmp_path: Path) -> None:
    _settings, _database, _repo, runs = _build_task_runs(tmp_path)
    runs.create(_task("failed-once"))
    runs.start("failed-once")
    runs.complete(
        "failed-once",
        TaskResult(task_id="failed-once", success=False, summary="未完成"),
    )
    runs.retry("failed-once")

    with pytest.raises(ValueError, match="already exists"):
        runs.retry("failed-once")


def test_progress_requires_a_running_task_run(tmp_path: Path) -> None:
    _settings, _database, repo, runs = _build_task_runs(tmp_path)
    runs.create(_task("still-queued"))

    with pytest.raises(ValueError, match="requires a running"):
        runs.progress(
            "still-queued",
            key="too-early",
            title="不应写入",
        )

    assert len(repo.list_run_updates("still-queued")) == 1


def test_retry_refuses_image_task_without_reselecting_image(tmp_path: Path) -> None:
    _settings, _database, _repo, runs = _build_task_runs(tmp_path)
    runs.create(_task("image-run", has_image=True))
    runs.start("image-run")
    runs.complete(
        "image-run",
        TaskResult(
            task_id="image-run",
            success=False,
            error_message="vision provider unavailable",
        ),
    )

    with pytest.raises(ValueError, match="selected again"):
        runs.retry("image-run")


def test_run_projection_and_updates_redact_sensitive_text(tmp_path: Path) -> None:
    _settings, _database, _repo, runs = _build_task_runs(tmp_path)
    task = _task("private")
    task.input_text = "联系 user@example.com，令牌 sk-" + "a" * 24
    runs.create(task)
    runs.start(task.id)
    snapshot = runs.progress(
        task.id,
        key="private",
        title="处理 user@example.com",
        detail="Bearer abcdef123456",
    )

    assert "user@example.com" not in snapshot.input_summary
    assert "***@***.***" in snapshot.input_summary
    assert "Bearer abcdef123456" not in snapshot.updates[-1].detail
    assert "Bearer ***" in snapshot.updates[-1].detail


def test_work_stage_dependencies_timing_and_critical_path_are_durable(
    tmp_path: Path,
) -> None:
    settings, _database, repo, runs = _build_task_runs(tmp_path)
    runs.create(_task("staged"))
    runs.start("staged")
    runs.progress(
        "staged",
        key="plan",
        title="规划工作",
        status="success",
        stage_family="computer-plan",
    )
    waiting = runs.progress(
        "staged",
        key="authorize",
        title="等待确认",
        status="warning",
        depends_on=("plan",),
        stage_family="approval",
    )

    assert waiting.stages[-1].blocked_by == ()
    assert waiting.waiting_stage_count == 1
    assert waiting.critical_path == ("plan", "authorize")
    assert waiting.critical_path_remaining_seconds > 0

    with pytest.raises(ValueError, match="dependencies succeed"):
        runs.progress(
            "staged",
            key="observe-1",
            title="观察界面",
            depends_on=("authorize",),
            stage_family="computer-observe",
        )

    runs.progress(
        "staged",
        key="authorize",
        title="确认完成",
        status="success",
        stage_family="approval",
        measured_duration_ms=2_400,
    )
    runs.progress(
        "staged",
        key="observe-1",
        title="观察界面",
        status="running",
        depends_on=("authorize",),
        stage_family="computer-observe",
    )
    observed = runs.progress(
        "staged",
        key="observe-1",
        title="界面已定位",
        status="success",
        stage_family="computer-observe",
        measured_duration_ms=6_500,
    )
    staged = runs.progress(
        "staged",
        key="act-1",
        title="等待执行",
        status="pending",
        depends_on=("observe-1",),
        stage_family="computer-act",
    )

    assert observed.stages[-1].duration_ms == 6_500
    assert staged.critical_path == ("plan", "authorize", "observe-1", "act-1")
    assert staged.critical_path_remaining_seconds == 3
    restored = TaskRunService(settings, repo).snapshot("staged")
    assert restored.stages[-2].duration_ms == 6_500
    assert restored.stages[-1].depends_on == ("observe-1",)


def test_work_stage_rejects_unknown_or_changed_dependencies(tmp_path: Path) -> None:
    _settings, _database, _repo, runs = _build_task_runs(tmp_path)
    runs.create(_task("dependency-guard"))
    runs.start("dependency-guard")

    with pytest.raises(ValueError, match="must already exist"):
        runs.progress(
            "dependency-guard",
            key="child",
            title="不应开始",
            status="pending",
            depends_on=("missing",),
        )

    runs.progress(
        "dependency-guard",
        key="root",
        title="根阶段",
        status="success",
    )
    runs.progress(
        "dependency-guard",
        key="child",
        title="子阶段",
        status="pending",
        depends_on=("root",),
    )
    runs.progress(
        "dependency-guard",
        key="other-root",
        title="另一个根阶段",
        status="success",
    )
    with pytest.raises(ValueError, match="cannot change"):
        runs.progress(
            "dependency-guard",
            key="child",
            title="篡改依赖",
            status="pending",
            depends_on=("other-root",),
        )


def test_stage_prediction_blends_exact_tool_timing_history(tmp_path: Path) -> None:
    _settings, _database, _repo, runs = _build_task_runs(tmp_path)
    for index, duration_ms in enumerate((2_000, 4_000, 6_000), start=1):
        task_id = f"tool-history-{index}"
        runs.create(_task(task_id))
        runs.start(task_id)
        runs.progress(
            task_id,
            key=f"tool:read_file:{index}",
            title="读取文件",
            status="running",
            stage_family="tool:read_file",
        )
        runs.progress(
            task_id,
            key=f"tool:read_file:{index}",
            title="读取完成",
            status="success",
            stage_family="tool:read_file",
            measured_duration_ms=duration_ms,
        )

    assert runs.estimate_stage_duration("tool:read_file") == 4
    assert runs.format_stage_duration(0) == ""
    assert runs.format_stage_duration(37) == "< 1 秒"
    assert runs.format_stage_duration(1_250) == "1.2 秒"


def test_task_run_persists_model_usage_and_learns_history_budget(
    tmp_path: Path,
) -> None:
    settings, _database, _repo, runs = _build_task_runs(tmp_path)
    for index, total in enumerate((1_000, 2_000, 3_000), start=1):
        task_id = f"usage-history-{index}"
        runs.create(_task(task_id))
        runs.start(task_id)
        runs.complete(
            task_id,
            TaskResult(
                task_id=task_id,
                success=True,
                summary="done",
                usage_evidence=ModelUsageEvidence(
                    provider_model=settings.llm_model,
                    prompt_tokens=total - 200,
                    completion_tokens=200,
                    cached_tokens=100,
                    source=ModelUsageSource.PROVIDER,
                ),
            ),
        )

    runs.create(_task("usage-other-model"))
    runs.start("usage-other-model")
    runs.complete(
        "usage-other-model",
        TaskResult(
            task_id="usage-other-model",
            success=True,
            summary="done",
            usage_evidence=ModelUsageEvidence(
                provider_model="different-model",
                prompt_tokens=99_800,
                completion_tokens=200,
                source=ModelUsageSource.PROVIDER,
            ),
        ),
    )

    next_task = _task("usage-budget")
    queued = runs.create(next_task)
    persisted = runs.snapshot("usage-history-3")

    assert queued.estimated_token_usage == 2_000
    assert persisted.usage_evidence.source == ModelUsageSource.PROVIDER
    assert persisted.usage_evidence.total_tokens == 3_000
    assert persisted.usage_evidence.cached_tokens == 100
    assert runs.format_token_usage(999) == "999"
    assert runs.format_token_usage(1_250) == "1.2k"


def test_unknown_stored_usage_source_is_not_promoted_to_evidence(
    tmp_path: Path,
) -> None:
    _settings, database, _repo, runs = _build_task_runs(tmp_path)
    runs.create(_task("legacy-usage"))
    runs.start("legacy-usage")
    runs.complete(
        "legacy-usage",
        TaskResult(task_id="legacy-usage", success=True, summary="done"),
    )
    with database.get_connection() as conn:
        conn.execute(
            """
            UPDATE task_result
            SET prompt_tokens = 500, completion_tokens = 100,
                cached_tokens = 900, usage_source = 'legacy_unknown'
            WHERE task_id = 'legacy-usage'
            """
        )
        conn.commit()

    evidence = runs.snapshot("legacy-usage").usage_evidence

    assert evidence.source == ModelUsageSource.UNAVAILABLE
    assert evidence.available is False
    assert evidence.total_tokens == 0


def test_retry_transaction_rolls_back_when_previous_update_is_invalid(
    tmp_path: Path,
) -> None:
    _settings, _database, repo, runs = _build_task_runs(tmp_path)
    runs.create(_task("previous"))
    existing_update = repo.list_run_updates("previous")[0]
    new_task = _task("should-not-exist")
    new_task.parent_task_id = "previous"
    new_task.attempt_no = 2
    queued = RunUpdate(
        id="queued-retry",
        task_id=new_task.id,
        kind=RunUpdateKind.QUEUED,
        title="retry",
        status=RunUpdateStatus.PENDING,
    )

    with pytest.raises(sqlite3.IntegrityError):
        repo.create_retry(existing_update, new_task, queued)

    assert repo.get_task(new_task.id) is None
    assert len(repo.list_run_updates("previous")) == 1


def test_observability_uses_task_run_and_real_tool_evidence(tmp_path: Path) -> None:
    _settings, database, _repo, runs = _build_task_runs(tmp_path)
    runs.create(_task("observed"))
    runs.start("observed")
    runs.complete(
        "observed",
        TaskResult(task_id="observed", success=True, summary="done"),
    )
    traces = ExecutionTraceRepository(database)
    traces.record(
        "session-1",
        "read",
        "read_file",
        {},
        "success",
        result_summary="ok",
    )
    traces.record(
        "session-1",
        "read",
        "read_file",
        {},
        "failed",
        result_summary="not found",
    )
    service = ObservabilityService(task_runs=runs, trace_repo=traces)

    summary = service.get_summary()

    assert summary["task_overview"]["total"] == 1
    assert summary["task_overview"]["success_rate"] == 100
    assert summary["recent_tasks"][0]["latest_update"] == "工作已完成"
    assert summary["tool_reliability"] == [
        {
            "tool_name": "read_file",
            "calls": 2,
            "success_rate": 50,
        }
    ]
