"""Task Recovery review, freshness, and grant-revocation regressions."""

from datetime import timedelta
from pathlib import Path

import pytest

from core.computer_use.models import (
    ComputerAction,
    ComputerActionType,
    ComputerPlanStatus,
    utc_now,
)
from core.config import Settings
from core.models.pet import TaskDifficulty, TaskRecord, TaskResult, TaskStatus
from core.storage.computer_use_repo import ComputerUseRepository
from core.storage.db import Database
from core.storage.execution_trace_repository import ExecutionTraceRepository
from core.storage.hitl_approval_repo import HitlApprovalRepository
from core.storage.task_repo import TaskRepository
from core.tasks.task_recovery_service import TaskRecoveryService
from core.tasks.task_run_service import TaskRunService


def _build_recovery(tmp_path: Path):
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        task_retry_max_attempts=3,
    )
    database = Database(settings)
    database.init_database()
    task_repo = TaskRepository(database)
    task_runs = TaskRunService(settings, task_repo)
    computers = ComputerUseRepository(database)
    traces = ExecutionTraceRepository(database)
    approvals = HitlApprovalRepository(database)
    recovery = TaskRecoveryService(
        settings,
        task_runs,
        computers=computers,
        traces=traces,
        approvals=approvals,
    )
    return settings, database, task_runs, computers, traces, approvals, recovery


def _failed_run(task_runs: TaskRunService, task_id: str, *, has_image: bool = False):
    task_runs.create(
        TaskRecord(
            id=task_id,
            input_text="打开发布设置并完成核对",
            status=TaskStatus.QUEUED,
            difficulty=TaskDifficulty.MEDIUM,
            session_id="session-1",
            has_image=has_image,
        )
    )
    task_runs.start(task_id)
    if not has_image:
        task_runs.progress(
            task_id,
            key="open-settings",
            title="打开发布设置",
            detail="已经进入设置页面",
            status="success",
            step_index=1,
            max_actions=4,
        )
    task_runs.complete(
        task_id,
        TaskResult(
            task_id=task_id,
            success=False,
            summary="核对尚未完成",
            error_message="provider timeout",
        ),
    )


def _authorized_plan(
    computers: ComputerUseRepository,
    *,
    task_id: str,
):
    plan, resumed = computers.create_or_resume_plan(
        session_id="session-1",
        task_id=task_id,
        goal="完成发布前核对",
        target_app="editor",
        allowed_actions=[ComputerActionType.CLICK],
        max_actions=4,
    )
    assert resumed is False
    plan = computers.authorize(plan.id, utc_now() + timedelta(minutes=10))
    computers.record_action(
        plan,
        ComputerAction(
            action=ComputerActionType.CLICK,
            x=40,
            y=50,
            description="打开发布设置",
        ),
        success=True,
        result_summary="已打开",
    )
    return plan


def test_review_explains_prior_evidence_without_treating_it_as_replay(
    tmp_path: Path,
) -> None:
    _, _, runs, computers, traces, approvals, recovery = _build_recovery(tmp_path)
    _failed_run(runs, "run-1")
    _authorized_plan(computers, task_id="run-1")
    traces.record(
        "run-1",
        "computer_use",
        "computer_act",
        {"action": "click", "text": "must be redacted"},
        "completed",
    )
    approvals.log_decision(
        session_id="run-1",
        tool_name="computer_authorize",
        command="bounded plan",
        working_dir="",
        affected_paths=(),
        risk_tags=("computer_use",),
        reason="plan authorization",
        approved=True,
        decision_reason="user approved",
    )

    review = recovery.review("run-1")

    assert review.eligible is True
    assert review.next_attempt_no == 2
    assert review.action_checkpoint_count == 1
    assert review.tool_trace_count == 1
    assert review.approved_action_count == 1
    assert review.active_grant_count == 1
    assert review.requires_reauthorization is True
    assert review.possible_side_effects is True
    assert review.last_update_title == "打开发布设置"
    assert "重放" in " ".join(review.safeguards)
    assert "bounded plan" not in review.model_dump_json()


def test_prepare_retry_revokes_old_grant_and_creates_new_task_run(
    tmp_path: Path,
) -> None:
    _, _, runs, computers, _, _, recovery = _build_recovery(tmp_path)
    _failed_run(runs, "run-1")
    plan = _authorized_plan(computers, task_id="run-1")
    review = recovery.review("run-1")

    prepared = recovery.prepare_retry(
        "run-1",
        expected_fingerprint=review.fingerprint,
    )

    assert prepared.revoked_grants == 1
    assert prepared.task.id != "run-1"
    assert prepared.task.parent_task_id == "run-1"
    assert prepared.snapshot.attempt_no == 2
    assert computers.get_plan(plan.id).status == ComputerPlanStatus.PAUSED
    assert computers.get_plan(plan.id).authorized_until is None
    assert runs.snapshot("run-1").retryable is False


def test_changed_evidence_invalidates_recovery_confirmation(tmp_path: Path) -> None:
    _, _, runs, _, traces, _, recovery = _build_recovery(tmp_path)
    _failed_run(runs, "run-1")
    review = recovery.review("run-1")
    traces.record(
        "run-1",
        "local_open",
        "local_open",
        {},
        "completed",
    )

    with pytest.raises(ValueError, match="恢复状态已经变化"):
        recovery.prepare_retry(
            "run-1",
            expected_fingerprint=review.fingerprint,
        )

    assert runs.snapshot("run-1").retryable is True


def test_authorization_expiry_invalidates_recovery_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _, _, runs, computers, _, _, recovery = _build_recovery(tmp_path)
    _failed_run(runs, "run-1")
    plan = _authorized_plan(computers, task_id="run-1")
    validity = {"active": True}
    monkeypatch.setattr(
        type(plan),
        "authorization_is_valid",
        lambda _plan: validity["active"],
    )

    current = recovery.review("run-1")
    validity["active"] = False
    expired = recovery.review("run-1")

    assert current.active_grant_count == 1
    assert expired.active_grant_count == 0
    assert expired.fingerprint != current.fingerprint


def test_image_run_requires_fresh_attachment_instead_of_retry(tmp_path: Path) -> None:
    _, _, runs, _, _, _, recovery = _build_recovery(tmp_path)
    _failed_run(runs, "image-run", has_image=True)

    review = recovery.review("image-run")

    assert review.eligible is False
    assert review.requires_fresh_attachment is True
    assert "重新选择" in review.reason


def test_computer_plan_resume_is_scoped_to_one_task_run(tmp_path: Path) -> None:
    _, _, _, computers, _, _, _ = _build_recovery(tmp_path)
    first, _ = computers.create_or_resume_plan(
        session_id="session-1",
        task_id="run-1",
        goal="保存文件",
        target_app="editor",
        allowed_actions=[ComputerActionType.CLICK],
        max_actions=3,
    )
    second, resumed = computers.create_or_resume_plan(
        session_id="session-1",
        task_id="run-2",
        goal="保存文件",
        target_app="editor",
        allowed_actions=[ComputerActionType.CLICK],
        max_actions=3,
    )

    assert resumed is False
    assert second.id != first.id
    assert {plan.id for plan in computers.list_task_plans("run-1")} == {first.id}
    assert {plan.id for plan in computers.list_task_plans("run-2")} == {second.id}


def test_process_restart_invalidates_every_active_desktop_grant(
    tmp_path: Path,
) -> None:
    _, _, _, computers, _, _, recovery = _build_recovery(tmp_path)
    first = _authorized_plan(computers, task_id="run-1")
    second = _authorized_plan(computers, task_id="run-2")

    assert recovery.invalidate_process_grants() == 2
    assert computers.get_plan(first.id).status == ComputerPlanStatus.PAUSED
    assert computers.get_plan(second.id).status == ComputerPlanStatus.PAUSED


def test_existing_computer_plan_table_is_migrated_with_task_ownership(
    tmp_path: Path,
) -> None:
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        workspace_path=tmp_path / "workspace",
    )
    database = Database(settings)
    with database.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE computer_use_plan (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                target_app TEXT NOT NULL DEFAULT '',
                allowed_actions_json TEXT NOT NULL,
                max_actions INTEGER NOT NULL,
                completed_actions INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                authorized_until TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    ComputerUseRepository(database)

    with database.get_connection() as conn:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(computer_use_plan)")
        }
        indexes = {
            row["name"] for row in conn.execute("PRAGMA index_list(computer_use_plan)")
        }
    assert "task_id" in columns
    assert "idx_computer_use_plan_task" in indexes
