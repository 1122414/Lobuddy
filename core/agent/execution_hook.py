"""5.4 ExecutionGovernanceHook — nanobot hook that enforces task-level execution constraints."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from core.agent.execution_budget import ExecutionBudget
from core.agent.execution_intent import ExecutionIntent, ExecutionRoute

logger = logging.getLogger("lobuddy.execution_hook")

_RECURSIVE_SEARCH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"where\s+/R", re.IGNORECASE),
    re.compile(r"dir\s+/s", re.IGNORECASE),
    re.compile(r"Get-ChildItem\s+-Recurse", re.IGNORECASE),
]

_FORBIDDEN_DIR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"C:\\Program Files", re.IGNORECASE),
    re.compile(r"C:\\Program Files\s+\(x86\)", re.IGNORECASE),
    re.compile(r"C:\\Users\\.+?\\AppData", re.IGNORECASE),
    re.compile(r"%APPDATA%", re.IGNORECASE),
    re.compile(r"AppData", re.IGNORECASE),
]

_BLOCK_EXEC_MSG = (
    "Execution governance: exec tool is blocked for this task type ({intent}). "
    "Use local_app_resolve to find candidates, then local_open to open one."
)

_BLOCK_RECURSIVE_MSG = (
    "Execution governance: recursive search ({pattern}) is blocked for this task type ({intent}). "
    "Use local_app_resolve for controlled desktop/start menu search."
)

_BLOCK_PROGRAM_FILES_MSG = (
    "Execution governance: searching Program Files or AppData is blocked for this task type "
    "({intent}). The user's requested app should be on Desktop or Start Menu. "
    "If not found, report that to the user instead of expanding search."
)

_BLOCK_BUDGET_MSG = (
    "Execution budget exceeded: {total}/{max_total} total calls, "
    "{shell}/{max_shell} shell calls. Stop searching and provide a concise result."
)

_BLOCK_RESOLVER_HAS_CANDIDATE_MSG = (
    "Execution governance: local_app_resolve already returned high-confidence candidates. "
    "Use local_open to open the best match instead of continuing to search."
)


def _has_high_confidence_candidate(result: Any) -> bool:
    try:
        data = json.loads(result) if isinstance(result, str) else result
        for candidate in data.get("candidates", []):
            if candidate.get("openable") and candidate.get("confidence", 0) >= 0.9:
                return True
    except (json.JSONDecodeError, TypeError):
        pass
    return False


class ExecutionGovernanceHook:
    """Nanobot hook that enforces execution governance rules.

    Plugged into bot.run() as a hook alongside _ToolTracker.
    """

    def __init__(
        self,
        route: ExecutionRoute,
        budget: ExecutionBudget,
        session_id: str = "",
        trace_repo: Any = None,
        guardrails: Any = None,
        iteration: int = 0,
    ) -> None:
        self._route = route
        self._budget = budget
        self._session_id = session_id
        self._trace_repo = trace_repo
        self._guardrails = guardrails
        self._iteration = iteration

    @property
    def traces(self) -> list[dict[str, Any]]:
        return []

    def wants_streaming(self) -> bool:
        return False

    def finalize_content(self, context: Any, content: str | None) -> str | None:
        return content

    async def before_execute_tools(self, context: Any) -> None:
        if not self._budget.enabled:
            return

        for tc in context.tool_calls:
            try:
                self._enforce_tool_governance(tc)
            except RuntimeError:
                self._record_trace(tc, "blocked")
                raise

    async def after_iteration(self, context: Any) -> None:
        if not self._budget.enabled:
            return

        self._iteration += 1

        for tc in getattr(context, "tool_calls", []):
            self._budget.record_tool_call(tc.name)

        tool_calls = getattr(context, "tool_calls", [])
        tool_results = getattr(context, "tool_results", [])
        for tc, result in zip(tool_calls, tool_results):
            if tc.name == "local_app_resolve" and _has_high_confidence_candidate(result):
                self._budget.record_high_confidence_candidate()
            self._record_trace(tc, "completed", result)

    def _enforce_tool_governance(self, tc: Any) -> None:
        tool_name = getattr(tc, "name", "")
        arguments = getattr(tc, "arguments", {})

        if self._route.intent == ExecutionIntent.LOCAL_OPEN_TARGET and tool_name == "exec":
            if self._budget.block_shell_for_local_open:
                raise RuntimeError(
                    _BLOCK_EXEC_MSG.format(intent=self._route.intent.value)
                )

        if tool_name == "exec":
            command = arguments.get("command", "")
            self._check_recursive_search(command)
            self._check_forbidden_directories(command)

        self._check_budget_exceeded()

        if self._budget.resolver_has_high_confidence and tool_name not in {
            "local_open", "local_app_resolve"
        }:
            self._check_resolver_has_candidate(tool_name)

    def _check_recursive_search(self, command: str) -> None:
        for pattern in _RECURSIVE_SEARCH_PATTERNS:
            if pattern.search(command):
                raise RuntimeError(
                    _BLOCK_RECURSIVE_MSG.format(
                        pattern=pattern.pattern,
                        intent=self._route.intent.value,
                    )
                )

    def _check_forbidden_directories(self, command: str) -> None:
        for pattern in _FORBIDDEN_DIR_PATTERNS:
            if pattern.search(command):
                raise RuntimeError(
                    _BLOCK_PROGRAM_FILES_MSG.format(intent=self._route.intent.value)
                )

    def _check_budget_exceeded(self) -> None:
        if self._budget.is_exceeded() or self._budget.is_shell_exceeded():
            raise RuntimeError(
                _BLOCK_BUDGET_MSG.format(
                    total=self._budget.total_call_count,
                    max_total=self._budget.max_tool_calls_per_task,
                    shell=self._budget.shell_call_count,
                    max_shell=self._budget.max_shell_calls_per_task,
                )
            )

    def _check_resolver_has_candidate(self, tool_name: str) -> None:
        raise RuntimeError(_BLOCK_RESOLVER_HAS_CANDIDATE_MSG)

    def _record_trace(self, tc: Any, status: str, result: Any = None) -> None:
        if self._trace_repo is None:
            return
        try:
            tool_name = getattr(tc, "name", "unknown")
            arguments = getattr(tc, "arguments", {})
            summary = ""
            if result is not None:
                summary = str(result)[:500]
            self._trace_repo.record(
                session_id=self._session_id,
                intent=self._route.intent.value,
                tool_name=tool_name,
                arguments=arguments if isinstance(arguments, dict) else {},
                status=status,
                target=self._route.target,
                result_summary=summary,
            )
        except Exception:
            logger.debug("Trace record failed for tool=%s status=%s", getattr(tc, "name", "?"), status)

    def __getattr__(self, name: str):
        async def _noop(*args: Any, **kwargs: Any) -> None:
            pass
        return _noop
