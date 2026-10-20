"""FG-06/07: real bounded effects, independent evidence and immutable skill history."""

import json
from pathlib import Path

import pytest

from core.agent.dsh.tools import GovernedTools, ToolRequest
from core.config import Settings
from core.safety.hitl_approval import HitlApprovalDecision
from core.service.knowledge import KnowledgeService
from core.service.outcomes import OutcomeRepository
from core.service.protocol import TurnState
from core.skills.skill_schema import SkillRecord, SkillStatus
from core.storage.db import Database


class Approval:
    approved = True
    requests = 0

    async def request_approval(self, value):
        self.requests += 1
        factory = (
            HitlApprovalDecision.approved_now
            if self.approved
            else HitlApprovalDecision.rejected_now
        )
        return factory(value.request_id)


@pytest.fixture
def tools(tmp_path: Path):
    s = Settings(
        llm_api_key="test",
        _env_file=None,
        data_dir=tmp_path / "data",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
    )
    s.workspace_path.mkdir()
    (s.workspace_path / "input").mkdir()
    (s.workspace_path / "input" / "a.txt").write_text(
        "决定使用绿色主题\n待办：更新首页\n简短测试材料"
    )
    db = Database(s)
    db.init_database(allow_desktop=True)
    k = KnowledgeService(s, db)
    state = TurnState(
        turn_id="t",
        task_id="task",
        session_id="s",
        engine_id="e",
        lane="background",
        status="running",
        input_text="整理 input 的分类副本到 output",
    )
    return GovernedTools(s.workspace_path, Approval(), settings=s, knowledge=k, state=state)


async def call(tools, name, arguments, identity="one"):
    return json.loads(
        await tools.execute(
            ToolRequest.model_validate({"callId": identity, "name": name, "arguments": arguments}),
            session_id="s",
            turn_id="t",
            is_active=lambda: True,
        )
    )


async def preview(tools):
    return await call(tools, "lobuddy_organize", {"source": "input", "output": "output"})


class TestPracticalTasks:
    async def test_preview_approval_copy_hash_and_immutable_candidates(self, tools):
        plan = await preview(tools)
        assert not (tools.workspace / "output").exists() and tools.approval.requests == 0
        result = await call(
            tools,
            "lobuddy_organize",
            {"source": "input", "output": "output", "preview_id": plan["preview_id"]},
            "two",
        )
        assert result["verdict"] == "verified"
        assert (tools.workspace / "output/txt/a.txt").read_bytes() == (
            tools.workspace / "input/a.txt"
        ).read_bytes()
        assert tools.approval.requests == 1
        tools.state.status = "completed"
        first = tools.knowledge.learn_outcome(tools.state)
        assert tools.knowledge.learn_outcome(tools.state) == first
        candidate = tools.knowledge.skills.get_candidate(first["candidate_id"])
        assert candidate.evidence["verdict"] == "verified"
        assert "失败反例" in candidate.proposed_content and "结果检查" in candidate.proposed_content
        with pytest.raises(ValueError, match="重放"):
            await call(
                tools,
                "lobuddy_organize",
                {"source": "input", "output": "output", "preview_id": plan["preview_id"]},
                "three",
            )

    @pytest.mark.parametrize("change", ["deny", "collision", "source_changed", "symlink_output"])
    async def test_denial_or_mismatch_never_verifies(self, tools, change):
        plan = await preview(tools)
        if change == "deny":
            tools.approval.approved = False
        elif change == "collision":
            (tools.workspace / "output/txt").mkdir(parents=True)
            (tools.workspace / "output/txt/a.txt").write_text("已有内容")
        elif change == "source_changed":
            (tools.workspace / "input/a.txt").write_text("changed")
        else:
            (tools.workspace / "output").symlink_to(
                tools.workspace / "input", target_is_directory=True
            )
        with pytest.raises((ValueError, RuntimeError, OSError)):
            await call(
                tools,
                "lobuddy_organize",
                {"source": "input", "output": "output", "preview_id": plan["preview_id"]},
                "two",
            )
        assert OutcomeRepository(tools.knowledge.db).get("t").verdict != "verified"
        if change in ("collision", "source_changed", "symlink_output"):
            tools.state.status = "completed"
            result = tools.knowledge.learn_outcome(tools.state)
            candidate = tools.knowledge.skills.get_candidate(result["candidate_id"])
            assert candidate.evidence["verdict"] == "failed"
            assert candidate.source_kind.value == "diagnosed_failure"
        if change == "collision":
            assert (tools.workspace / "output/txt/a.txt").read_text() == "已有内容"
        if change == "deny":
            assert not (tools.workspace / "output").exists()

    @pytest.mark.parametrize("path", ["../input", ".env", "skills", "/etc"])
    async def test_unsafe_source_rejected(self, tools, path):
        with pytest.raises(ValueError):
            await call(tools, "lobuddy_organize", {"source": path, "output": "output"})
        assert tools.approval.requests == 0

    async def test_research_quotes_source_coverage_and_missing(self, tools):
        value = await call(tools, "lobuddy_digest", {"sources": ["input/a.txt"]})
        assert value["outcome"]["verdict"] == "verified"
        assert value["sections"]["decisions"][0]["source"] == "S1"
        assert value["sections"]["todos"][0]["quote"] == "待办：更新首页"
        value = await call(
            tools, "lobuddy_digest", {"sources": ["input/a.txt", "missing.txt"]}, "two"
        )
        assert value["outcome"]["verdict"] == "unknown"
        assert value["outcome"]["evidence"][1]["available"] is False
        assert all(item["source"] == "S1" for items in value["sections"].values() for item in items)

    def test_claimed_success_and_cancelled_never_count(self, tools):
        tools.state.status = "completed"
        tools.state.output_text = "全部做好了"
        assert tools.knowledge.learn_outcome(tools.state) == {"skipped": "no_result_evidence"}
        repo = OutcomeRepository(tools.knowledge.db)
        assert repo.finish_turn("t", "completed").verdict == "unknown"
        assert repo.finish_turn("t", "cancelled").verdict == "unknown"
        assert not tools.knowledge.skills.list_candidates()

    def test_versions_preserve_actual_current_and_disabled_content(self, tools):
        manager = tools.knowledge.skills
        manager.create_skill(
            SkillRecord(
                id="s",
                name="sample",
                path="",
                description="test",
                version=5,
                status=SkillStatus.ACTIVE,
            ),
            "before",
        )
        manager.patch_skill("s", "after")
        assert [v["version"] for v in manager.versions("s")] == [6, 5]
        manager.disable_skill("s")
        manager.patch_skill("s", "inactive")
        assert [v["content"] for v in manager.versions("s")] == ["inactive", "after", "before"]
        assert not (tools.workspace / "skills/sample/SKILL.md").exists()

    async def test_unknown_write_survives_restart(self, tools):
        repo = OutcomeRepository(tools.knowledge.db)
        repo.claim_effect("crash", "t", "{}")
        restarted = OutcomeRepository(tools.knowledge.db)
        with pytest.raises(ValueError, match="重放"):
            restarted.claim_effect("crash", "t", "{}")

    def test_explicit_correction_candidate_has_source_and_is_not_success(self, tools):
        tools.state.status = "completed"
        tools.state.input_text = "下次整理文件时先给我按类型的数量，再让我确认。"
        result = tools.knowledge.learn_outcome(tools.state)
        candidate = tools.knowledge.skills.get_candidate(result["candidate_id"])
        assert candidate.source_kind.value == "correction"
        assert candidate.evidence["verdict"] == "unknown"
        assert tools.state.input_text in candidate.proposed_content
        candidate.proposed_content += "changed"
        with pytest.raises(ValueError, match="修订不可覆盖"):
            tools.knowledge.skills.create_candidate(candidate)
