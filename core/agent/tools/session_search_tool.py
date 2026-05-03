"""5.3 session_search nanobot tool — controlled cold recall of chat history."""
from __future__ import annotations

import logging
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, IntegerSchema, tool_parameters_schema

from core.config import Settings
from core.memory.session_search import SessionSearchScope, SessionSearchService

logger = logging.getLogger("lobuddy.session_search_tool")


@tool_parameters(
    tool_parameters_schema(
        query=StringSchema("Search query for chat history"),
        scope=StringSchema("Scope: current_session or all_sessions"),
        limit=IntegerSchema("Max results (1-10, default 5)"),
        required=["query"],
    )
)
class SessionSearchTool(Tool):
    """nanobot tool for searching local chat history.

    Security: results are sanitized (secrets redacted), bounded per-item
    and per-call. Only registered when memory_session_search_enabled is True.
    """

    def __init__(
        self,
        settings: Settings,
        current_session_id: str,
    ) -> None:
        self._search_service = SessionSearchService(settings)
        self._current_session_id = current_session_id

    @property
    def name(self) -> str:
        return "session_search"

    @property
    def description(self) -> str:
        return (
            "Search your local chat history for relevant information. "
            "Use this when you need to recall past conversations, decisions, or context "
            "that isn't in the current prompt. Results are from LOCAL chat history only. "
            "Default scope is current_session — only search all_sessions when explicitly needed."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        query: str = "",
        scope: str = "current_session",
        limit: int = 5,
        **kwargs: Any,
    ) -> str:
        if not query.strip():
            return "*session_search: Query required.*"

        search_scope = SessionSearchScope.CURRENT_SESSION
        if scope == "all_sessions":
            search_scope = SessionSearchScope.ALL_SESSIONS

        response = self._search_service.search(
            query=query,
            current_session_id=self._current_session_id,
            scope=search_scope,
            limit=limit,
        )

        logger.info(
            "session_search: query=%s scope=%s found=%d shown=%d",
            query[:50], response.scope, response.total_found, response.total_shown,
        )

        return response.to_markdown()
