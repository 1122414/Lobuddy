"""Tests for ConversationSummarizer."""

import pytest
from datetime import datetime

from core.memory.conversation_summarizer import ConversationSummarizer
from core.memory.memory_repository import MemoryRepository
from core.models.chat import ChatMessage
from core.storage.db import Database
from core.config import Settings


class TestConversationSummarizer:
    def test_should_summarize_when_enough_turns(self, tmp_path):
        settings = _settings_for_test(tmp_path, memory_summary_trigger_turns=3)
        db = Database(settings)
        repo = MemoryRepository(db)
        summarizer = ConversationSummarizer(settings, repo)

        messages = [
            ChatMessage(id="m1", role="user", content="Hello", session_id="s1", created_at=datetime.now()),
            ChatMessage(id="m2", role="user", content="Hi", session_id="s1", created_at=datetime.now()),
            ChatMessage(id="m3", role="user", content="How are you?", session_id="s1", created_at=datetime.now()),
        ]
        assert summarizer.should_summarize(messages) is True

    def test_should_not_summarize_when_few_turns(self, tmp_path):
        settings = _settings_for_test(tmp_path, memory_summary_trigger_turns=10)
        db = Database(settings)
        repo = MemoryRepository(db)
        summarizer = ConversationSummarizer(settings, repo)

        messages = [
            ChatMessage(id="m1", role="user", content="Hello", session_id="s1", created_at=datetime.now()),
        ]
        assert summarizer.should_summarize(messages) is False

    def test_create_rolling_summary(self, tmp_path):
        settings = _settings_for_test(tmp_path, memory_summary_trigger_turns=2)
        db = Database(settings)
        repo = MemoryRepository(db)
        summarizer = ConversationSummarizer(settings, repo)

        messages = [
            ChatMessage(id="m1", role="user", content="What is Python?", session_id="s1", created_at=datetime.now()),
            ChatMessage(id="m2", role="user", content="Tell me more", session_id="s1", created_at=datetime.now()),
        ]
        summary = summarizer.create_rolling_summary("s1", messages)
        assert summary is not None
        assert summary.session_id == "s1"
        assert summary.summary_type == "rolling"
        assert "Python" in summary.content

    def test_create_session_summary(self, tmp_path):
        settings = _settings_for_test(tmp_path)
        db = Database(settings)
        repo = MemoryRepository(db)
        summarizer = ConversationSummarizer(settings, repo)

        messages = [
            ChatMessage(id="m1", role="user", content="Question", session_id="s1", created_at=datetime.now()),
            ChatMessage(id="m2", role="assistant", content="Answer", session_id="s1", created_at=datetime.now()),
        ]
        summary = summarizer.create_session_summary("s1", messages)
        assert summary is not None
        assert summary.summary_type == "session_end"

    def test_get_latest_summary(self, tmp_path):
        settings = _settings_for_test(tmp_path, memory_summary_trigger_turns=1)
        db = Database(settings)
        repo = MemoryRepository(db)
        summarizer = ConversationSummarizer(settings, repo)

        messages = [
            ChatMessage(id="m1", role="user", content="First", session_id="s1", created_at=datetime.now()),
        ]
        summarizer.create_rolling_summary("s1", messages)

        latest = summarizer.get_latest_summary("s1")
        assert latest is not None
        assert "First" in latest.content

    def test_empty_messages_no_summary(self, tmp_path):
        settings = _settings_for_test(tmp_path)
        db = Database(settings)
        repo = MemoryRepository(db)
        summarizer = ConversationSummarizer(settings, repo)

        summary = summarizer.create_session_summary("s1", [])
        assert summary is None


def _settings_for_test(tmp_path, **kwargs):
    defaults = dict(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        memory_summary_trigger_turns=10,
        memory_summary_max_chars=2000,
    )
    defaults.update(kwargs)
    return Settings(**defaults)
