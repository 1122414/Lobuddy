"""FG-04/05: grounded topics and durable boundaries without invented events."""

from pathlib import Path

import pytest

from core.config import Settings
from core.memory.memory_schema import MemoryItem, MemoryType
from core.service.companionship import Companionship, CompanionTrigger
from core.storage.db import Database


@pytest.fixture
def companion(tmp_path: Path):
    db = Database(Settings(llm_api_key="test", _env_file=None, data_dir=tmp_path))
    db.init_database(allow_desktop=True)
    now = [1792100000.0]
    return Companionship(db, lambda: now[0]), now


def remember(service, identity="tea", content="我喜欢白茶", title="茶"):
    item = MemoryItem(
        id=identity,
        memory_type=MemoryType.USER_PROFILE,
        title=title,
        content=content,
        source="relationship",
    )
    service.topics.memory.save(item)
    return item


class TestCompanionTopics:
    def test_source_seven_days_and_new_evidence(self, companion):
        service, now = companion
        item = remember(service)
        choice = service.topics.choose()
        assert choice and item.content in choice.text and choice.memory_id == item.id
        service.topics.shown(choice)
        assert service.topics.choose() is None
        now[0] += 6 * 86400
        assert service.topics.choose() is None
        now[0] += 86401
        assert service.topics.choose()
        service.topics.shown(choice)
        remember(service, content="我现在喜欢红茶")
        assert not service.topics.valid(item.id)
        assert "红茶" in service.topics.choose().text

    def test_never_survives_new_evidence_restart_and_can_unblock(self, companion):
        service, now = companion
        remember(service)
        choice = service.topics.choose()
        service.topics.shown(choice)
        service.respond("以后别提白茶")
        remember(service, content="我喜欢白茶和红茶")
        restarted = Companionship(service.topics.db, lambda: now[0])
        assert restarted.topics.choose() is None
        assert restarted.topics.list_topics()[0].blocked
        restarted.topics.feedback(choice.topic_id, "unblock")
        assert restarted.topics.choose()

    @pytest.mark.parametrize(
        "text", ["他说以后别提白茶", "以后别提白茶好吗？", "如果以后别提白茶", "「以后别提白茶」"]
    )
    def test_quoted_boundary_does_not_apply(self, companion, text):
        service, _ = companion
        remember(service)
        service.respond(text)
        assert service.topics.choose()

    def test_later_global_cooldown_and_source_delete(self, companion):
        service, now = companion
        item = remember(service)
        service.trigger(CompanionTrigger(event="app_returned"))
        now[0] += 31
        notice = service.poll(focused=False, running=False)
        assert notice and notice.memory_id == item.id
        service.topics.memory.delete(item.id)
        assert service.poll(focused=False, running=False) is None
        assert service.topics.list_topics()[0].label == "来源记忆已删除"
        service.respond("暂时不聊")
        assert service.state.cooldown_until == now[0] + 7200

    @pytest.mark.parametrize(
        "content",
        ["我喜欢我的住址上海市某路123号", "我喜欢 sk-abc12345678901234567890", "如果我喜欢红茶"],
    )
    def test_sensitive_and_hypothetical_not_topics(self, companion, content):
        service, _ = companion
        remember(service, content=content)
        assert service.topics.choose() is None

    def test_overview_does_not_equate_exp_with_verified_skill(self, companion):
        service, _ = companion
        result = service.topics.overview()
        assert result.verified_skills == []
        assert "文字交流" in result.available
        assert result.experiences == []
