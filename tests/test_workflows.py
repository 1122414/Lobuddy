"""FG-08: protected declarations, held-out comparison and rollback without effects."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.config import Settings
from core.service.workflow_engine import execute_workflow
from core.service.workflow_evaluation import context_definition
from core.service.workflow_protocol import WorkflowDefinition
from core.service.workflows import WorkflowService
from core.storage.db import Database


@pytest.fixture
def workflows(tmp_path: Path):
    db = Database(Settings(llm_api_key="test", _env_file=None, data_dir=tmp_path))
    db.init_database(allow_desktop=True)
    return WorkflowService(db)


class TestWorkflows:
    def test_improvement_36_holdout_cases_promotes_then_five_runs(self, workflows):
        before = workflows.active("assistant-context")
        candidate = workflows.propose(
            context_definition("compact"), "减少格式开销", ["synthetic-result"]
        )
        result = workflows.evaluate(candidate.version_id)
        assert result.active and result.status == "probation"
        assert result.evaluation["cases"] == 36
        assert result.evaluation["after"] < result.evaluation["before"]
        assert workflows.get(before.version_id).definition == before.definition
        for i in range(5):
            data = {"records": [{"id": str(i), "text": "原样保留「偏好」"}]}
            assert json.loads(workflows.context(data, f"run-{i}")) == data
            workflows.context(data, f"run-{i}")
        assert workflows.get(candidate.version_id).observed == 5
        assert workflows.get(candidate.version_id).status == "stable"
        workflows.rollback(candidate.version_id)
        assert workflows.active("assistant-context").version_id == before.version_id

    @pytest.mark.parametrize("bad", ["same", "permission", "prompt", "extra_node"])
    def test_no_gain_authority_or_unprovable_semantics_do_not_promote(self, workflows, bad):
        data = context_definition("compact" if bad != "same" else "pretty").model_dump()
        if bad == "permission":
            data["permissions"] = ["lobuddy_read_file"]
        if bad == "prompt":
            data["nodes"][0]["prompt"] = "改变用户边界"
        if bad == "extra_node":
            data["nodes"].insert(1, {"id": "change", "kind": "model", "prompt": "覆写事实"})
        candidate = workflows.propose(WorkflowDefinition.model_validate(data), "test", [])
        result = workflows.evaluate(candidate.version_id)
        assert result.status == "rejected" and not result.active
        assert workflows.active("assistant-context").definition == context_definition()

    @pytest.mark.parametrize(
        "change",
        [
            {"nodes": []},
            {"nodes": [{"id": "x", "kind": "python", "prompt": "print(1)"}]},
            {
                "nodes": [
                    {"id": "a", "kind": "context", "after": ["b"]},
                    {"id": "b", "kind": "output"},
                ]
            },
            {
                "nodes": [
                    {"id": "a", "kind": "tool", "tool": "lobuddy_read_file"},
                    {"id": "b", "kind": "output"},
                ]
            },
            {"nodes": [{"id": "a", "kind": "output", "source": "input.__class__()"}]},
            {"repairs": 3},
            {"eval_answers": "tamper"},
        ],
    )
    def test_invalid_or_unprivileged_graph_rejected(self, change):
        with pytest.raises(ValidationError):
            WorkflowDefinition.model_validate(context_definition().model_dump() | change)

    def test_regression_crash_disable_and_pinning(self, workflows):
        prior = workflows.active("assistant-context")
        workflows.context({"a": "b"}, "pinned")
        c = workflows.propose(context_definition("compact"), "test", [])
        workflows.evaluate(c.version_id)
        assert "\n" in workflows.context({"a": "b"}, "pinned")
        workflows.begin(c.version_id, "crashed")
        restarted = WorkflowService(workflows.db)
        restarted.recover()
        assert restarted.active("assistant-context").version_id == prior.version_id
        assert restarted.get(c.version_id).status == "rolled_back"
        restarted.disable(prior.version_id)
        with pytest.raises(ValueError):
            restarted.active("assistant-context")
        restarted.enable(prior.version_id)
        assert restarted.active("assistant-context").active

    async def test_interpreter_conditions_and_model_retry_limit(self):
        calls = []

        async def model(prompt):
            calls.append(prompt)
            if len(calls) < 3:
                raise ValueError("retry")
            return "ok"

        async def tool(name, args):
            raise AssertionError("No tools expected")

        graph = WorkflowDefinition.model_validate(
            {
                "name": "test",
                "repairs": 2,
                "nodes": [
                    {
                        "id": "condition",
                        "kind": "condition",
                        "source": "input.flag",
                        "operator": "equals",
                        "expected": True,
                    },
                    {"id": "reply", "kind": "model", "when": "condition", "prompt": "test"},
                    {"id": "result", "kind": "output", "source": "reply"},
                ],
            }
        )
        result = await execute_workflow(
            graph, {"flag": True}, active=lambda: True, tool=tool, model=model, verify=lambda: None
        )
        assert result == "ok" and len(calls) == 3
        calls.clear()
        result = await execute_workflow(
            graph, {"flag": False}, active=lambda: True, tool=tool, model=model, verify=lambda: None
        )
        assert result is None and not calls

    async def test_unknown_tool_error_never_retries_and_cancel_stops(self):
        calls = []

        async def tool(name, args):
            calls.append(name)
            raise RuntimeError("unknown effect")

        async def model(prompt):
            raise AssertionError("No model expected")

        graph = WorkflowDefinition.model_validate(
            {
                "name": "test",
                "repairs": 2,
                "permissions": ["lobuddy_organize"],
                "nodes": [
                    {"id": "copy", "kind": "tool", "tool": "lobuddy_organize"},
                    {"id": "result", "kind": "output", "source": "copy"},
                ],
            }
        )
        with pytest.raises(RuntimeError):
            await execute_workflow(
                graph, {}, active=lambda: True, tool=tool, model=model, verify=lambda: None
            )
        assert len(calls) == 1
        with pytest.raises(asyncio.CancelledError):
            await execute_workflow(
                graph, {}, active=lambda: False, tool=tool, model=model, verify=lambda: None
            )
        assert len(calls) == 1

    async def test_generator_sees_no_holdout_answers(self, workflows):
        async def model(prompt):
            assert "hidden-" not in prompt and "cases" not in prompt
            return json.dumps({"format": "compact", "reason": "减少格式字节"})

        result = await workflows.generate("source-task", model)
        assert result.active and result.evidence == ["source-task"]
