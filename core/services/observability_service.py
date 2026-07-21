"""Observability service — aggregates runtime metrics for developer dashboard.

Reads from TokenMeter, execution traces, and HITL repository.
Never exposes secrets, API keys, or full prompts.
"""

import logging
from typing import Any, Optional

from core.runtime.token_meter import TokenMeter
from core.storage.execution_trace_repository import ExecutionTraceRepository
from core.storage.hitl_approval_repo import HitlApprovalRepository
from core.storage.task_repo import TaskRepository
from core.tasks.task_run_service import TaskRunService

logger = logging.getLogger(__name__)


class ObservabilityService:
    """Read-only service for runtime observability data."""

    def __init__(
        self,
        token_meter: Optional[TokenMeter] = None,
        trace_repo: Optional[ExecutionTraceRepository] = None,
        hitl_repo: Optional[HitlApprovalRepository] = None,
        task_repo: Optional[TaskRepository] = None,
        task_runs: Optional[TaskRunService] = None,
    ):
        self._token_meter = token_meter
        self._trace_repo = trace_repo
        self._hitl_repo = hitl_repo
        self._task_repo = task_repo
        self._task_runs = task_runs

    def get_token_overview(self) -> dict[str, Any]:
        if not self._token_meter:
            return {"available": False}
        try:
            return self._token_meter.export_metrics()
        except Exception as e:
            logger.debug("Token overview failed: %s", e)
            return {"available": False, "error": str(e)}

    def get_recent_traces(self, limit: int = 10) -> list[dict[str, Any]]:
        if not self._trace_repo:
            return []
        try:
            rows = self._trace_repo.list_recent(limit=limit)
            return [
                {
                    "session_id": r.get("session_id", ""),
                    "tool_name": r.get("tool_name", ""),
                    "status": r.get("status", "unknown"),
                    "result_summary": _truncate(r.get("result_summary", ""), 120),
                }
                for r in rows
            ]
        except Exception as e:
            logger.debug("Trace query failed: %s", e)
            return []

    def get_hitl_records(self, limit: int = 10) -> list[dict[str, Any]]:
        if not self._hitl_repo:
            return []
        try:
            rows = self._hitl_repo.list_recent(limit=limit)
            return [
                {
                    "tool_name": r.get("tool_name", ""),
                    "command_preview": r.get("command_preview", "")[:80],
                    "decision": r.get("decision", "unknown"),
                    "decided_at": r.get("decided_at", ""),
                }
                for r in rows
            ]
        except Exception as e:
            logger.debug("HITL query failed: %s", e)
            return []

    def get_recent_tasks(self, limit: int = 10) -> list[dict[str, Any]]:
        if self._task_runs:
            try:
                return [
                    {
                        "task_id": run.task_id,
                        "status": run.status.value,
                        "summary": run.input_summary,
                        "created_at": run.created_at.isoformat(),
                        "elapsed_seconds": run.elapsed_seconds,
                        "estimated_duration_seconds": (run.estimated_duration_seconds),
                        "attempt_no": run.attempt_no,
                        "retryable": run.retryable,
                        "progress": run.progress,
                        "latest_update": (run.updates[-1].title if run.updates else ""),
                        "model_usage_tokens": run.usage_evidence.total_tokens,
                        "model_usage_source": run.usage_evidence.source.value,
                        "estimated_token_usage": run.estimated_token_usage,
                    }
                    for run in self._task_runs.list_recent(limit)
                ]
            except Exception as e:
                logger.debug("Task Run query failed: %s", e)
                return []
        if not self._task_repo:
            return []
        try:
            tasks = self._task_repo.get_recent_tasks(limit=limit)
            return [
                {
                    "task_id": t.id,
                    "status": t.status.value if hasattr(t.status, "value") else str(t.status),
                    "summary": _truncate(t.input_text, 80),
                    "created_at": t.created_at.isoformat()
                    if hasattr(t.created_at, "isoformat")
                    else str(t.created_at),
                }
                for t in tasks
            ]
        except Exception as e:
            logger.debug("Task query failed: %s", e)
            return []

    def get_task_overview(self, limit: int = 50) -> dict[str, Any]:
        if not self._task_runs:
            return {"available": False}
        try:
            runs = self._task_runs.list_recent(limit)
        except Exception as e:
            logger.debug("Task overview failed: %s", e)
            return {"available": False}
        terminal = [run for run in runs if run.status.value in {"success", "failed", "cancelled"}]
        successful = [run for run in terminal if run.status.value == "success"]
        elapsed = [run.elapsed_seconds for run in terminal if run.elapsed_seconds > 0]
        retries = sum(run.attempt_no > 1 for run in runs)
        return {
            "available": True,
            "total": len(runs),
            "active": sum(run.status.value in {"created", "queued", "running"} for run in runs),
            "successful": len(successful),
            "interrupted": sum(run.status.value == "cancelled" for run in runs),
            "retry_attempts": retries,
            "success_rate": (round(len(successful) / len(terminal) * 100) if terminal else 0),
            "average_duration_seconds": (round(sum(elapsed) / len(elapsed)) if elapsed else 0),
        }

    def get_tool_reliability(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self._trace_repo:
            return []
        try:
            rows = self._trace_repo.list_recent(limit=limit)
        except Exception as e:
            logger.debug("Tool reliability query failed: %s", e)
            return []
        tools: dict[str, dict[str, int]] = {}
        for row in rows:
            name = row.get("tool_name", "") or "unknown"
            metrics = tools.setdefault(name, {"calls": 0, "successes": 0})
            metrics["calls"] += 1
            if row.get("status") == "success":
                metrics["successes"] += 1
        return [
            {
                "tool_name": name,
                "calls": metrics["calls"],
                "success_rate": round(metrics["successes"] / metrics["calls"] * 100),
            }
            for name, metrics in sorted(
                tools.items(),
                key=lambda item: (-item[1]["calls"], item[0]),
            )
        ]

    def get_error_summary(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return recent failed traces as error summary."""
        if not self._trace_repo:
            return []
        try:
            rows = self._trace_repo.list_recent(limit=limit * 3)
            errors = [
                {
                    "session_id": r.get("session_id", ""),
                    "tool_name": r.get("tool_name", ""),
                    "status": r.get("status", "unknown"),
                    "result_summary": _truncate(r.get("result_summary", ""), 120),
                    "created_at": r.get("created_at", ""),
                }
                for r in rows
                if r.get("status") != "success"
            ]
            return errors[:limit]
        except Exception as e:
            logger.debug("Error summary query failed: %s", e)
            return []

    def get_summary(self) -> dict[str, Any]:
        return {
            "token": self.get_token_overview(),
            "task_overview": self.get_task_overview(),
            "recent_tasks": self.get_recent_tasks(limit=5),
            "tool_reliability": self.get_tool_reliability(limit=100),
            "recent_traces": self.get_recent_traces(limit=5),
            "hitl_decisions": self.get_hitl_records(limit=5),
            "recent_errors": self.get_error_summary(limit=5),
        }


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
