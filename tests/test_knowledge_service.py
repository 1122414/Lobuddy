"""Knowledge migration, correction, lifecycle and governed DSH regression checks."""

from pathlib import Path

import pytest

from core.agent.dsh.tools import GovernedTools, ToolRequest
from core.config import Settings
from core.memory.memory_schema import ConversationSummary, MemoryItem, MemoryType
from core.safety.hitl_approval import HitlApprovalDecision, HitlApprovalRequest
from core.service.knowledge import KnowledgeService
from core.service.protocol import RpcRequest, TurnState
from core.skills.skill_schema import SkillRecord, SkillStatus
from core.storage.db import Database


@pytest.fixture
def knowledge(tmp_path: Path) -> KnowledgeService:
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
        memory_summary_trigger_turns=2,
    )
    settings.workspace_path.mkdir()
    db = Database(settings)
    db.init_database()
    return KnowledgeService(settings, db)


def state(session: str = "session-one") -> TurnState:
    return TurnState(
        turn_id="turn-one",
        task_id="task-one",
        session_id=session,
        engine_id="engine-one",
        lane="foreground",
        status="running",
        input_text="你好",
    )


def request(method: str, **params: object) -> RpcRequest:
    return RpcRequest.model_validate(
        {"jsonrpc": "2.0", "id": "request-" + method, "method": method, "params": params}
    )


class TestMemoryLifecycle:
    def test_existing_id_source_correction_and_delete(self, knowledge: KnowledgeService) -> None:
        legacy = MemoryItem(
            id="legacy-id",
            memory_type=MemoryType.USER_PROFILE,
            title="茶",
            content="我喜欢茉莉花茶",
            source="migration",
            source_session_id="old-session",
            source_message_id="old-message",
        )
        knowledge.memory.save_memory(legacy)
        assert "茉莉花茶" in knowledge.context(state())
        saved = knowledge.handle(
            request(
                "memory.save",
                memory_id=legacy.id,
                memory_type="user_profile",
                title="茶",
                content="我喜欢白桃乌龙茶",
            )
        )
        assert isinstance(saved, dict)
        assert saved["id"] == legacy.id and saved["source_message_id"] == "old-message"
        assert saved["source"] == "manual"
        assert "白桃乌龙茶" in knowledge.context(state("another-session"))
        assert "茉莉花茶" not in knowledge.context(state())
        assert "白桃乌龙茶" in (knowledge.settings.workspace_path / "USER.md").read_text()
        knowledge.handle(request("memory.delete", memory_id=legacy.id))
        assert "白桃乌龙茶" not in knowledge.context(state())
        for path in (
            knowledge.settings.workspace_path / "USER.md",
            knowledge.settings.data_dir / "memory/USER.md",
        ):
            assert "白桃乌龙茶" not in path.read_text()
        restarted = KnowledgeService(knowledge.settings, knowledge.db)
        assert restarted.memory.get_memory(legacy.id) is None

    @pytest.mark.parametrize(
        "kind,paths",
        [
            (MemoryType.PROJECT_MEMORY, ("data/memory/PROJECT.md", "workspace/memory/MEMORY.md")),
            (MemoryType.SYSTEM_PROFILE, ("data/memory/SYSTEM.md", "workspace/SOUL.md")),
        ],
    )
    def test_last_projection_removed(
        self, knowledge: KnowledgeService, kind: MemoryType, paths: tuple[str, str]
    ) -> None:
        item = MemoryItem(id="last", memory_type=kind, content="obsolete-token")
        knowledge.gateway.save_manual(item)
        knowledge.gateway.delete_manual(item.id)
        for path in paths:
            assert "obsolete-token" not in (knowledge.settings.data_dir.parent / path).read_text()

    def test_correction_invalidates_summary_without_destroying_history(
        self, knowledge: KnowledgeService
    ) -> None:
        summary = ConversationSummary(
            id="old-summary", session_id="session-one", content="outdated-name"
        )
        knowledge.gateway.save_summary(summary)
        assert "outdated-name" in knowledge.context(state())
        knowledge.handle(
            request("memory.save", memory_type="user_profile", title="身份", content="new-name")
        )
        assert "outdated-name" not in knowledge.context(state())
        assert knowledge.repo.get_latest_summary("session-one").id == "old-summary"  # type: ignore[union-attr]

    def test_secret_redaction_and_source_links(self, knowledge: KnowledgeService) -> None:
        secret = "sk-" + "a" * 24
        saved = knowledge.handle(
            request("memory.save", memory_type="user_profile", title=secret, content=secret)
        )
        assert secret not in str(saved)
        assert secret not in knowledge.context(state())

    def test_identity_uses_current_message_source(self, knowledge: KnowledgeService) -> None:
        turn = state().model_copy(update={"input_text": "请叫我小满。"})
        from core.models.chat import ChatMessage

        knowledge.chat.get_or_create_session(turn.session_id)
        knowledge.chat.save_message(
            ChatMessage(
                id=turn.turn_id, session_id=turn.session_id, role="user", content=turn.input_text
            )
        )
        knowledge.relationship.immediate(turn.session_id, turn.turn_id, turn.input_text)
        assert "小满" in knowledge.prepare(turn)
        items = knowledge.memory.list_memories(MemoryType.USER_PROFILE)
        assert any(item.source_message_id == turn.turn_id for item in items)


class TestSkillLifecycle:
    def test_disabled_content_survives_patch_restart_enable(
        self, knowledge: KnowledgeService
    ) -> None:
        manager = knowledge.skills
        manager.create_skill(
            SkillRecord(
                id="old-skill",
                name="tea-helper",
                path="",
                description="泡茶",
                status=SkillStatus.ACTIVE,
            ),
            "jasmine-procedure",
        )
        tea_turn = state()
        tea_turn.input_text = "帮我泡茶"
        assert "tea-helper" in knowledge.context(tea_turn)
        assert "jasmine-procedure" == manager.get_content("old-skill")
        assert "jasmine-procedure" not in knowledge.context(tea_turn)
        assert manager.cleanup_orphan_workspace_files() == 0
        manager.disable_skill("old-skill")
        assert "tea-helper" not in knowledge.context(tea_turn)
        manager.patch_skill("old-skill", "new-oolong-procedure")
        assert not (knowledge.settings.workspace_path / "skills/tea-helper/SKILL.md").exists()
        restarted = KnowledgeService(knowledge.settings, knowledge.db)
        assert restarted.skills.enable_skill("old-skill")
        assert "tea-helper" in restarted.context(tea_turn)
        assert "new-oolong-procedure" == restarted.skills.get_content("old-skill")
        assert restarted.skills.get_skill("old-skill").version == 2  # type: ignore[union-attr]
        with knowledge.db.get_connection() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM skill_event WHERE skill_id='old-skill'"
                ).fetchone()[0]
                == 4
            )

    def test_legacy_file_backfill_and_missing_content(self, knowledge: KnowledgeService) -> None:
        manager = knowledge.skills
        record = manager.create_skill(
            SkillRecord(id="legacy", name="legacy", path="", description="old"), "legacy-body"
        )
        with knowledge.db.transaction() as conn:
            conn.execute("UPDATE skill_record SET content='' WHERE id='legacy'")
        assert manager.get_content("legacy") == "legacy-body"
        manager.disable_skill("legacy")
        assert manager.get_content("legacy") == "legacy-body"
        with knowledge.db.transaction() as conn:
            conn.execute("UPDATE skill_record SET content='' WHERE id='legacy'")
        with pytest.raises(ValueError, match="旧技能内容缺失"):
            manager.enable_skill("legacy")
        assert not Path(record.path).exists()

    def test_legacy_path_alias_targets_same_managed_file(
        self, knowledge: KnowledgeService, tmp_path: Path
    ) -> None:
        record = knowledge.skills.create_skill(
            SkillRecord(id="aliased", name="aliased", path="", description="same directory"),
            "kept content",
        )
        alias = tmp_path / "workspace-alias"
        alias.symlink_to(knowledge.settings.workspace_path, target_is_directory=True)
        with knowledge.db.transaction() as conn:
            conn.execute(
                "UPDATE skill_record SET path=? WHERE id=?",
                (str(alias / "skills/aliased/SKILL.md"), record.id),
            )
        assert knowledge.skills.disable_skill(record.id)
        assert knowledge.skills.enable_skill(record.id)
        assert Path(record.path).read_text() == "kept content"

    def test_duplicate_name_does_not_overwrite_and_paths_rejected(
        self, knowledge: KnowledgeService, tmp_path: Path
    ) -> None:
        manager = knowledge.skills
        old = manager.create_skill(
            SkillRecord(id="a", name="existing", path="", description="x"), "original"
        )
        with pytest.raises(ValueError, match="已存在"):
            manager.create_skill(
                SkillRecord(id="b", name="existing", path="", description="x"), "overwrite"
            )
        assert Path(old.path).read_text() == "original"
        with pytest.raises(ValueError):
            manager.create_skill(
                SkillRecord(id="c", name="../outside", path="", description="x"), "unsafe"
            )
        (knowledge.settings.workspace_path / "skills/linked").symlink_to(
            tmp_path, target_is_directory=True
        )
        with pytest.raises(ValueError):
            manager.create_skill(
                SkillRecord(id="d", name="linked", path="", description="x"), "unsafe"
            )


class Decision:
    def __init__(self, approved: bool) -> None:
        self.approved = approved

    async def request_approval(self, value: HitlApprovalRequest) -> HitlApprovalDecision:
        return (
            HitlApprovalDecision.approved_now(value.request_id)
            if self.approved
            else HitlApprovalDecision.rejected_now(value.request_id, "拒绝")
        )


class TestKnowledgeTools:
    @pytest.mark.asyncio
    async def test_memory_approval_denial_cancel_and_provenance(
        self, knowledge: KnowledgeService
    ) -> None:
        tool = ToolRequest.model_validate(
            {
                "callId": "one",
                "name": "lobuddy_memory_propose",
                "arguments": {
                    "memory_type": "user_profile",
                    "title": "茶",
                    "content": "喜欢白桃茶",
                    "confidence": 0.95,
                },
            }
        )
        for approved, alive in ((False, True), (True, False)):

            def is_active(current: bool = alive) -> bool:
                return current

            executor = GovernedTools(
                knowledge.settings.workspace_path,
                Decision(approved),
                knowledge=knowledge,
                state=state(),
            )
            with pytest.raises(RuntimeError):
                await executor.execute(
                    tool,
                    session_id="session-one",
                    turn_id="turn-one",
                    is_active=is_active,
                )
        assert not knowledge.memory.search_memories("白桃茶")
        executor = GovernedTools(
            knowledge.settings.workspace_path, Decision(True), knowledge=knowledge, state=state()
        )
        await executor.execute(
            tool, session_id="session-one", turn_id="turn-one", is_active=lambda: True
        )
        assert knowledge.memory.search_memories("白桃茶")[0].source_message_id == "turn-one"
        with pytest.raises(RuntimeError):
            await executor.execute(
                tool, session_id="session-one", turn_id="turn-one", is_active=lambda: True
            )

    @pytest.mark.asyncio
    async def test_managed_files_cannot_bypass_gateway(self, knowledge: KnowledgeService) -> None:
        executor = GovernedTools(knowledge.settings.workspace_path, Decision(True))
        for index, path in enumerate(
            (
                "USER.md",
                "user.md",
                "skills/test/SKILL.md",
                "SKILLS/test/SKILL.md",
                "memory/MEMORY.md",
            )
        ):
            tool = ToolRequest.model_validate(
                {
                    "callId": str(index),
                    "name": "lobuddy_write_file",
                    "arguments": {"path": path, "content": "bypass"},
                }
            )
            with pytest.raises(ValueError, match="Managed knowledge"):
                await executor.execute(tool, session_id="s", turn_id="t", is_active=lambda: True)
