"""Independent, content-minimized provenance verification for skill candidates."""

from __future__ import annotations

from typing import Protocol

from core.models.pet import TaskStatus
from core.models.task_run import TaskRunOutcomeEvidence
from core.skills.skill_schema import (
    CandidateSource,
    ProvenanceStatus,
    SkillCandidate,
    SkillCandidateProvenance,
)


class TaskRunEvidenceReader(Protocol):
    """Read only the Task Run facts needed for provenance verification."""

    def get_outcome_evidence(
        self,
        task_id: str,
    ) -> TaskRunOutcomeEvidence | None:
        ...


class TaskToolEvidenceReader(Protocol):
    """Adapter over persisted, successful tool-call evidence."""

    def get_completed_tools_for_task(
        self,
        task_id: str,
        limit: int = 200,
    ) -> list[str]:
        ...


class SkillCandidateProvenanceVerifier:
    """Verify an evolution claim without retaining task or tool content."""

    def __init__(
        self,
        task_runs: TaskRunEvidenceReader | None = None,
        tool_traces: TaskToolEvidenceReader | None = None,
    ) -> None:
        self._task_runs = task_runs
        self._tool_traces = tool_traces

    def verify(self, candidate: SkillCandidate) -> SkillCandidateProvenance:
        if candidate.source_kind != CandidateSource.SUCCESSFUL_TASK:
            return SkillCandidateProvenance(
                source_kind=candidate.source_kind,
                status=ProvenanceStatus.NOT_REQUIRED,
                detail="该提案不宣称来自自动学习，无需 Task Run 来源证明",
            )

        task_id = (candidate.source_task_id or "").strip()
        declared_tools = self._tool_names(candidate.evidence.get("tools", []))
        if self._task_runs is None or self._tool_traces is None:
            return self._unverified(
                candidate,
                declared_tools,
                task_id=task_id or None,
                detail="Task Run 来源证据读取器不可用",
            )
        if not task_id:
            return self._unverified(
                candidate,
                declared_tools,
                detail="自动进化提案缺少来源 Task Run",
            )

        outcome = self._task_runs.get_outcome_evidence(task_id)
        if outcome is None:
            return self._unverified(
                candidate,
                declared_tools,
                task_id=task_id,
                detail="没有找到来源 Task Run",
            )

        task_result_verified = bool(outcome.status == TaskStatus.SUCCESS and outcome.result_success)
        session_binding_verified = bool(
            candidate.source_session_id
            and outcome.session_id
            and candidate.source_session_id == outcome.session_id
        )
        observed_tools = self._tool_names(self._tool_traces.get_completed_tools_for_task(task_id))
        observed = set(observed_tools)
        missing_tools = [tool for tool in declared_tools if tool not in observed]

        failures: list[str] = []
        if not task_result_verified:
            failures.append("Task Run 没有可核验的成功结果")
        if not session_binding_verified:
            failures.append("Task Run 与来源会话不匹配")
        if not declared_tools:
            failures.append("提案没有声明形成该流程的工具")
        if missing_tools:
            failures.append("缺少已完成的工具轨迹：" + "、".join(missing_tools))

        status = ProvenanceStatus.UNVERIFIED if failures else ProvenanceStatus.VERIFIED
        detail = (
            "来源 Task Run、成功结果和工具轨迹已独立核验"
            if status == ProvenanceStatus.VERIFIED
            else "；".join(failures)
        )
        return SkillCandidateProvenance(
            source_kind=candidate.source_kind,
            status=status,
            task_id=task_id,
            task_status=outcome.status.value,
            task_result_verified=task_result_verified,
            session_binding_verified=session_binding_verified,
            declared_tools=declared_tools,
            observed_tools=observed_tools,
            missing_tools=missing_tools,
            detail=detail,
        )

    @staticmethod
    def _tool_names(raw_tools: object) -> list[str]:
        if not isinstance(raw_tools, (list, tuple, set)):
            return []
        return list(dict.fromkeys(str(tool).strip() for tool in raw_tools if str(tool).strip()))

    @staticmethod
    def _unverified(
        candidate: SkillCandidate,
        declared_tools: list[str],
        *,
        task_id: str | None = None,
        detail: str,
    ) -> SkillCandidateProvenance:
        return SkillCandidateProvenance(
            source_kind=candidate.source_kind,
            status=ProvenanceStatus.UNVERIFIED,
            task_id=task_id,
            declared_tools=declared_tools,
            missing_tools=declared_tools,
            detail=detail,
        )
