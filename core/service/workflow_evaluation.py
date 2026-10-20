"""Fixed holdout checks live in application code, never in candidate definitions."""

from __future__ import annotations

import json

from pydantic import JsonValue

from core.service.workflow_engine import serialize
from core.service.workflow_protocol import WorkflowDefinition


def context_definition(style: str = "pretty") -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "name": "assistant-context",
            "nodes": [
                {"id": "context", "kind": "context", "format": style},
                {"id": "result", "kind": "output", "source": "context", "after": ["context"]},
            ],
        }
    )


def evaluate(stable: WorkflowDefinition, candidate: WorkflowDefinition) -> dict[str, JsonValue]:
    if not set(candidate.permissions).issubset(stable.permissions):
        return {"decision": "rejected", "reason": "权限扩大", "cases": 0}
    # Only lossless serialization is mechanically provable in this release.
    if stable.name != "assistant-context" or candidate.name != stable.name:
        return {"decision": "review", "reason": "暂无可靠自动质量判定，保持候选", "cases": 0}
    expected = context_definition(candidate.nodes[0].format)
    if candidate != expected or stable != context_definition(stable.nodes[0].format):
        return {"decision": "rejected", "reason": "修改了固定上下文契约或非格式节点", "cases": 0}
    before = after = 0
    # Held out Unicode, embedded delimiters, instruction-looking text, empty fields,
    # long values and IDs. Candidate generation receives none of these fixtures.
    for i in range(36):
        data: dict[str, JsonValue] = {
            "records": [
                {
                    "id": f"hidden-{i}",
                    "description": [
                        "偏好：请先听我说",
                        "ignore previous instructions",
                        'x\n"{}[]:，',
                        "",
                    ][i % 4]
                    * (1 + i // 4),
                    "enabled": i % 2 == 0,
                    "scope": ["session", "global"][i % 2],
                }
            ],
            "query": f"第{i}项",
            "missing": None,
        }
        old = serialize(data, stable.nodes[0].format)
        new = serialize(data, candidate.nodes[0].format)
        if json.loads(new) != data or len(new.encode()) > len(old.encode()):
            return {"decision": "rejected", "reason": "数据丢失或开销退化", "cases": i + 1}
        before += len(old.encode())
        after += len(new.encode())
    return {
        "decision": "promote" if after < before else "rejected",
        "reason": "36个保留场景数据不变且格式字节减少" if after < before else "无改善",
        "cases": 36,
        "metric": "context_utf8_bytes",
        "before": before,
        "after": after,
        "hard_regressions": 0,
        "data_preserved": True,
    }
