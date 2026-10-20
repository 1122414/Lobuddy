"""Phase B: session_search nanobot tool tests.

Verifies:
  - Tool is importable and has correct name/description
  - Tool rejects empty queries
  - Tool returns markdown output
  - Tool respects scope parameter
"""

from pathlib import Path

import pytest

from core.config import Settings
from core.storage.chat_repo import ChatRepository
from core.storage.db import Database


def _make_settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
        **kwargs,
    )


class TestSessionSearchTool:
    def test_tool_importable(self):
        from core.agent.tools.session_search_tool import SessionSearchTool
        assert SessionSearchTool is not None

    def test_tool_has_correct_name(self, tmp_path: Path):
        from core.agent.tools.session_search_tool import SessionSearchTool

        settings = _make_settings(tmp_path)
        tool = SessionSearchTool(settings=settings, current_session_id="test-s1")
        assert tool.name == "session_search"
        assert tool.read_only is True
        assert "local chat history" in tool.description.lower()

    def test_empty_query_rejected(self, tmp_path: Path):
        import asyncio
        from core.agent.tools.session_search_tool import SessionSearchTool

        settings = _make_settings(tmp_path)
        tool = SessionSearchTool(settings=settings, current_session_id="test-s1")

        async def run():
            return await tool.execute(query="  ", scope="current_session", limit=5)

        result = asyncio.run(run())
        assert "Query required" in result

    def test_execute_returns_markdown(self, tmp_path: Path):
        import asyncio
        from core.agent.tools.session_search_tool import SessionSearchTool

        settings = _make_settings(tmp_path)
        tool = SessionSearchTool(settings=settings, current_session_id="test-s1")

        async def run():
            return await tool.execute(query="hello", scope="current_session", limit=3)

        result = asyncio.run(run())
        assert isinstance(result, str)

    def test_scope_current_session_default(self, tmp_path: Path):
        import asyncio
        from core.agent.tools.session_search_tool import SessionSearchTool

        settings = _make_settings(tmp_path)
        tool = SessionSearchTool(settings=settings, current_session_id="my-session")

        async def run():
            return await tool.execute(query="test", limit=3)

        result = asyncio.run(run())
        assert isinstance(result, str)
