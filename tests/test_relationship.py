"""FG-01/03: source admission, corrections, scoped memory and late derivations."""

import json
from pathlib import Path

import pytest

from core.config import Settings
from core.models.chat import ChatMessage
from core.service.knowledge import KnowledgeService
from core.service.protocol import TurnState
from core.service.relationship_protocol import RelationProposal
from core.storage.db import Database


@pytest.fixture
def knowledge(tmp_path: Path) -> KnowledgeService:
    settings = Settings(
        llm_api_key="test",
        _env_file=None,
        data_dir=tmp_path / "data",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
    )
    settings.workspace_path.mkdir()
    db = Database(settings)
    db.init_database(allow_desktop=True)
    return KnowledgeService(settings, db)


def message(
    knowledge: KnowledgeService,
    text: str,
    identity: str = "one",
    role: str = "user",
    session: str = "s",
) -> ChatMessage:
    knowledge.chat.get_or_create_session(session)
    value = ChatMessage(id=identity, session_id=session, role=role, content=text)
    knowledge.chat.save_message(value)
    return value


def proposal(source: ChatMessage, **changes: object) -> RelationProposal:
    return RelationProposal.model_validate(
        {
            "kind": "preference",
            "key": "tea",
            "content": source.content,
            "quote": source.content,
            "source_ids": [source.id],
        }
        | changes
    )


def state(session: str = "s") -> TurnState:
    return TurnState(
        turn_id="t",
        task_id="task",
        session_id=session,
        engine_id="e",
        lane="foreground",
        status="running",
        input_text="喜欢什么茶",
    )


class TestRelationship:
    async def test_explicit_ordinary_tool_memory_does_not_ask_twice(
        self, knowledge: KnowledgeService
    ) -> None:
        from core.agent.dsh.tools import GovernedTools, ToolRequest

        class NoApproval:
            async def request_approval(self, _request):
                raise AssertionError("Ordinary explicit preference must not ask again")

        source = message(knowledge, "请记住，我喜欢白茶。", identity="t")
        turn = state()
        turn.input_text = source.content
        executor = GovernedTools(
            knowledge.settings.workspace_path, NoApproval(), knowledge=knowledge, state=turn
        )
        result = await executor.execute(
            ToolRequest.model_validate(
                {
                    "callId": "once",
                    "name": "lobuddy_memory_propose",
                    "arguments": {
                        "memory_type": "user_profile",
                        "title": "茶",
                        "content": "喜欢白茶",
                        "confidence": 0.95,
                    },
                }
            ),
            session_id="s",
            turn_id="t",
            is_active=lambda: True,
        )
        assert "active" in result and "白茶" in knowledge.context(state())

    @pytest.mark.parametrize(
        "text",
        [
            "如果我喜欢红茶",
            "假如我喜欢红茶",
            "假设我喜欢红茶",
            "他说我喜欢红茶",
            "她说我喜欢红茶",
            "朋友说我喜欢红茶",
            "例如我喜欢红茶",
            "举例我喜欢红茶",
            "角色扮演：我喜欢红茶",
            "“我喜欢红茶”",
            "「我喜欢红茶」",
            "`我喜欢红茶`",
            "我喜欢红茶？",
            "我喜欢红茶吗?",
            "我喜欢红茶，不要记住",
            "我喜欢红茶，别记",
            "今天我很累",
            "现在回复短一点",
            "这次回答短一点",
            "我喜欢 sk-abcdefghijklmnopqrstuvwxyz123456",
        ],
    )
    def test_not_user_fact(self, knowledge: KnowledgeService, text: str) -> None:
        source = message(knowledge, text)
        assert knowledge.relationship.admit(proposal(source), "s") is None
        assert knowledge.relationship.list_relations() == []

    def test_assistant_claim_rejected(self, knowledge: KnowledgeService) -> None:
        source = message(knowledge, "我喜欢红茶", role="assistant")
        assert knowledge.relationship.admit(proposal(source), "s") is None

    def test_exact_quote_not_model_invention(self, knowledge: KnowledgeService) -> None:
        source = message(knowledge, "我喜欢红茶")
        value = knowledge.relationship.admit(proposal(source, content="用户喜欢赛车"), "s")
        assert value.status == "active" and value.content == source.content
        assert "赛车" not in knowledge.context(state())

    def test_missing_source_rejected(self, knowledge: KnowledgeService) -> None:
        source = message(knowledge, "我喜欢红茶")
        assert knowledge.relationship.admit(proposal(source, source_ids=["missing"]), "s") is None

    @pytest.mark.parametrize(
        "text",
        [
            "我喜欢的药是阿司匹林",
            "我喜欢谈论我的工资",
            "我喜欢的住址是楼下",
            "我喜欢的女朋友叫小张",
        ],
    )
    def test_sensitive_needs_confirmation_without_copy(
        self, knowledge: KnowledgeService, text: str
    ) -> None:
        source = message(knowledge, text)
        value = knowledge.relationship.admit(proposal(source), "s")
        assert value.status == "pending" and value.content == ""
        assert text not in knowledge.context(state())
        knowledge.relationship.resolve(value.id, True)
        assert text in knowledge.context(state())

    def test_inference_requires_distinct_evidence_and_confirmation(
        self, knowledge: KnowledgeService
    ) -> None:
        first = message(knowledge, "我今天喝了红茶", "a")
        second = message(knowledge, "我今天喝了红茶", "b")
        third = message(knowledge, "我今天喝了红茶", "c")
        assert (
            knowledge.relationship.admit(
                proposal(first, kind="inferred", source_ids=["a", "a", "a"]), "s"
            )
            is None
        )
        value = knowledge.relationship.admit(
            proposal(first, kind="inferred", source_ids=[first.id, second.id, third.id]), "s"
        )
        assert value.status == "pending"
        assert first.content not in knowledge.context(state())

    def test_correction_forget_and_restart(self, knowledge: KnowledgeService) -> None:
        first = message(knowledge, "我喜欢红茶", "a")
        old = knowledge.relationship.admit(proposal(first), "s")
        latest = message(knowledge, "以后我喜欢白茶", "b")
        new = knowledge.relationship.admit(proposal(latest), "s")
        assert new.status == "active"
        assert knowledge.relationship.get(old.id).status == "superseded"
        assert "红茶" not in knowledge.context(state("another"))
        assert "白茶" in knowledge.context(state("another"))
        knowledge.relationship.forget(new.id)
        restarted = KnowledgeService(knowledge.settings, knowledge.db)
        assert restarted.relationship.admit(proposal(latest), "s") is None
        assert restarted.relationship.admit(proposal(first), "s") is None
        assert "白茶" not in restarted.context(state())
        assert latest.id in {m.id for m in restarted.chat.get_messages("s")}
        assert not restarted.search.search("白茶", current_session_id="s").results

    def test_conflict_kept_pending_and_session_scope(self, knowledge: KnowledgeService) -> None:
        first = message(knowledge, "我喜欢红茶", "a")
        knowledge.relationship.admit(proposal(first), "s")
        second = message(knowledge, "我喜欢咖啡", "b")
        pending = knowledge.relationship.admit(proposal(second), "s")
        assert pending.status == "pending"
        scoped = knowledge.relationship.admit(proposal(second, key="local", scope="session"), "s")
        knowledge.relationship.resolve(scoped.id, True)
        assert "咖啡" in knowledge.context(state())
        assert "咖啡" not in knowledge.context(state("other"))
        assert "咖啡" not in (knowledge.settings.workspace_path / "USER.md").read_text()

    async def test_late_summary_cannot_revive_forgotten_source(
        self, knowledge: KnowledgeService
    ) -> None:
        source = message(knowledge, "我喜欢红茶")
        value = knowledge.relationship.admit(proposal(source), "s")

        async def model(_prompt: str) -> str:
            knowledge.relationship.forget(value.id)
            return json.dumps({"memories": [proposal(source).model_dump()], "summary": []})

        result = await knowledge.relationship.analyze("s", model)
        assert result == {"skipped": "knowledge_changed"}
        assert "红茶" not in knowledge.context(state())

    async def test_semantic_summary_with_evidence_and_no_tools(
        self, knowledge: KnowledgeService
    ) -> None:
        source = message(knowledge, "明天先整理资料，再写总结。")

        async def model(prompt: str) -> str:
            assert source.id in prompt and len(prompt.encode()) <= 7000
            return json.dumps(
                {
                    "memories": [],
                    "summary": [
                        {
                            "kind": "decision",
                            "content": "先整理资料，再总结",
                            "source_ids": [source.id],
                        },
                        {"kind": "goal", "content": "不存在来源的事", "source_ids": ["missing"]},
                    ],
                }
            )

        result = await knowledge.relationship.analyze("s", model)
        assert result["summary_facts"] == 1
        assert "不存在来源" not in knowledge.repo.get_latest_summary("s").content

    def test_disable_and_delete_history(self, knowledge: KnowledgeService) -> None:
        source = message(knowledge, "我喜欢红茶")
        knowledge.relationship.configure(False)
        assert knowledge.relationship.admit(proposal(source), "s") is None
        knowledge.relationship.configure(True)
        value = knowledge.relationship.admit(proposal(source), "s")
        knowledge.relationship.forget(value.id, delete_history=True)
        assert knowledge.chat.get_messages("s") == []
