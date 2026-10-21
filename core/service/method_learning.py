"""Task evidence constrains method proposals; model suggestions never authorize promotion."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from core.service.digest_evaluation import digest_definition
from core.service.outcomes import OutcomeRepository

if TYPE_CHECKING:
    from core.service.workflow_protocol import WorkflowView
    from core.service.workflows import WorkflowService


class DigestMethodProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    strategy: Literal["read-each-source", "reuse-unchanged-local"]
    evidence_refs: list[str] = Field(min_length=2, max_length=6)
    reason: str = Field(min_length=1, max_length=500)


def evidence(workflows: WorkflowService, identities: list[str]) -> dict[str, JsonValue] | None:
    if len(identities) != 1:
        return None
    outcome = OutcomeRepository(workflows.db).get(identities[0])
    if outcome.verdict != "verified" or outcome.scenario != "digest" or not outcome.metrics:
        return None
    with workflows.db.get_connection() as conn:
        if conn.execute(
            "SELECT 1 FROM relationship_barrier WHERE source_id=?", (identities[0],)
        ).fetchone():
            return None
        state = conn.execute(
            "SELECT state_json FROM service_turn WHERE turn_id=?", (identities[0],)
        ).fetchone()
    if not state or json.loads(state[0])["status"] != "completed":
        return None
    groups: dict[str, list[str]] = {}
    for item in outcome.evidence:
        canonical, ref = item.get("canonical_source"), item.get("ref")
        if (
            isinstance(canonical, str)
            and isinstance(ref, str)
            and not canonical.startswith(("http://", "https://"))
        ):
            groups.setdefault(canonical, []).append(ref)
    duplicates = [refs for refs in groups.values() if len(refs) > 1]
    if not duplicates or outcome.metrics.get("physical_reads", 0) <= len(groups):
        return None
    return {
        "turn_id": outcome.turn_id,
        "verified": True,
        "duplicate_reference_groups": [[ref for ref in group] for group in duplicates],
        "physical_reads": outcome.metrics["physical_reads"],
        "source_count": outcome.metrics["source_count"],
        "trace_sha256": hashlib.sha256(outcome.model_dump_json().encode()).hexdigest(),
    }


async def generate_method(
    workflows: WorkflowService,
    source_id: str,
    model: Callable[[str], Awaitable[str]],
    current: Callable[[], bool],
) -> WorkflowView | None:
    trace = evidence(workflows, [source_id])
    if not trace:
        return None
    stable = workflows.active("source-digest")
    if stable.definition == digest_definition(True):
        return None
    prompt = (
        "根据实际执行证据提出资料归纳方法候选。只返回 JSON：strategy 只能是 read-each-source 或 reuse-unchanged-local；evidence_refs 必须引用同一重复读取组的至少两个真实来源编号；reason 说明为何这份证据支持该变化。只允许在同一次任务中复用未变更本地来源，不缓存链接、不删来源、不改摘要含义或权限。\n实际证据（文件路径和正文已移除）："
        + json.dumps(trace, ensure_ascii=False)
    )
    proposal = DigestMethodProposal.model_validate_json(await model(prompt))
    if not current() or trace != evidence(workflows, [source_id]):
        return None
    groups = trace["duplicate_reference_groups"]
    assert isinstance(groups, list)
    if len(set(proposal.evidence_refs)) < 2 or not any(
        isinstance(group, list) and set(proposal.evidence_refs).issubset(group) for group in groups
    ):
        raise ValueError("候选未引用真实的重复读取证据")
    definition = digest_definition(proposal.strategy == "reuse-unchanged-local")
    reason = (
        "依据 "
        + source_id
        + " 的 "
        + "、".join(proposal.evidence_refs)
        + " 重复读取记录；"
        + proposal.reason
    )
    candidate = workflows.propose(definition, reason, [source_id])
    return await asyncio.to_thread(workflows.evaluate, candidate.version_id, current)
