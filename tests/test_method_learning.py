"""FG-07/08: real task traces, fixed task-level comparison, refusal and rollback."""

import asyncio
import json
import uuid

import pytest

from core.config import Settings
from core.service.application import ApplicationService
from core.service.digest_evaluation import digest_definition, evaluate_digest
from core.service.method_learning import evidence, generate_method
from core.service.protocol import RpcRequest
from core.storage.db import Database
from tests.test_projects import Backend


@pytest.fixture
def service(tmp_path):
    root = tmp_path.resolve()
    settings = Settings(
        llm_api_key="synthetic", data_dir=root / "data", workspace_path=root / "workspace"
    )
    settings.workspace_path.mkdir()
    (settings.workspace_path / "a.txt").write_text("决定：保留绿色主题。\n待办：核对引用。")
    (settings.workspace_path / "b.txt").write_text("决定：保留独立来源。")
    db = Database(settings)
    db.init_database(allow_desktop=True)
    return ApplicationService(settings, db, Backend(), lambda event: None)


async def task(service, sources):
    session = service.chat.get_or_create_session(uuid.uuid4().hex)
    result = await service.handle(
        RpcRequest(
            jsonrpc="2.0",
            id=uuid.uuid4().hex,
            method="turn.send",
            params={
                "session_id": session.id,
                "text": "归纳明确提供的资料",
                "workflow_id": "source-digest",
                "workflow_input": {"sources": sources},
                "lane": "background",
            },
        )
    )
    async with asyncio.timeout(5):
        while service.repo.get(result["turn_id"]).status in ("queued", "running"):
            await asyncio.sleep(0.01)
    return service.repo.get(result["turn_id"])


class TestMethodEvidence:
    def test_fixed_task_suite_reduces_reads_without_losing_sources(self):
        result = evaluate_digest(digest_definition(), digest_definition(True))
        assert result["decision"] == "promote" and result["cases"] == 40
        assert result["after"] < result["before"]
        assert result["source_coverage_preserved"] and result["hard_regressions"] == 0
        assert result["model_calls"] == 0

    def test_identical_candidate_has_no_improvement(self):
        result = evaluate_digest(digest_definition(), digest_definition())
        assert result["decision"] == "rejected" and result["before"] == result["after"]

    def test_semantic_or_tool_contract_mutation_is_rejected(self):
        candidate = digest_definition(True)
        candidate.nodes[0].arguments["sources"] = ["a.txt"]
        assert evaluate_digest(digest_definition(), candidate)["decision"] == "rejected"

    def test_actual_workflow_trace_drives_model_proposal_and_rollback(self, service):
        async def run():
            try:
                baseline = await task(service, ["a.txt", "./a.txt", "b.txt"])
                assert baseline.status == "completed"
                original = service.ledger.outcomes.get(baseline.turn_id)
                assert original.metrics["physical_reads"] == 3
                trace = evidence(service.knowledge.workflows, [baseline.turn_id])
                assert trace["duplicate_reference_groups"] == [["S1", "S2"]]
                seen = []

                async def model(prompt):
                    seen.append(prompt)
                    assert baseline.turn_id in prompt and '"physical_reads": 3.0' in prompt
                    assert "a.txt" not in prompt and "绿色主题" not in prompt
                    return json.dumps(
                        {
                            "strategy": "reuse-unchanged-local",
                            "evidence_refs": ["S1", "S2"],
                            "reason": "两个引用读取同一未变化来源，可保留各引用并只读取一次",
                        }
                    )

                candidate = await generate_method(
                    service.knowledge.workflows, baseline.turn_id, model, lambda: True
                )
                assert seen and candidate.active and candidate.status == "probation"
                assert candidate.evaluation["metric"] == "physical_source_reads"
                newer = await task(service, ["a.txt", "./a.txt", "b.txt"])
                result = service.ledger.outcomes.get(newer.turn_id)
                assert result.verdict == "verified" and result.metrics["physical_reads"] == 2
                assert result.metrics["cache_hits"] == 1 and {
                    item.get("ref") for item in result.evidence if "ref" in item
                } == {"S1", "S2", "S3"}
                assert service.knowledge.workflows.get(candidate.version_id).observed == 1
                service.knowledge.workflows.rollback(candidate.version_id)
                stable = service.knowledge.workflows.active("source-digest")
                assert stable.version_id == candidate.parent_id
                reverted = await task(service, ["a.txt", "./a.txt", "b.txt"])
                assert service.ledger.outcomes.get(reverted.turn_id).metrics["physical_reads"] == 3
            finally:
                await service.close()

        asyncio.run(run())

    @pytest.mark.parametrize(
        "mode", ["unique", "missing", "forgotten", "unrelated_refs", "epoch_changed"]
    )
    def test_insufficient_or_stale_evidence_does_not_promote(self, service, mode):
        async def run():
            try:
                source = await task(
                    service,
                    (
                        ["a.txt", "b.txt"]
                        if mode == "unique"
                        else ["missing.txt"] if mode == "missing" else ["a.txt", "./a.txt", "b.txt"]
                    ),
                )
                if mode == "forgotten":
                    service.knowledge.relationship.block_source(source.turn_id)

                async def model(prompt):
                    return json.dumps(
                        {
                            "strategy": "reuse-unchanged-local",
                            "evidence_refs": (
                                ["S1", "S3"] if mode == "unrelated_refs" else ["S1", "S2"]
                            ),
                            "reason": "测试引用",
                        }
                    )

                if mode == "unrelated_refs":
                    with pytest.raises(ValueError, match="真实"):
                        await generate_method(
                            service.knowledge.workflows, source.turn_id, model, lambda: True
                        )
                else:
                    assert (
                        await generate_method(
                            service.knowledge.workflows,
                            source.turn_id,
                            model,
                            lambda: mode != "epoch_changed",
                        )
                        is None
                    )
                assert (
                    service.knowledge.workflows.active("source-digest").version_id
                    == "builtin-source-digest-1"
                )
            finally:
                await service.close()

        asyncio.run(run())

    def test_manual_json_without_real_trace_cannot_bypass_evidence(self, service):
        candidate = service.knowledge.workflows.propose(
            digest_definition(True), "看起来更好", ["user_proposal"]
        )
        result = service.knowledge.workflows.evaluate(candidate.version_id)
        assert result.status == "rejected" and not result.active

    def test_authorization_changed_during_evaluation_rejects(self, service):
        async def run():
            try:
                source = await task(service, ["a.txt", "./a.txt"])
                candidate = service.knowledge.workflows.propose(
                    digest_definition(True), "有证据候选", [source.turn_id]
                )
                result = await asyncio.to_thread(
                    service.knowledge.workflows.evaluate, candidate.version_id, lambda: False
                )
                assert result.status == "rejected" and not result.active
            finally:
                await service.close()

        asyncio.run(run())

    def test_link_sources_are_never_reused(self, service, monkeypatch):
        from core.agent.dsh.practical import PracticalTools

        calls = []

        def fetch(url, guardrails, limit, cancelled):
            calls.append(url)
            return "决定：每次读取链接。"

        monkeypatch.setattr("core.agent.dsh.practical.fetch_page", fetch)

        async def run():
            try:
                # Exercise the component directly through the governed workflow schema.
                from core.agent.dsh.practical import DigestArguments
                from core.agent.dsh.tools import GovernedTools
                from core.safety.hitl_approval import DenyAllHitlApprovalProvider
                from core.service.protocol import TurnState

                state = TurnState(
                    turn_id="links",
                    task_id="links",
                    session_id="links",
                    engine_id="none",
                    lane="background",
                    status="running",
                    input_text="links",
                )
                tools = GovernedTools(
                    service.settings.workspace_path,
                    DenyAllHitlApprovalProvider(),
                    knowledge=service.knowledge,
                    state=state,
                    settings=service.settings,
                )
                result = await PracticalTools(tools).digest(
                    DigestArguments(
                        sources=["https://example.com/a", "https://example.com/a"],
                        reuse_local_sources=True,
                    ),
                    lambda: True,
                )
                assert len(calls) == 2
                assert json.loads(result)["outcome"]["verdict"] == "verified"
            finally:
                await service.close()

        asyncio.run(run())
