"""Deep Task Run module for durable progress, prediction, and safe retry."""

from __future__ import annotations

import re
import statistics
import uuid
from datetime import datetime
from typing import Optional

from core.config import Settings
from core.models.model_usage import ModelUsageEvidence
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
    TaskRunSnapshot,
    WorkStage,
)
from core.storage.task_repo import TaskRepository


_FALLBACK_DURATION_SECONDS = {
    TaskDifficulty.SIMPLE: 20,
    TaskDifficulty.MEDIUM: 60,
    TaskDifficulty.COMPLEX: 120,
}

_STAGE_FALLBACK_SECONDS = {
    "memory-context": 1,
    "computer-plan": 2,
    "computer-authorize": 15,
    "computer-observe": 8,
    "computer-act": 3,
    "computer-verify": 8,
    "computer-finish": 1,
    "approval": 20,
}

_SECRET_PATTERNS = (
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "sk-***"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "ghp_***"),
    (re.compile(r"xoxb-[a-zA-Z0-9-]+"), "xoxb-***"),
    (re.compile(r"Bearer\s+[a-zA-Z0-9._-]+"), "Bearer ***"),
    (
        re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        "***@***.***",
    ),
)


class TaskRunService:
    """Own Task Run lifecycle invariants behind one compact interface."""

    def __init__(
        self,
        settings: Settings,
        repo: Optional[TaskRepository] = None,
    ) -> None:
        self._settings = settings
        self._repo = repo or TaskRepository()

    def update_settings(self, settings: Settings) -> None:
        self._settings = settings

    def create(self, task: TaskRecord) -> TaskRunSnapshot:
        """Persist a queued Task Run and its first Run Update atomically."""
        task.estimated_duration_seconds = self.estimate_duration(task.difficulty)
        task.estimated_token_usage = self.estimate_token_usage(task.difficulty)
        update = self._update(
            task.id,
            RunUpdateKind.QUEUED,
            title="已加入工作队列",
            detail=(
                f"预计约 {self.format_duration(task.estimated_duration_seconds)}"
                if task.estimated_duration_seconds
                else ""
            ),
            status=RunUpdateStatus.PENDING,
            progress=0.02,
        )
        self._repo.create_task(task, update)
        return self.snapshot(task.id)

    def start(self, task_id: str) -> TaskRunSnapshot:
        """Start one queued Task Run without duplicating start events."""
        task = self._require_task(task_id)
        if task.status == TaskStatus.RUNNING:
            return self.snapshot(task_id)
        task.start()
        update = self._update(
            task_id,
            RunUpdateKind.STARTED,
            title="开始处理",
            detail="正在规划并执行这项工作",
            status=RunUpdateStatus.RUNNING,
            progress=0.08,
        )
        if not self._repo.update_task_status(
            task_id,
            task.status,
            started_at=task.started_at,
            update=update,
        ):
            raise ValueError("Task Run does not exist")
        return self.snapshot(task_id)

    def progress(
        self,
        task_id: str,
        *,
        key: str,
        title: str,
        detail: str = "",
        status: str = "running",
        step_index: int = 0,
        max_actions: int = 0,
        depends_on: tuple[str, ...] = (),
        stage_family: str = "",
        measured_duration_ms: int = 0,
    ) -> TaskRunSnapshot:
        """Append one privacy-safe Work Stage update and refresh timing projections."""
        task = self._require_task(task_id)
        if task.status != TaskStatus.RUNNING:
            raise ValueError("Progress requires a running Task Run")
        safe_key = self._safe_text(key, 120)
        if not safe_key:
            raise ValueError("Work Stage key cannot be empty")
        current_updates = self._repo.list_run_updates(task_id, limit=500)
        current_stages = self._project_stages(
            current_updates,
            task.status,
            task.finished_at,
        )
        stage_by_key = {stage.key: stage for stage in current_stages}
        existing_stage = stage_by_key.get(safe_key)
        safe_dependencies = tuple(
            dict.fromkeys(
                self._safe_text(dependency, 120)
                for dependency in depends_on
                if self._safe_text(dependency, 120)
            )
        )
        if len(safe_dependencies) > 8:
            raise ValueError("A Work Stage supports at most 8 dependencies")
        if safe_key in safe_dependencies:
            raise ValueError("A Work Stage cannot depend on itself")
        if existing_stage is not None:
            if safe_dependencies and safe_dependencies != existing_stage.depends_on:
                raise ValueError("Work Stage dependencies cannot change")
            safe_dependencies = existing_stage.depends_on
        else:
            missing = [
                dependency for dependency in safe_dependencies if dependency not in stage_by_key
            ]
            if missing:
                raise ValueError("Work Stage dependencies must already exist")
            self._validate_stage_graph(stage_by_key, safe_key, safe_dependencies)

        update_status = self._progress_status(status)
        if update_status in {RunUpdateStatus.RUNNING, RunUpdateStatus.SUCCESS}:
            blocked = [
                dependency
                for dependency in safe_dependencies
                if stage_by_key[dependency].status != RunUpdateStatus.SUCCESS
            ]
            if blocked:
                raise ValueError("Work Stage cannot run before its dependencies succeed")
        previous_progress = max(
            (update.progress for update in current_updates),
            default=0.08,
        )
        if step_index > 0 and max_actions > 0:
            action_progress = min(1.0, step_index / max_actions)
            progress = 0.1 + action_progress * 0.78
        else:
            progress = (
                min(0.86, previous_progress + 0.04) if existing_stage is None else previous_progress
            )
        progress = max(previous_progress, progress)
        family = self._safe_text(stage_family, 80) or self._stage_family(safe_key)
        estimate = (
            existing_stage.estimated_duration_seconds
            if existing_stage is not None and existing_stage.estimated_duration_seconds
            else self.estimate_stage_duration(family)
        )
        now = datetime.now()
        duration_ms = max(0, min(86_400_000, measured_duration_ms))
        if (
            duration_ms <= 0
            and existing_stage is not None
            and update_status in {RunUpdateStatus.SUCCESS, RunUpdateStatus.FAILED}
        ):
            duration_ms = max(
                0,
                min(
                    86_400_000,
                    int((now - existing_stage.started_at).total_seconds() * 1000),
                ),
            )
        update = self._update(
            task_id,
            RunUpdateKind.PROGRESS,
            key=safe_key,
            title=title,
            detail=detail,
            status=update_status,
            progress=progress,
            stage_family=family,
            depends_on=safe_dependencies,
            estimated_duration_seconds=estimate,
            duration_ms=duration_ms,
            created_at=now,
        )
        self._repo.append_run_update(update)
        return self.snapshot(task_id)

    def complete(
        self,
        task_id: str,
        result: TaskResult,
    ) -> TaskRunSnapshot:
        """Persist outcome, terminal status, and Run Update atomically."""
        if result.task_id != task_id:
            raise ValueError("Task result must reference the completed Task Run")
        task = self._require_task(task_id)
        if result.success and task.status in {
            TaskStatus.CREATED,
            TaskStatus.QUEUED,
        }:
            self.start(task_id)
            task = self._require_task(task_id)
        if result.cancelled:
            task.cancel()
            update_kind = RunUpdateKind.INTERRUPTED
            update_title = "已安全暂停"
            update_detail = result.error_message or result.summary
            update_status = RunUpdateStatus.WARNING
        elif result.success:
            task.complete(True)
            update_kind = RunUpdateKind.COMPLETED
            update_title = "工作已完成"
            update_detail = result.summary
            update_status = RunUpdateStatus.SUCCESS
        else:
            task.complete(False)
            update_kind = RunUpdateKind.FAILED
            update_title = "这次没有完成"
            update_detail = result.error_message or result.summary
            update_status = RunUpdateStatus.FAILED
        update = self._update(
            task_id,
            update_kind,
            title=update_title,
            detail=update_detail,
            status=update_status,
            progress=1.0 if result.success else self._latest_progress(task_id),
        )
        self._repo.save_result_and_status(
            result,
            task.status,
            task.finished_at or datetime.now(),
            update,
        )
        return self.snapshot(task_id)

    def interrupt_incomplete(self) -> list[TaskRunSnapshot]:
        """Safe-stop work left incomplete by a prior process; never replay it."""
        interrupted: list[TaskRunSnapshot] = []
        for task in self._repo.get_incomplete_tasks():
            task.cancel()
            message = "应用重新启动，未自动重放这项工作以避免重复副作用"
            update = self._update(
                task.id,
                RunUpdateKind.INTERRUPTED,
                title="已安全暂停",
                detail=message,
                status=RunUpdateStatus.WARNING,
                progress=self._latest_progress(task.id),
            )
            result = TaskResult(
                task_id=task.id,
                success=False,
                summary="任务在应用重启后安全暂停",
                error_message=message,
            )
            self._repo.save_result_and_status(
                result,
                task.status,
                task.finished_at or datetime.now(),
                update,
            )
            interrupted.append(self.snapshot(task.id))
        return interrupted

    def retry(self, task_id: str) -> tuple[TaskRecord, TaskRunSnapshot]:
        """Create a linked Task Run after explicit user intent."""
        previous = self._require_task(task_id)
        if previous.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
            raise ValueError("Only failed or interrupted Task Runs can be retried")
        if previous.has_image:
            raise ValueError("Image tasks require the image to be selected again")
        if self._repo.get_retry_for_parent(previous.id) is not None:
            raise ValueError("A retry already exists for this Task Run")
        max_attempts = self._settings.task_retry_max_attempts
        if previous.attempt_no >= max_attempts:
            raise ValueError(f"Retry limit reached ({max_attempts} attempts)")

        new_task = TaskRecord(
            id=str(uuid.uuid4()),
            input_text=previous.input_text,
            task_type=previous.task_type,
            status=TaskStatus.QUEUED,
            difficulty=previous.difficulty,
            reward_exp=previous.reward_exp,
            session_id=previous.session_id,
            estimated_duration_seconds=self.estimate_duration(previous.difficulty),
            estimated_token_usage=self.estimate_token_usage(previous.difficulty),
            attempt_no=previous.attempt_no + 1,
            parent_task_id=previous.id,
            has_image=False,
        )
        previous_update = self._update(
            previous.id,
            RunUpdateKind.RETRIED,
            title=f"已创建第 {new_task.attempt_no} 次尝试",
            detail="由你明确选择重试；旧尝试保持不变",
            status=RunUpdateStatus.WARNING,
            progress=self._latest_progress(previous.id),
        )
        queued_update = self._update(
            new_task.id,
            RunUpdateKind.QUEUED,
            title=f"第 {new_task.attempt_no} 次尝试已排队",
            detail=f"预计约 {self.format_duration(new_task.estimated_duration_seconds)}",
            status=RunUpdateStatus.PENDING,
            progress=0.02,
        )
        self._repo.create_retry(previous_update, new_task, queued_update)
        return new_task, self.snapshot(new_task.id)

    def snapshot(self, task_id: str) -> TaskRunSnapshot:
        task = self._require_task(task_id)
        updates = self._repo.list_run_updates(task_id, limit=500)
        result = self._repo.get_task_result(task_id)
        end = task.finished_at or datetime.now()
        elapsed = max(0, int((end - task.started_at).total_seconds())) if task.started_at else 0
        estimate = task.estimated_duration_seconds
        remaining = (
            max(0, estimate - elapsed)
            if task.status == TaskStatus.RUNNING and estimate
            else (estimate if task.status == TaskStatus.QUEUED else 0)
        )
        if task.status == TaskStatus.SUCCESS:
            progress = 1.0
        else:
            progress = max(
                (update.progress for update in updates),
                default=0.02 if task.status == TaskStatus.QUEUED else 0.0,
            )
        retryable = (
            task.status in {TaskStatus.FAILED, TaskStatus.CANCELLED}
            and not task.has_image
            and task.attempt_no < self._settings.task_retry_max_attempts
            and self._repo.get_retry_for_parent(task.id) is None
        )
        stages = self._project_stages(updates, task.status, task.finished_at)
        critical_path, critical_remaining = self._critical_path(
            stages,
            terminal=task.status
            in {
                TaskStatus.SUCCESS,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            },
        )
        return TaskRunSnapshot(
            task_id=task.id,
            input_summary=self._safe_text(task.input_text, 140),
            session_id=task.session_id,
            status=task.status,
            difficulty=task.difficulty,
            attempt_no=task.attempt_no,
            parent_task_id=task.parent_task_id,
            has_image=task.has_image,
            estimated_duration_seconds=estimate,
            estimated_token_usage=task.estimated_token_usage,
            elapsed_seconds=elapsed,
            estimated_remaining_seconds=remaining,
            progress=progress,
            retryable=retryable,
            outcome_summary=self._safe_text(result.summary, 500) if result else "",
            error_message=(self._safe_text(result.error_message or "", 500) if result else ""),
            usage_evidence=result.usage_evidence if result else ModelUsageEvidence(),
            created_at=task.created_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
            updates=updates,
            stages=stages,
            critical_path=critical_path,
            critical_path_remaining_seconds=critical_remaining,
        )

    def list_recent(self, limit: int = 20) -> list[TaskRunSnapshot]:
        return [
            self.snapshot(task.id) for task in self._repo.get_recent_tasks(max(1, min(100, limit)))
        ]

    def estimate_duration(self, difficulty: TaskDifficulty) -> int:
        fallback = min(
            self._settings.task_timeout,
            _FALLBACK_DURATION_SECONDS[difficulty],
        )
        durations = self._repo.get_completed_durations(
            difficulty.value,
            self._settings.task_estimation_history_size,
        )
        if not durations:
            return fallback
        median = int(statistics.median(durations))
        history_weight = min(5, len(durations))
        estimate = round((median * history_weight + fallback * 2) / (history_weight + 2))
        return max(5, min(self._settings.task_timeout, estimate))

    def estimate_stage_duration(self, stage_family: str) -> int:
        """Blend measured Work Stage history with a conservative family fallback."""
        family = self._safe_text(stage_family, 80) or "work"
        fallback = self._stage_fallback(family)
        durations_ms = self._repo.get_completed_stage_durations(
            family,
            self._settings.task_estimation_history_size,
        )
        if not durations_ms:
            return fallback
        median_seconds = max(1, round(statistics.median(durations_ms) / 1000))
        history_weight = min(5, len(durations_ms))
        estimate = round((median_seconds * history_weight + fallback * 2) / (history_weight + 2))
        return max(1, min(self._settings.task_timeout, estimate))

    def estimate_token_usage(self, difficulty: TaskDifficulty) -> int:
        """Freeze a history-backed budget only after enough comparable evidence exists."""
        usages = self._repo.get_completed_token_usage(
            difficulty.value,
            self._settings.llm_model,
            self._settings.task_estimation_history_size,
        )
        if len(usages) < 3:
            return 0
        return max(1, min(10_000_000, round(statistics.median(usages))))

    @staticmethod
    def format_duration(seconds: int) -> str:
        if seconds < 60:
            return f"{max(1, seconds)} 秒"
        minutes, remainder = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes} 分钟" if remainder < 30 else f"约 {minutes + 1} 分钟"
        hours, minutes = divmod(minutes, 60)
        return f"{hours} 小时" if not minutes else f"{hours} 小时 {minutes} 分钟"

    @staticmethod
    def format_stage_duration(duration_ms: int) -> str:
        if duration_ms <= 0:
            return ""
        if duration_ms < 1000:
            return "< 1 秒"
        if duration_ms < 60_000:
            seconds = duration_ms / 1000
            return f"{seconds:.1f} 秒" if duration_ms % 1000 else f"{int(seconds)} 秒"
        return TaskRunService.format_duration(round(duration_ms / 1000))

    @staticmethod
    def format_token_usage(tokens: int) -> str:
        if tokens < 1000:
            return f"{max(0, tokens):,}"
        if tokens < 1_000_000:
            value = tokens / 1000
            return f"{value:.1f}k" if tokens % 1000 else f"{int(value)}k"
        value = tokens / 1_000_000
        return f"{value:.1f}m" if tokens % 1_000_000 else f"{int(value)}m"

    def _require_task(self, task_id: str) -> TaskRecord:
        task = self._repo.get_task(task_id)
        if task is None:
            raise ValueError("Task Run does not exist")
        return task

    def _latest_progress(self, task_id: str) -> float:
        return max(
            (update.progress for update in self._repo.list_run_updates(task_id, limit=500)),
            default=0.0,
        )

    @staticmethod
    def _progress_status(status: str) -> RunUpdateStatus:
        return {
            "pending": RunUpdateStatus.PENDING,
            "running": RunUpdateStatus.RUNNING,
            "success": RunUpdateStatus.SUCCESS,
            "warning": RunUpdateStatus.WARNING,
            "failed": RunUpdateStatus.FAILED,
        }.get(status, RunUpdateStatus.RUNNING)

    def _update(
        self,
        task_id: str,
        kind: RunUpdateKind,
        *,
        title: str,
        detail: str = "",
        status: RunUpdateStatus,
        progress: float,
        key: str = "",
        stage_family: str = "",
        depends_on: tuple[str, ...] = (),
        estimated_duration_seconds: int = 0,
        duration_ms: int = 0,
        created_at: datetime | None = None,
    ) -> RunUpdate:
        return RunUpdate(
            id=str(uuid.uuid4()),
            task_id=task_id,
            kind=kind,
            key=self._safe_text(key, 120),
            title=self._safe_text(title, 160),
            detail=self._safe_text(detail, 500),
            status=status,
            progress=max(0.0, min(1.0, progress)),
            stage_family=self._safe_text(stage_family, 80),
            depends_on=depends_on,
            estimated_duration_seconds=max(
                0,
                min(86_400, estimated_duration_seconds),
            ),
            duration_ms=max(0, min(86_400_000, duration_ms)),
            created_at=created_at or datetime.now(),
        )

    def _project_stages(
        self,
        updates: list[RunUpdate],
        task_status: TaskStatus,
        task_finished_at: datetime | None,
    ) -> list[WorkStage]:
        grouped: dict[str, list[RunUpdate]] = {}
        for update in updates:
            if update.kind == RunUpdateKind.PROGRESS and update.key:
                grouped.setdefault(update.key, []).append(update)
        now = task_finished_at or datetime.now()
        stages: list[WorkStage] = []
        for key, stage_updates in grouped.items():
            first = stage_updates[0]
            latest = stage_updates[-1]
            status = latest.status
            if task_status in {TaskStatus.FAILED, TaskStatus.CANCELLED} and status in {
                RunUpdateStatus.PENDING,
                RunUpdateStatus.RUNNING,
                RunUpdateStatus.WARNING,
            }:
                status = (
                    RunUpdateStatus.FAILED
                    if task_status == TaskStatus.FAILED
                    else RunUpdateStatus.WARNING
                )
            finished_at = (
                latest.created_at
                if status in {RunUpdateStatus.SUCCESS, RunUpdateStatus.FAILED}
                else (
                    task_finished_at
                    if task_status in {TaskStatus.FAILED, TaskStatus.CANCELLED}
                    else None
                )
            )
            duration_ms = latest.duration_ms
            if duration_ms <= 0:
                duration_end = finished_at or now
                duration_ms = max(
                    0,
                    min(
                        86_400_000,
                        int((duration_end - first.created_at).total_seconds() * 1000),
                    ),
                )
            stages.append(
                WorkStage(
                    key=key,
                    family=latest.stage_family or first.stage_family,
                    title=latest.title or first.title,
                    detail=latest.detail,
                    status=status,
                    depends_on=latest.depends_on or first.depends_on,
                    estimated_duration_seconds=(
                        latest.estimated_duration_seconds or first.estimated_duration_seconds
                    ),
                    duration_ms=duration_ms,
                    started_at=first.created_at,
                    finished_at=finished_at,
                    update_count=len(stage_updates),
                )
            )
        stage_by_key = {stage.key: stage for stage in stages}
        return [
            stage.model_copy(
                update={
                    "blocked_by": tuple(
                        dependency
                        for dependency in stage.depends_on
                        if (
                            dependency in stage_by_key
                            and stage_by_key[dependency].status != RunUpdateStatus.SUCCESS
                        )
                    )
                }
            )
            for stage in stages
        ]

    @staticmethod
    def _validate_stage_graph(
        existing: dict[str, WorkStage],
        new_key: str,
        dependencies: tuple[str, ...],
    ) -> None:
        graph = {key: stage.depends_on for key, stage in existing.items()}
        graph[new_key] = dependencies
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise ValueError("Work Stage dependencies cannot form a cycle")
            if key in visited:
                return
            visiting.add(key)
            for dependency in graph.get(key, ()):
                visit(dependency)
            visiting.remove(key)
            visited.add(key)

        visit(new_key)

    @staticmethod
    def _critical_path(
        stages: list[WorkStage],
        *,
        terminal: bool,
    ) -> tuple[tuple[str, ...], int]:
        if terminal or not stages or not any(stage.depends_on for stage in stages):
            return (), 0
        stage_by_key = {stage.key: stage for stage in stages}
        costs: dict[str, int] = {}
        paths: dict[str, tuple[str, ...]] = {}
        for stage in stages:
            elapsed_seconds = round(stage.duration_ms / 1000)
            own_cost = (
                0
                if stage.status == RunUpdateStatus.SUCCESS
                else max(0, stage.estimated_duration_seconds - elapsed_seconds)
            )
            candidates = [
                (costs[dependency], paths[dependency])
                for dependency in stage.depends_on
                if dependency in costs
            ]
            prior_cost, prior_path = max(candidates, default=(0, ()))
            costs[stage.key] = prior_cost + own_cost
            paths[stage.key] = (*prior_path, stage.key)
        critical_key = max(costs, key=costs.get)
        remaining = costs[critical_key]
        return (paths[critical_key], remaining) if remaining > 0 else ((), 0)

    @staticmethod
    def _stage_family(key: str) -> str:
        family = re.sub(r"[-:]\d+$", "", key.strip().lower())
        return family[:80] or "work"

    @staticmethod
    def _stage_fallback(family: str) -> int:
        if family.startswith("tool:"):
            return 5
        return _STAGE_FALLBACK_SECONDS.get(family, 6)

    @staticmethod
    def _safe_text(value: str, limit: int) -> str:
        safe = " ".join((value or "").split())
        for pattern, replacement in _SECRET_PATTERNS:
            safe = pattern.sub(replacement, safe)
        return safe[:limit]
