"""FG-04/05: scoped listening, explicit boundaries and grounded budgeted invitations."""

import asyncio
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from core.service.companionship import CompanionActivity, CompanionFeedback, CompanionTrigger
from core.service.learning_protocol import LearningPolicy
from core.service.schedule_protocol import NotificationView
from tests.test_projects import (
    Backend,
    project,
    share,
    state,
)


@pytest.fixture
def service(tmp_path):
    from core.config import Settings
    from core.service.application import ApplicationService
    from core.storage.db import Database

    root = tmp_path.resolve()
    settings = Settings(llm_api_key="synthetic", data_dir=root / "data", workspace_path=root)
    db = Database(settings)
    db.init_database(allow_desktop=True)
    value = ApplicationService(settings, db, Backend(), lambda event: None)
    value.chat.get_or_create_session("session-a")
    value.chat.get_or_create_session("session-b")
    return value


class TestConversationIntent:
    def test_listening_is_session_scoped_and_expires(self, service):
        turn = state()
        turn.input_text = "先听我讲"
        service.dialogue.respond(turn)
        assert service.dialogue.state("session-a").mode == "listening"
        assert service.dialogue.state("session-b") is None
        assert "不连续追问" in service.dialogue.context(turn)
        now = time.time()
        service.dialogue.clock = lambda: now + 3601
        assert service.dialogue.state("session-a") is None

    @pytest.mark.parametrize(
        "text", ["他说“先听我讲”", "如果今天不聊工作", "今天不聊工作？", "角色扮演：今天不聊工作"]
    )
    def test_quotation_and_hypothetical_do_not_change_boundaries(self, service, text):
        turn = state()
        turn.input_text = text
        service.dialogue.respond(turn)
        assert not service.dialogue.boundaries()
        assert service.dialogue.state("session-a") is None

    def test_today_boundary_ends_at_explicit_local_midnight_and_does_not_cancel_tasks(
        self, service
    ):
        now = datetime(2026, 10, 19, 23, 59, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        service.dialogue.clock = lambda: now
        turn = state()
        turn.input_text = "今天不聊工作"
        service.dialogue.respond(turn)
        assert service.dialogue.blocked("工作项目")
        assert not service.dialogue.blocked("喝水提醒")
        assert service.dialogue.boundaries()[0].expires_at == now + 60
        assert service.delegation_repo.list() == []
        service.dialogue.clock = lambda: now + 61
        assert not service.dialogue.blocked("工作项目")

    def test_persistent_boundary_can_be_removed(self, service):
        turn = state()
        turn.input_text = "以后别提工作"
        service.dialogue.respond(turn)
        boundary = service.dialogue.boundaries()[0]
        assert boundary.expires_at is None
        with service.knowledge.db.transaction() as conn:
            assert conn.execute(
                "SELECT body FROM dialogue_boundary WHERE id=?", (boundary.id,)
            ).fetchone()

    def test_listening_can_return_to_discussion(self, service):
        turn = state()
        turn.input_text = "我好累"
        service.dialogue.respond(turn)
        assert service.dialogue.state(turn.session_id).mode == "listening"
        turn.input_text = "帮我分析一下"
        service.dialogue.respond(turn)
        assert service.dialogue.state(turn.session_id).mode == "discussing"


def candidate(service):
    p = project(service)
    source = share(
        service,
        project_id=p["id"],
        session_id="",
        category="shared",
        text="我们一起完成了提醒功能的测试。",
    )
    companion = service.companionship
    companion.trigger(CompanionTrigger(event="app_returned"))
    service.dialogue.enqueue()
    with service.knowledge.db.get_connection() as conn:
        row = conn.execute("SELECT id FROM dialogue_invitation").fetchone()
    assert row
    return row[0], source


def answer(source, **changes):
    return json.dumps(
        {
            "source_id": "project:" + source["id"],
            "quote": "一起完成了提醒功能的测试",
            "opening": "我还记得你说",
            "closing": "想接着聊时，我在。",
            **changes,
        },
        ensure_ascii=False,
    )


class TestGroundedInvitations:
    def test_preparation_quotes_exact_source_and_preserves_reason(self, service, monkeypatch):
        identity, source = candidate(service)

        async def model(prompt):
            assert "我们一起完成了提醒功能的测试" in prompt
            return answer(source)

        monkeypatch.setattr(service, "_analyze", model)
        assert asyncio.run(service.dialogue.prepare(identity))["prepared"]
        choice = service.dialogue.choose()
        assert "一起完成了提醒功能的测试" in choice.text
        assert "？" not in choice.text
        service.companionship.topics.shown(choice)
        assert service.dialogue.valid(choice.memory_id)
        assert service.dialogue.choose() is None  # Seven-day topic dedup.
        service.companionship.topics.feedback(choice.topic_id, "never")
        assert not service.dialogue.valid(choice.memory_id)

    @pytest.mark.parametrize("change", [{"quote": "我们昨天去了台北"}, {"source_id": "invented"}])
    def test_invented_fact_or_source_is_rejected(self, service, monkeypatch, change):
        identity, source = candidate(service)

        async def model(prompt):
            return answer(source, **change)

        monkeypatch.setattr(service, "_analyze", model)
        assert "skipped" in asyncio.run(service.dialogue.prepare(identity))
        assert service.dialogue.choose() is None

    def test_source_forgotten_during_generation_cannot_return(self, service, monkeypatch):
        identity, source = candidate(service)

        async def model(prompt):
            service.projects.forget(service.projects.repo.source(source["id"]))
            return answer(source)

        monkeypatch.setattr(service, "_analyze", model)
        assert "skipped" in asyncio.run(service.dialogue.prepare(identity))
        assert service.dialogue.choose() is None

    def test_late_prepared_bubble_is_suppressed_after_typing(self, service, monkeypatch):
        identity, source = candidate(service)

        async def model(prompt):
            return answer(source)

        monkeypatch.setattr(service, "_analyze", model)
        asyncio.run(service.dialogue.prepare(identity))
        companion = service.companionship
        companion.state.pending_at = time.time() - 1
        companion.engage(CompanionActivity(client="quick", typing=True, conversation=True))
        assert companion.poll(focused=False, running=False) is None
        assert companion.state.used == 0

    def test_learning_disabled_does_not_generate_or_wait(self, service):
        service.learning.policy = LearningPolicy(enabled=False)
        p = project(service)
        share(service, project_id=p["id"], session_id="", category="shared")
        service.companionship.trigger(CompanionTrigger(event="app_returned"))
        service.dialogue.enqueue()
        assert not service.dialogue.waiting()
        assert not service.learning.repo.jobs()

    def test_generation_uses_shared_durable_budget(self, service, monkeypatch):
        _identity, source = candidate(service)

        async def run():
            calls = []

            async def model(prompt):
                calls.append(prompt)
                return answer(source)

            monkeypatch.setattr(service, "_analyze", model)
            service.learning.handlers = {
                "companion_topic": service.learning.handlers["companion_topic"]
            }
            service.learning.last_activity = time.time() - 120
            service.learning.policy = LearningPolicy(daily_calls=0)
            await service.learning.tick()
            assert calls == []
            service.learning.policy = LearningPolicy(daily_calls=1)
            await service.learning.tick()
            await service.learning.current
            assert len(calls) == 1 and service.learning.repo.usage(time.time()).calls == 1
            await service.learning.tick()
            assert len(calls) == 1
            assert asyncio.current_task()

        asyncio.run(run())

    def test_ignored_invitation_applies_cooldown(self, service, monkeypatch):
        identity, source = candidate(service)

        async def model(prompt):
            return answer(source)

        monkeypatch.setattr(service, "_analyze", model)
        asyncio.run(service.dialogue.prepare(identity))
        companion = service.companionship
        companion.state.pending_at = time.time() - 1
        notice = companion.poll(focused=False, running=False)
        assert notice and notice.memory_id == "project:" + source["id"]
        companion.feedback(CompanionFeedback(notice_id=notice.notice_id, action="ignored"))
        assert companion.state.cooldown_until > time.time() + 7100
        assert companion.poll(focused=False, running=False) is None

    def test_quiet_boundary_defers_work_notice_without_losing_it(self, service):
        turn = state()
        turn.input_text = "今天不聊工作"
        service.dialogue.respond(turn)
        notice = NotificationView(
            id="n",
            reason="task_result",
            source_id="t",
            text="工作结果完成",
            planned_at=time.time(),
            created_at=time.time(),
        )
        service.scheduler.notifications.put(notice)
        assert service.scheduler.notifications.next(quiet=False) is None
        assert service.scheduler.notifications.list()[0].status == "pending"
