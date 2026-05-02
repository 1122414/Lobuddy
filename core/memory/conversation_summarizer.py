"""Conversation summarizer for rolling and session-end summaries."""

import logging
import uuid
from datetime import datetime
from typing import Optional

from core.config import Settings
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import ConversationSummary
from core.models.chat import ChatMessage

logger = logging.getLogger(__name__)


class ConversationSummarizer:
    """Generates conversation summaries from chat messages."""

    def __init__(self, settings: Settings, repo: Optional[MemoryRepository] = None) -> None:
        self._settings = settings
        self._repo = repo or MemoryRepository()

    def should_summarize(self, messages: list[ChatMessage]) -> bool:
        user_messages = [m for m in messages if m.role == "user"]
        return len(user_messages) >= self._settings.memory_summary_trigger_turns

    def create_rolling_summary(
        self,
        session_id: str,
        messages: list[ChatMessage],
    ) -> Optional[ConversationSummary]:
        if not self.should_summarize(messages):
            return None
        content = self._summarize_messages(messages)
        summary = ConversationSummary(
            id=str(uuid.uuid4()),
            session_id=session_id,
            summary_type="rolling",
            content=content,
            from_message_id=messages[0].id if messages else None,
            to_message_id=messages[-1].id if messages else None,
            token_estimate=len(content),
        )
        self._repo.save_summary(summary)
        logger.info("Created rolling summary for session %s", session_id)
        return summary

    def create_session_summary(
        self,
        session_id: str,
        messages: list[ChatMessage],
    ) -> Optional[ConversationSummary]:
        if not messages:
            return None
        content = self._summarize_messages(messages)
        summary = ConversationSummary(
            id=str(uuid.uuid4()),
            session_id=session_id,
            summary_type="session_end",
            content=content,
            from_message_id=messages[0].id,
            to_message_id=messages[-1].id,
            token_estimate=len(content),
        )
        self._repo.save_summary(summary)
        logger.info("Created session summary for session %s", session_id)
        return summary

    def get_latest_summary(self, session_id: str) -> Optional[ConversationSummary]:
        return self._repo.get_latest_summary(session_id)

    def _summarize_messages(self, messages: list[ChatMessage]) -> str:
        lines: list[str] = []
        for msg in messages[-self._settings.memory_summary_trigger_turns * 2 :]:
            role = msg.role
            text = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            lines.append(f"{role}: {text}")
        return "\n".join(lines)
