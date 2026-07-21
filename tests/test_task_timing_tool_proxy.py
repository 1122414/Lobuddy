"""Exact, content-minimized tool timing Adapter regressions."""

from __future__ import annotations

import asyncio

from core.agent.tools.task_timing_tool_proxy import TaskTimingToolProxy
from core.events import EventBus, ToolCallExecuted, ToolCallPlanned


class _Tool:
    name = "read_file"
    description = "read"
    parameters = {"type": "object"}
    read_only = True
    concurrency_safe = True
    exclusive = False

    def cast_params(self, params):
        return params

    def validate_params(self, _params):
        return []

    def to_schema(self):
        return {"name": self.name}

    async def execute(self, **kwargs):
        await asyncio.sleep(0.002)
        return f"read {kwargs['path']}"


def test_timing_proxy_preserves_tool_interface_and_emits_exact_safe_evidence() -> None:
    bus = EventBus()
    events = []
    bus.subscribe(ToolCallPlanned, events.append)
    bus.subscribe(ToolCallExecuted, events.append)
    proxy = TaskTimingToolProxy(_Tool(), bus, "task-1")

    result = asyncio.run(proxy.execute(path="C:/private/project/secret.txt"))

    assert result == "read C:/private/project/secret.txt"
    assert proxy.name == "read_file"
    assert proxy.to_schema() == {"name": "read_file"}
    assert len(events) == 2
    planned, executed = events
    assert planned.task_id == executed.task_id == "task-1"
    assert planned.call_id == executed.call_id
    assert planned.stage_key == executed.stage_key
    assert executed.success is True
    assert executed.duration_ms > 0
    assert "private" not in repr(events)
    assert "secret.txt" not in repr(events)


def test_timing_proxy_marks_error_result_without_retaining_raw_result() -> None:
    bus = EventBus()
    executed = []
    bus.subscribe(ToolCallExecuted, executed.append)
    tool = _Tool()

    async def fail(**_kwargs):
        return "Error: password=do-not-store"

    tool.execute = fail
    proxy = TaskTimingToolProxy(tool, bus, "task-2")

    assert asyncio.run(proxy.execute(path="unused")).startswith("Error:")
    assert executed[0].success is False
    assert "do-not-store" not in repr(executed[0])
