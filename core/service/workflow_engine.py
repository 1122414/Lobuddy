"""Finite typed interpreter. Model nodes have no tools; effects use injected governance."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from pydantic import JsonValue

from core.service.workflow_protocol import WorkflowDefinition


def lookup(values: dict[str, JsonValue], reference: str) -> JsonValue:
    value: JsonValue = values
    for part in reference.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ValueError("工作流引用不存在")
        value = value[part]
    return value


def serialize(value: JsonValue, style: str) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2 if style == "pretty" else None,
        separators=None if style == "pretty" else (",", ":"),
    )


async def execute_workflow(
    definition: WorkflowDefinition,
    inputs: dict[str, JsonValue],
    *,
    active: Callable[[], bool],
    tool: Callable[[str, dict[str, JsonValue]], Awaitable[str]],
    model: Callable[[str], Awaitable[str]],
    verify: Callable[[], JsonValue],
    timeout: float = 120,
) -> JsonValue:
    # Revalidate even when a caller constructed a model without validation.
    definition = WorkflowDefinition.model_validate_json(definition.model_dump_json())
    values: dict[str, JsonValue] = {"input": inputs}
    async with asyncio.timeout(timeout):
        for node in definition.nodes:
            if not active():
                raise asyncio.CancelledError
            if node.when and lookup(values, node.when) is not True:
                values[node.id] = None
                continue
            value = lookup(values, node.source)
            if node.kind == "context":
                values[node.id] = serialize(value, node.format)
            elif node.kind == "condition":
                values[node.id] = (
                    value is not None if node.operator == "exists" else value == node.expected
                )
            elif node.kind == "model":
                prompt = node.prompt + "\n" + serialize(value, "compact")
                if len(prompt.encode()) > 7000:
                    raise ValueError("工作流模型输入超过上限")
                for attempt in range(definition.repairs + 1):
                    try:
                        values[node.id] = await model(prompt)
                        break
                    except (ValueError, RuntimeError):
                        if attempt == definition.repairs:
                            raise
            elif node.kind == "tool":
                assert node.tool is not None
                args = {
                    key: lookup(values, v[1:]) if isinstance(v, str) and v.startswith("$") else v
                    for key, v in node.arguments.items()
                }
                # Tool failures never retry: they may have already caused side effects.
                result = await tool(node.tool, args)
                try:
                    values[node.id] = json.loads(result)
                except json.JSONDecodeError:
                    values[node.id] = result
            elif node.kind == "verify":
                values[node.id] = verify()
            elif node.kind == "output":
                return value
    raise ValueError("工作流没有结果")
