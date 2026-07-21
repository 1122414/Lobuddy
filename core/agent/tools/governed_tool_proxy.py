"""Fail-closed execution proxy for nanobot tools.

Nanobot's extra-hook chain logs and swallows hook exceptions. Security decisions
therefore cannot rely on an exception from ``before_execute_tools`` alone. This
proxy re-checks the decision inside the actual tool ``execute`` boundary.
"""

from __future__ import annotations

from typing import Any


class GovernedToolProxy:
    """Delegate schema and execution only after Lobuddy's gate allows the call."""

    def __init__(self, delegate: Any, tracker: Any, execution_hook: Any = None) -> None:
        self._delegate = delegate
        self._tracker = tracker
        self._execution_hook = execution_hook

    @property
    def name(self) -> str:
        return self._delegate.name

    @property
    def description(self) -> str:
        return self._delegate.description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._delegate.parameters

    @property
    def read_only(self) -> bool:
        return self._delegate.read_only

    @property
    def concurrency_safe(self) -> bool:
        return getattr(self._delegate, "concurrency_safe", False)

    @property
    def exclusive(self) -> bool:
        return getattr(self._delegate, "exclusive", False)

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._delegate.cast_params(params)

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        return self._delegate.validate_params(params)

    def to_schema(self) -> dict[str, Any]:
        return self._delegate.to_schema()

    async def execute(self, **kwargs: Any) -> Any:
        if self._execution_hook is not None:
            error = self._execution_hook.validate_tool_call(self.name, kwargs)
            if error:
                return f"Error: {error}"
        error = self._tracker.consume_execution_permission(self.name, kwargs)
        if error:
            return f"Error: {error}"
        return await self._delegate.execute(**kwargs)
