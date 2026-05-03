"""5.3 Session Search Service — cold recall of chat history.

Provides controlled, sanitized search over local chat history.
Results are bounded per-item and per-call. Secrets are redacted.
Hot memory stays in prompt context; this is for agent-initiated cold recall.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from core.config import Settings
from core.storage.chat_repo import ChatRepository

logger = logging.getLogger(__name__)

# Reuse the same secret patterns as memory_service
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"xoxb-[a-zA-Z0-9-]+"),
    re.compile(r"Bearer\s+[a-zA-Z0-9._-]+"),
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
]


def _sanitize_text(text: str) -> str:
    """Redact secrets from text before exposing to LLM context."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text.strip()


# ---- Models ----


class SessionSearchScope(str, Enum):
    """Search scope for session_search tool."""

    CURRENT_SESSION = "current_session"
    ALL_SESSIONS = "all_sessions"


class SessionSearchResult(BaseModel):
    """A single search result from chat history."""

    session_id: str
    message_id: str
    role: str
    content: str
    created_at: datetime
    score: float = 0.0


class SessionSearchResponse(BaseModel):
    """Response returned by session_search tool."""

    results: list[SessionSearchResult] = Field(default_factory=list)
    query: str = ""
    scope: str = ""
    total_found: int = 0
    total_shown: int = 0
    budget_exhausted: bool = False
    note: str = ""

    def to_markdown(self) -> str:
        """Render as compact markdown for nanobot context."""
        if not self.results:
            return f"*session_search: No results found for '{self.query}'*"

        lines = [
            f"**Session Search Results** (query: '{self.query}', scope: {self.scope})",
            f"Found {self.total_found}, showing {self.total_shown}.",
            "",
        ]
        for i, r in enumerate(self.results, 1):
            ts = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else ""
            lines.append(f"{i}. [{r.role.upper()}] [{ts}] {r.content}")
        if self.budget_exhausted:
            lines.append(f"\n*Note: {self.note}*")
        return "\n".join(lines)


# ---- Service ----


class SessionSearchService:
    """Controlled search over local chat history for cold recall.

    Security: results are sanitized, bounded per-item and per-call.
    Scope is enforced: all_sessions requires explicit settings permission.
    """

    def __init__(self, settings: Settings, chat_repo: ChatRepository | None = None) -> None:
        self._settings = settings
        if chat_repo is not None:
            self._chat_repo = chat_repo
        else:
            from core.storage.db import Database
            db = Database(settings)
            db.init_database()
            self._chat_repo = ChatRepository(db=db)

    def search(
        self,
        query: str,
        *,
        current_session_id: str,
        scope: SessionSearchScope = SessionSearchScope.CURRENT_SESSION,
        limit: int = 5,
    ) -> SessionSearchResponse:
        """Search chat history with enforced bounds and sanitization.

        Args:
            query: Search query string (empty query rejected).
            current_session_id: Current session ID for scope filtering.
            scope: Search scope (current_session or all_sessions).
            limit: Max results to return (capped at 10).

        Returns:
            SessionSearchResponse with sanitized, bounded results.
        """
        query = query.strip()
        if not query:
            return SessionSearchResponse(
                query=query,
                scope=scope.value,
                note="Empty query rejected.",
            )

        # Enforce scope policy
        effective_scope = scope
        if scope == SessionSearchScope.ALL_SESSIONS:
            if self._settings.memory_session_search_default_scope != "all_sessions":
                logger.info("session_search: all_sessions denied by settings policy")
                effective_scope = SessionSearchScope.CURRENT_SESSION

        # Search
        session_filter = (
            current_session_id
            if effective_scope == SessionSearchScope.CURRENT_SESSION
            else None
        )
        limit = min(max(limit, 1), 10)  # Cap at 10

        try:
            messages = self._chat_repo.search_messages(
                query=query,
                session_id=session_filter,
                limit=limit * 2,  # Fetch more to allow truncation
            )
        except Exception as exc:
            logger.warning("session_search: ChatRepo search failed: %s", exc)
            return SessionSearchResponse(
                query=query,
                scope=effective_scope.value,
                note=f"Search failed: {exc}",
            )

        if not messages:
            return SessionSearchResponse(
                query=query,
                scope=effective_scope.value,
                note="No results found.",
            )

        # Sanitize and bound results
        max_result_chars = self._settings.memory_session_search_max_result_chars
        total_budget = self._settings.memory_session_search_total_budget_chars

        results: list[SessionSearchResult] = []
        budget_used = 0
        budget_exhausted = False

        for msg in messages[:limit]:
            clean_content = _sanitize_text(msg.content)
            if not clean_content:
                continue

            # Truncate per-item
            if len(clean_content) > max_result_chars:
                clean_content = clean_content[:max_result_chars] + "..."

            # Check total budget
            if budget_used + len(clean_content) > total_budget:
                budget_exhausted = True
                break

            budget_used += len(clean_content)
            results.append(SessionSearchResult(
                session_id=msg.session_id,
                message_id=msg.id,
                role=msg.role,
                content=clean_content,
                created_at=msg.created_at,
            ))

        return SessionSearchResponse(
            results=results,
            query=query,
            scope=effective_scope.value,
            total_found=len(messages),
            total_shown=len(results),
            budget_exhausted=budget_exhausted,
            note=(
                f"Budget exhausted ({total_budget} chars limit). {len(messages) - len(results)} results omitted."
                if budget_exhausted
                else f"Retrieved from local chat history. Source: {effective_scope.value}."
            ),
        )
