"""Tests for nanobot adapter image handling with sub-agent tool."""

import pytest
import asyncio
import sys
from unittest.mock import MagicMock, patch, AsyncMock

sys.modules["nanobot"] = MagicMock()
sys.modules["nanobot.bus"] = MagicMock()
sys.modules["nanobot.bus.events"] = MagicMock()

from core.agent.nanobot_adapter import NanobotAdapter, AgentResult
from app.config import Settings


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestAdapterImageHandling:
    def test_no_model_switch_on_image(self):
        settings = Settings(
            llm_api_key="test",
            llm_model="kimi-2.5",
            llm_multimodal_model="qwen-vl",
        )
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config") as mock_ensure:
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                bot_instance.run = AsyncMock(return_value=MagicMock(content="ok"))
                MockBot.from_config.return_value = bot_instance
                run_async(adapter.run_task("hi", "s1", image_path="/img.jpg"))
        assert mock_ensure.call_args[1]["model"] == "kimi-2.5"

    def test_prompt_appended_with_image_note(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                bot_instance.run = AsyncMock(return_value=MagicMock(content="ok"))
                MockBot.from_config.return_value = bot_instance
                run_async(adapter.run_task("describe this", "s1", image_path="/img.jpg"))
                call_prompt = bot_instance.run.call_args[0][0]
                assert "uploaded an image" in call_prompt
                assert "analyze_image tool" in call_prompt

    def test_analyze_image_tool_registered_and_unregistered(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                bot_instance.run = AsyncMock(return_value=MagicMock(content="ok"))
                MockBot.from_config.return_value = bot_instance
                run_async(adapter.run_task("hi", "s1", image_path="/img.jpg"))
                bot_instance._loop.tools.register.assert_called_once()
                bot_instance._loop.tools.unregister.assert_called_once_with("analyze_image")

    def test_tools_used_returned_in_result(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                bot_instance.run = AsyncMock(return_value=MagicMock(content="done"))
                MockBot.from_config.return_value = bot_instance
                result = run_async(adapter.run_task("hi", "s1", image_path="/img.jpg"))
                assert isinstance(result, AgentResult)
                assert result.tools_used is None

    def test_analyze_image_tool_unregistered_on_exception(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                bot_instance.run = AsyncMock(side_effect=RuntimeError("boom"))
                MockBot.from_config.return_value = bot_instance
                result = run_async(adapter.run_task("hi", "s1", image_path="/img.jpg"))
                assert result.success is False
                bot_instance._loop.tools.unregister.assert_called_once_with("analyze_image")

    def test_text_task_no_tool_registration(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                bot_instance.run = AsyncMock(return_value=MagicMock(content="ok"))
                MockBot.from_config.return_value = bot_instance
                run_async(adapter.run_task("hi", "s1"))
                bot_instance._loop.tools.register.assert_not_called()
                bot_instance._loop.tools.unregister.assert_not_called()
