"""Persistent proactive limits, engagement suppression and correctable shared memory."""

import asyncio
from pathlib import Path

import pytest

from core.config import Settings
from core.service.companionship import (
    CompanionActivity,
    CompanionFeedback,
    CompanionPolicy,
    CompanionPreference,
    Companionship,
    CompanionTrigger,
    proactive_instruction,
)
from core.service.knowledge import KnowledgeService
from core.service.protocol import RpcRequest, TurnState
from core.service.stdio import StdioServer
from core.storage.db import Database


class TestCompanionship:
    def test_presence_polling_does_not_exhaust_transport_request_budget(self) -> None:
        async def exercise() -> None:
            server = StdioServer()
            slots = asyncio.Semaphore(1)

            async def handle(request: RpcRequest) -> None:
                return None

            for index in range(8300):
                await slots.acquire()
                request = RpcRequest(
                    jsonrpc="2.0", id=str(index), method="companion.get", params={}
                )
                await server._receive(request.model_dump_json().encode(), handle, slots)
                assert "error" not in await server._outgoing.get()
            assert not server._requests

        asyncio.run(exercise())

    def test_direct_boundaries_do_not_match_questions_or_quoted_text(self) -> None:
        assert proactive_instruction("以后不要主动找我聊天。") is False
        assert proactive_instruction("现在可以主动找我聊天") is True
        assert proactive_instruction("以后不要主动找我聊天好吗？") is None
        assert proactive_instruction("他说不要主动找我聊天") is None

    def test_quota_ignore_cooldown_restart_and_clock_rollback(self, tmp_path: Path) -> None:
        db = Database(Settings(llm_api_key="test", data_dir=tmp_path))
        db.init_database(allow_desktop=True)
        now = [1792100000.0]
        clock = lambda: now[0]
        service = Companionship(db, clock)
        for index in range(3):
            service.trigger(CompanionTrigger(event="app_returned"))
            assert service.poll(focused=False, running=False) is None
            now[0] += 31
            notice = service.poll(focused=False, running=False)
            assert notice is not None
            assert service.poll(focused=False, running=False).notice_id == notice.notice_id
            assert service.state.used == index + 1
            service.feedback(CompanionFeedback(notice_id=notice.notice_id, action="ignored"))
            service.trigger(CompanionTrigger(event="app_returned"))
            now[0] += 3600
            assert service.poll(focused=False, running=False) is None
            now[0] += 3601
        restarted = Companionship(db, clock)
        assert restarted.state.used == 3
        restarted.trigger(CompanionTrigger(event="app_returned"))
        now[0] += 31
        assert restarted.poll(focused=False, running=False) is None
        now[0] -= 24 * 3600
        assert restarted.poll(focused=False, running=False) is None
        assert restarted.state.used == 3

    @pytest.mark.parametrize("blocked", ["focus", "running", "typing", "conversation", "dnd"])
    def test_suppression_uses_real_activity_not_window_count(
        self, tmp_path: Path, blocked: str
    ) -> None:
        db = Database(Settings(llm_api_key="test", data_dir=tmp_path))
        db.init_database(allow_desktop=True)
        now = [1792100000.0]
        service = Companionship(db, lambda: now[0])
        service.trigger(CompanionTrigger(event="app_returned"))
        now[0] += 31
        if blocked == "dnd":
            service.configure(CompanionPolicy(do_not_disturb=True))
        service.engage(
            CompanionActivity(
                client="quick", typing=blocked == "typing", conversation=blocked == "conversation"
            )
        )
        assert service.poll(focused=blocked == "focus", running=blocked == "running") is None
        assert service.state.used == 0

    def test_expiry_and_restart_do_not_repeat_unanswered_invitation(self, tmp_path: Path) -> None:
        db = Database(Settings(llm_api_key="test", data_dir=tmp_path))
        db.init_database(allow_desktop=True)
        now = [1792100000.0]
        service = Companionship(db, lambda: now[0])
        service.trigger(CompanionTrigger(event="conversation_finished"))
        now[0] += 31
        assert service.poll(focused=False, running=False) is not None
        restarted = Companionship(db, lambda: now[0])
        assert restarted.poll(focused=False, running=False) is None
        assert restarted.state.cooldown_until > now[0] + 7000
        now[0] += 7201
        restarted.trigger(CompanionTrigger(event="conversation_finished"))
        now[0] += 31
        assert restarted.poll(focused=False, running=False) is not None
        now[0] += 21
        assert restarted.poll(focused=False, running=False) is None
        assert restarted.state.cooldown_until == now[0] + 7200

    def test_explicit_correction_delete_and_event_deduplication(self, tmp_path: Path) -> None:
        settings = Settings(
            llm_api_key="test",
            data_dir=tmp_path / "data",
            workspace_path=tmp_path / "workspace",
            memory_enable_migration=False,
        )
        settings.workspace_path.mkdir()
        db = Database(settings)
        db.init_database(allow_desktop=True)
        knowledge = KnowledgeService(settings, db)
        state = TurnState(
            turn_id="turn-a",
            task_id="task-a",
            session_id="session-a",
            engine_id="engine",
            lane="foreground",
            status="running",
            input_text="以后回答简短一点",
        )
        assert "以后回答简短一点" in knowledge.prepare(state)
        knowledge.save_preference(
            CompanionPreference(kind="tone", content="请详细解释"), "manual-correction"
        )
        state.session_id = "session-b"
        context = knowledge.context(state)
        assert "请详细解释" in context and "以后回答简短一点" not in context
        restarted = KnowledgeService(settings, db)
        assert "请详细解释" in restarted.context(state)
        restarted.save_preference(CompanionPreference(kind="tone", content=""), "manual-delete")
        assert "请详细解释" not in restarted.context(state)
        restarted.record_focus("focus-one", 25)
        restarted.record_focus("focus-one", 25)
        memories = restarted.handle(
            RpcRequest(jsonrpc="2.0", id="list", method="memory.list", params={"query": "一起完成"})
        )
        assert isinstance(memories, list) and len(memories) == 1
        assert isinstance(memories[0], dict) and memories[0]["source"] == "app_event"
        restarted.handle(
            RpcRequest(
                jsonrpc="2.0",
                id="delete",
                method="memory.delete",
                params={"memory_id": memories[0]["id"]},
            )
        )
        restarted.record_focus("focus-one", 25)
        assert "一起完成" not in restarted.context(state)

    def test_questions_and_hypotheses_do_not_become_preferences(self, tmp_path: Path) -> None:
        settings = Settings(
            llm_api_key="test",
            data_dir=tmp_path,
            workspace_path=tmp_path / "workspace",
            memory_enable_migration=False,
        )
        settings.workspace_path.mkdir()
        db = Database(settings)
        db.init_database(allow_desktop=True)
        knowledge = KnowledgeService(settings, db)
        for text in (
            "如果以后回答简短一点会怎样",
            "以后回答简短一点好吗？",
            "我今天回了一条很短的消息",
        ):
            state = TurnState(
                turn_id="turn",
                task_id="task",
                session_id="session",
                engine_id="engine",
                lane="foreground",
                status="running",
                input_text=text,
            )
            knowledge.prepare(state)
        result = knowledge.handle(
            RpcRequest(jsonrpc="2.0", id="list", method="memory.list", params={"query": "相处 ·"})
        )
        assert result == []
