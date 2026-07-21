"""Exact, content-minimized timing Adapter for nanobot tool calls."""

from __future__ import annotations

import time
import uuid
from typing import Any

from core.events import ToolCallExecuted, ToolCallPlanned


class TaskTimingToolProxy:
    """Preserve the nanobot tool Interface while emitting safe timing evidence."""

    def __init__(self, delegate: Any, event_bus: Any, task_id: str) -> None:
        self._delegate = delegate
        self._event_bus = event_bus
        self._task_id = task_id

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
        call_id = str(uuid.uuid4())
        stage_key = f"tool:{self.name}:{call_id[:8]}"
        self._event_bus.publish(
            ToolCallPlanned(
                task_id=self._task_id,
                tool_name=self.name,
                estimated_risk="low" if self.read_only else "medium",
                call_id=call_id,
                stage_key=stage_key,
            )
        )
        started = time.perf_counter()
        try:
            result = await self._delegate.execute(**kwargs)
        except BaseException:
            self._publish_finished(call_id, stage_key, started, success=False)
            raise
        self._publish_finished(
            call_id,
            stage_key,
            started,
            success=not self._looks_like_error(result),
        )
        return result

    def _publish_finished(
        self,
        call_id: str,
        stage_key: str,
        started: float,
        *,
        success: bool,
    ) -> None:
        self._event_bus.publish(
            ToolCallExecuted(
                task_id=self._task_id,
                tool_name=self.name,
                success=success,
                duration_ms=max(0.0, (time.perf_counter() - started) * 1000),
                call_id=call_id,
                stage_key=stage_key,
            )
        )

    @staticmethod
    def _looks_like_error(result: Any) -> bool:
        if isinstance(result, str):
            return result.lstrip().lower().startswith("error")
        if isinstance(result, dict):
            return bool(result.get("error"))
        return False
