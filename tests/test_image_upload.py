"""Tests for nanobot adapter image handling with sub-agent tool."""

import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

from core.agent.nanobot_adapter import NanobotAdapter, AgentResult
from app.config import Settings


def run_async(coro):
    return asyncio.run(coro)


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

    def test_multimodal_model_missing_runs_main_agent_without_tool(self):
        settings = Settings(
            llm_api_key="test",
            llm_model="kimi-2.5",
            llm_multimodal_model="",
        )
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                session = MagicMock()
                session.messages = []
                bot_instance._loop.sessions.get_or_create.return_value = session
                bot_instance.run = AsyncMock(return_value=MagicMock(content="ok"))
                MockBot.from_config.return_value = bot_instance

                def check_mid_run(*args, **kwargs):
                    assert any(
                        msg.get("role") == "system" and "not configured" in msg.get("content", "")
                        for msg in session.messages
                    )
                    return MagicMock(content="ok")

                bot_instance.run = AsyncMock(side_effect=check_mid_run)
                result = run_async(adapter.run_task("hi", "s1", image_path="/img.jpg"))
                assert result.success is True
                bot_instance.run.assert_called_once()
                bot_instance._loop.tools.register.assert_not_called()

    def test_temp_system_message_added_and_removed(self):
        settings = Settings(llm_api_key="test", llm_model="kimi", llm_multimodal_model="qwen")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                session = MagicMock()
                session.messages = []
                bot_instance._loop.sessions.get_or_create.return_value = session

                def check_mid_run(*args, **kwargs):
                    assert any(
                        msg.get("role") == "system" and "analyze_image" in msg.get("content", "")
                        for msg in session.messages
                    )
                    return MagicMock(content="ok")

                bot_instance.run = AsyncMock(side_effect=check_mid_run)
                MockBot.from_config.return_value = bot_instance
                run_async(adapter.run_task("describe this", "s1", image_path="/img.jpg"))
                # After run completes, temp message is removed
                assert not any(
                    msg.get("role") == "system" and "analyze_image" in msg.get("content", "")
                    for msg in session.messages
                )

    def test_analyze_image_tool_registered_and_restored(self):
        settings = Settings(llm_api_key="test", llm_model="kimi", llm_multimodal_model="qwen")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                bot_instance.run = AsyncMock(return_value=MagicMock(content="ok"))
                prev_tool = MagicMock(name="previous_analyze_image_tool")
                bot_instance._loop.tools.get.return_value = prev_tool
                MockBot.from_config.return_value = bot_instance
                run_async(adapter.run_task("hi", "s1", image_path="/img.jpg"))
                bot_instance._loop.tools.register.assert_called()
                # In finally, previous tool is restored
                restore_calls = [
                    c
                    for c in bot_instance._loop.tools.register.call_args_list
                    if c[0][0] is prev_tool
                ]
                assert len(restore_calls) == 1
                bot_instance._loop.tools.unregister.assert_not_called()

    def test_analyze_image_tool_unregistered_when_no_previous(self):
        settings = Settings(llm_api_key="test", llm_model="kimi", llm_multimodal_model="qwen")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                bot_instance.run = AsyncMock(return_value=MagicMock(content="ok"))
                bot_instance._loop.tools.get.return_value = None
                MockBot.from_config.return_value = bot_instance
                run_async(adapter.run_task("hi", "s1", image_path="/img.jpg"))
                bot_instance._loop.tools.unregister.assert_called_once_with("analyze_image")

    def test_analyze_image_tool_restored_on_exception(self):
        settings = Settings(llm_api_key="test", llm_model="kimi", llm_multimodal_model="qwen")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                bot_instance.run = AsyncMock(side_effect=RuntimeError("boom"))
                prev_tool = MagicMock(name="previous_analyze_image_tool")
                bot_instance._loop.tools.get.return_value = prev_tool
                MockBot.from_config.return_value = bot_instance
                result = run_async(adapter.run_task("hi", "s1", image_path="/img.jpg"))
                assert result.success is False
                restore_calls = [
                    c
                    for c in bot_instance._loop.tools.register.call_args_list
                    if c[0][0] is prev_tool
                ]
                assert len(restore_calls) == 1

    def test_temp_system_message_removed_on_run_exception(self):
        settings = Settings(llm_api_key="test", llm_model="kimi", llm_multimodal_model="qwen")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                session = MagicMock()
                session.messages = []
                bot_instance._loop.sessions.get_or_create.return_value = session
                bot_instance.run = AsyncMock(side_effect=RuntimeError("boom"))
                MockBot.from_config.return_value = bot_instance
                result = run_async(adapter.run_task("hi", "s1", image_path="/img.jpg"))
                assert result.success is False
                assert not any(
                    msg.get("role") == "system" and "analyze_image" in msg.get("content", "")
                    for msg in session.messages
                )

    def test_temp_system_message_removed_on_timeout(self):
        settings = Settings(llm_api_key="test", llm_model="kimi", llm_multimodal_model="qwen")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                session = MagicMock()
                session.messages = []
                bot_instance._loop.sessions.get_or_create.return_value = session
                bot_instance.run = AsyncMock(side_effect=asyncio.TimeoutError("timeout"))
                MockBot.from_config.return_value = bot_instance
                result = run_async(adapter.run_task("hi", "s1", image_path="/img.jpg"))
                assert result.success is False
                assert not any(
                    msg.get("role") == "system" and "analyze_image" in msg.get("content", "")
                    for msg in session.messages
                )

    def test_no_stale_temp_message_in_next_text_turn(self):
        settings = Settings(llm_api_key="test", llm_model="kimi", llm_multimodal_model="qwen")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                session = MagicMock()
                session.messages = []
                bot_instance._loop.sessions.get_or_create.return_value = session
                bot_instance.run = AsyncMock(return_value=MagicMock(content="ok"))
                MockBot.from_config.return_value = bot_instance
                # First turn with image
                run_async(adapter.run_task("hi", "s1", image_path="/img.jpg"))
                # Second turn text-only
                run_async(adapter.run_task("second turn", "s1"))
                assert not any(
                    msg.get("role") == "system" and "analyze_image" in msg.get("content", "")
                    for msg in session.messages
                )

    def test_unboundlocal_error_fixed_on_pre_run_failure(self):
        settings = Settings(llm_api_key="test", llm_model="kimi", llm_multimodal_model="qwen")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                bot_instance = MagicMock()
                bot_instance.run = AsyncMock(return_value=MagicMock(content="ok"))
                MockBot.from_config.return_value = bot_instance
                with patch.object(
                    adapter,
                    "_compress_history_if_needed",
                    side_effect=RuntimeError("compress boom"),
                ):
                    result = run_async(adapter.run_task("hi", "s1", image_path="/img.jpg"))
                assert result.success is False
                assert "compress boom" in result.error_message

    def test_unboundlocal_error_fixed_on_nanobot_init_failure(self):
        settings = Settings(llm_api_key="test", llm_model="kimi", llm_multimodal_model="qwen")
        adapter = NanobotAdapter(settings)
        with patch.object(adapter, "_ensure_config"):
            with patch("nanobot.Nanobot") as MockBot:
                MockBot.from_config.side_effect = RuntimeError("nanobot init boom")
                result = run_async(adapter.run_task("hi", "s1", image_path="/img.jpg"))
                assert result.success is False
                assert "nanobot init boom" in result.error_message

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
