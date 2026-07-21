"""Deep Task Recovery Module for review, grant revocation, and safe retry."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from core.config import Settings
from core.models.pet import TaskRecord, TaskStatus
from core.models.task_recovery import (
    RecoveryEvidence,
    RecoveryTone,
    TaskRecoveryReview,
)
from core.models.task_run import RunUpdateKind, TaskRunSnapshot
from core.storage.computer_use_repo import ComputerUseRepository
from core.storage.execution_trace_repository import ExecutionTraceRepository
from core.storage.hitl_approval_repo import HitlApprovalRepository
from core.tasks.task_run_service import TaskRunService


@dataclass(frozen=True)
class PreparedTaskRetry:
    task: TaskRecord
    snapshot: TaskRunSnapshot
    revoked_grants: int


class TaskRecoveryService:
    """Own the review-before-retry invariant behind one compact Interface."""

    def __init__(
        self,
        settings: Settings,
        task_runs: TaskRunService,
        *,
        computers: ComputerUseRepository | None = None,
        traces: ExecutionTraceRepository | None = None,
        approvals: HitlApprovalRepository | None = None,
    ) -> None:
        self._settings = settings
        self._task_runs = task_runs
        self._computers = computers or ComputerUseRepository()
        self._traces = traces or ExecutionTraceRepository()
        self._approvals = approvals or HitlApprovalRepository()

    def update_settings(self, settings: Settings) -> None:
        self._settings = settings

    def invalidate_process_grants(self) -> int:
        """A restarted process can never retain a prior desktop grant."""
        return self._computers.revoke_all_authorizations()

    def review(self, task_id: str) -> TaskRecoveryReview:
        snapshot = self._task_runs.snapshot(task_id)
        plans = self._computers.list_task_plans(task_id, limit=100)
        checkpoints = [
            checkpoint
            for plan in plans
            for checkpoint in self._computers.list_checkpoint_models(plan.id)
        ]
        traces = self._traces.get_traces_for_session(task_id, limit=100)
        approvals = self._approvals.list_for_session(task_id, limit=100)
        active_grants = [plan for plan in plans if plan.authorization_is_valid()]
        approved_actions = [
            item for item in approvals if str(item.get("decision", "")) == "approved"
        ]
        last_update = self._last_stable_update(snapshot)
        possible_side_effects = bool(checkpoints or approved_actions or traces)
        reason = self._ineligible_reason(snapshot)
        eligible = not reason

        evidence = [
            RecoveryEvidence(
                label="上次进展",
                value=(
                    f"约 {round(snapshot.progress * 100)}%"
                    if snapshot.progress > 0
                    else "尚未形成稳定进展"
                ),
                detail=(
                    " · ".join(
                        item
                        for item in (
                            last_update.title if last_update else "",
                            last_update.detail if last_update else "",
                        )
                        if item
                    )
                    or "新尝试会重新规划"
                ),
                tone=RecoveryTone.SAFE if last_update else RecoveryTone.NEUTRAL,
            ),
            RecoveryEvidence(
                label="电脑操作",
                value=f"{len(checkpoints)} 个已记录动作",
                detail=(
                    f"{len(plans)} 个旧计划不会直接继续，所有授权都要重新确认"
                    if plans
                    else "没有可继承的电脑操作计划"
                ),
                tone=RecoveryTone.ATTENTION if checkpoints else RecoveryTone.NEUTRAL,
            ),
            RecoveryEvidence(
                label="工具证据",
                value=f"{len(traces)} 次工具调用",
                detail=(
                    f"其中 {len(approved_actions)} 次经过人工确认"
                    if approved_actions
                    else "不会把旧工具调用当作可以安全重放的脚本"
                ),
                tone=RecoveryTone.ATTENTION if possible_side_effects else RecoveryTone.NEUTRAL,
            ),
        ]
        safeguards = [
            "旧 Task Run 与 Run Update 保持不变",
            "不会重放旧点击、输入、命令或临时屏幕像素",
            "新 Task Run 会重新规划，并重新申请所有必要授权",
        ]
        if snapshot.has_image:
            safeguards.append("图片或屏幕选区必须由你重新选择")

        payload = self._fingerprint_payload(
            snapshot,
            plans=plans,
            checkpoints=checkpoints,
            traces=traces,
            approvals=approvals,
        )
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if eligible:
            headline = f"可以安全开始第 {snapshot.attempt_no + 1} 次尝试"
            summary = (
                "这会创建一个新的 Task Run。旧证据只用于解释上次做到哪里，"
                "不会成为自动重放指令。"
            )
        else:
            headline = "这项工作暂时不能直接重试"
            summary = reason

        return TaskRecoveryReview(
            task_id=task_id,
            eligible=eligible,
            fingerprint=fingerprint,
            headline=headline,
            summary=summary,
            reason=reason,
            next_attempt_no=snapshot.attempt_no + 1,
            progress=snapshot.progress,
            last_update_title=last_update.title if last_update else "",
            last_update_detail=last_update.detail if last_update else "",
            computer_plan_count=len(plans),
            action_checkpoint_count=len(checkpoints),
            tool_trace_count=len(traces),
            approved_action_count=len(approved_actions),
            active_grant_count=len(active_grants),
            requires_reauthorization=bool(plans),
            requires_fresh_attachment=snapshot.has_image,
            possible_side_effects=possible_side_effects,
            evidence=evidence,
            safeguards=safeguards,
        )

    def prepare_retry(
        self,
        task_id: str,
        *,
        expected_fingerprint: str,
    ) -> PreparedTaskRetry:
        current = self.review(task_id)
        if current.fingerprint != expected_fingerprint:
            raise ValueError(
                "恢复状态已经变化，请重新查看上次进展和授权状态后再试"
            )
        if not current.eligible:
            raise ValueError(current.reason or "This Task Run cannot be retried")
        revoked = self._computers.revoke_task_authorizations(task_id)
        task, snapshot = self._task_runs.retry(task_id)
        return PreparedTaskRetry(
            task=task,
            snapshot=snapshot,
            revoked_grants=revoked,
        )

    def _ineligible_reason(self, snapshot: TaskRunSnapshot) -> str:
        if snapshot.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
            return "只有失败或安全暂停的 Task Run 才能开始新的尝试。"
        if snapshot.has_image:
            return "这项工作包含图片或屏幕选区，请回到对话中重新选择后再提交。"
        if snapshot.attempt_no >= self._settings.task_retry_max_attempts:
            return f"已达到最多 {self._settings.task_retry_max_attempts} 次尝试。"
        if not snapshot.retryable:
            return "这次尝试已经创建过后续 Task Run，不能重复创建。"
        return ""

    @staticmethod
    def _last_stable_update(snapshot: TaskRunSnapshot):
        terminal = {
            RunUpdateKind.FAILED,
            RunUpdateKind.INTERRUPTED,
            RunUpdateKind.RETRIED,
        }
        return next(
            (
                update
                for update in reversed(snapshot.updates)
                if update.kind not in terminal and (update.title or update.detail)
            ),
            None,
        )

    @staticmethod
    def _fingerprint_payload(
        snapshot: TaskRunSnapshot,
        *,
        plans,
        checkpoints,
        traces,
        approvals,
    ) -> dict:
        return {
            "task": {
                "id": snapshot.task_id,
                "status": snapshot.status.value,
                "attempt": snapshot.attempt_no,
                "retryable": snapshot.retryable,
                "has_image": snapshot.has_image,
                "updates": [
                    (item.id, item.kind.value, item.status.value) for item in snapshot.updates
                ],
            },
            "plans": [
                (
                    item.id,
                    item.status.value,
                    item.completed_actions,
                    item.authorized_until.isoformat() if item.authorized_until else "",
                    item.authorization_is_valid(),
                )
                for item in plans
            ],
            "checkpoints": [
                (item.id, item.status.value, item.verification_attempts)
                for item in checkpoints
            ],
            "traces": [
                (str(item.get("id", "")), str(item.get("status", "")))
                for item in traces
            ],
            "approvals": [
                (str(item.get("id", "")), str(item.get("decision", "")))
                for item in approvals
            ],
        }
