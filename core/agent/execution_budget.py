"""5.4 Execution budget — per-intent tool-call limits and constraints."""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.agent.execution_intent import ExecutionIntent


class ExecutionBudgetLimit(BaseModel):
    """Limits for a single execution intent."""

    max_tool_calls: int = Field(default=3, ge=1)
    max_resolver_calls: int = Field(default=1, ge=0)
    max_open_calls: int = Field(default=1, ge=0)
    max_shell_calls: int = Field(default=0, ge=0)
    max_result_chars: int = Field(default=1500, ge=100)
    max_recursive_depth: int = Field(default=2, ge=0)


class ExecutionBudget:
    """Manages per-task tool-call budgets based on execution intent.

    Budgets are loaded from Settings and can be overridden per-intent.
    """

    DEFAULT_LOCAL_OPEN: ExecutionBudgetLimit = ExecutionBudgetLimit(
        max_tool_calls=3,
        max_resolver_calls=1,
        max_open_calls=1,
        max_shell_calls=0,
        max_result_chars=1500,
        max_recursive_depth=0,
    )

    DEFAULT_LOCAL_FIND: ExecutionBudgetLimit = ExecutionBudgetLimit(
        max_tool_calls=5,
        max_resolver_calls=0,
        max_open_calls=0,
        max_shell_calls=0,
        max_result_chars=3000,
        max_recursive_depth=2,
    )

    DEFAULT_GENERAL: ExecutionBudgetLimit = ExecutionBudgetLimit(
        max_tool_calls=6,
        max_resolver_calls=0,
        max_open_calls=0,
        max_shell_calls=2,
        max_result_chars=3000,
        max_recursive_depth=0,
    )

    def __init__(
        self,
        max_tool_calls_per_task: int = 6,
        max_local_lookup_calls: int = 2,
        max_shell_calls_per_task: int = 2,
        block_shell_for_local_open: bool = True,
        max_tool_result_chars: int = 3000,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self._max_tool_calls_per_task = max_tool_calls_per_task
        self._max_shell_calls_per_task = max_shell_calls_per_task
        self._block_shell_for_local_open = block_shell_for_local_open
        self._max_tool_result_chars = max_tool_result_chars

        self._local_open_limit = ExecutionBudgetLimit(
            max_tool_calls=3,
            max_resolver_calls=max_local_lookup_calls,
            max_open_calls=1,
            max_shell_calls=0 if block_shell_for_local_open else 1,
            max_result_chars=1500,
            max_recursive_depth=0,
        )
        self._tool_call_counts: dict[str, int] = {}
        self._resolver_call_count: int = 0
        self._shell_call_count: int = 0
        self._total_call_count: int = 0
        self._resolver_has_high_confidence: bool = False

    def record_tool_call(self, tool_name: str) -> None:
        self._tool_call_counts[tool_name] = self._tool_call_counts.get(tool_name, 0) + 1
        self._total_call_count += 1
        if tool_name == "exec":
            self._shell_call_count += 1
        if tool_name == "local_app_resolve":
            self._resolver_call_count += 1

    def record_high_confidence_candidate(self) -> None:
        self._resolver_has_high_confidence = True

    def allocate_for_route(self, route) -> ExecutionBudgetLimit:
        """Return the budget limit appropriate for the current execution route."""
        if route.intent == ExecutionIntent.LOCAL_OPEN_TARGET:
            return self._local_open_limit
        if route.intent == ExecutionIntent.LOCAL_FIND_FILE:
            return self.DEFAULT_LOCAL_FIND
        return self.DEFAULT_GENERAL

    @property
    def block_shell_for_local_open(self) -> bool:
        return self._block_shell_for_local_open

    @property
    def max_tool_calls_per_task(self) -> int:
        return self._max_tool_calls_per_task

    @property
    def max_shell_calls_per_task(self) -> int:
        return self._max_shell_calls_per_task

    @property
    def max_tool_result_chars(self) -> int:
        return self._max_tool_result_chars

    @property
    def total_call_count(self) -> int:
        return self._total_call_count

    @property
    def shell_call_count(self) -> int:
        return self._shell_call_count

    @property
    def resolver_call_count(self) -> int:
        return self._resolver_call_count

    @property
    def resolver_has_high_confidence(self) -> bool:
        return self._resolver_has_high_confidence

    def is_exceeded(self) -> bool:
        return self._total_call_count >= self._max_tool_calls_per_task

    def is_shell_exceeded(self) -> bool:
        return self._shell_call_count >= self._max_shell_calls_per_task

    def is_resolver_exceeded(self) -> bool:
        return self._resolver_call_count >= self._local_open_limit.max_resolver_calls
