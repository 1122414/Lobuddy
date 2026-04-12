import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from core.agent.subagent_factory import SubagentFactory
from core.events.bus import EventBus
from core.events.events import SubagentCompleted, SubagentSpawned


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture
def factory():
    settings = Settings(
        llm_api_key="test-key",
        llm_base_url="https://api.openai.com/v1",
        llm_model="kimi-2.5",
        llm_multimodal_model="qwen-vl",
        llm_multimodal_base_url="https://multimodal.test/v1",
        llm_multimodal_api_key="mm-key",
        nanobot_max_iterations=3,
    )
    return SubagentFactory(settings)


@pytest.fixture
def factory_with_bus():
    settings = Settings(
        llm_api_key="test-key",
        llm_model="kimi-2.5",
        llm_multimodal_model="qwen-vl",
        nanobot_max_iterations=3,
    )
    bus = EventBus()
    return SubagentFactory(settings, bus)


class TestSubagentFactory:
    def test_run_image_analysis_delegates_to_run_subagent(self, factory):
        received = {}

        async def mock_run_subagent(subagent_type, prompt, session_key=None, media_paths=None):
            received["subagent_type"] = subagent_type
            received["prompt"] = prompt
            received["media_paths"] = media_paths
            return "analysis result"

        factory.run_subagent = mock_run_subagent

        result = run_async(factory.run_image_analysis("describe", "/tmp/img.png"))

        assert result == "analysis result"
        assert received["subagent_type"] == "image_analysis"
        assert received["prompt"] == "describe"
        assert received["media_paths"] == ["/tmp/img.png"]

    def test_run_subagent_creates_isolated_workspace(self, factory):
        with patch("nanobot.Nanobot") as MockBot:
            mock_loop = MagicMock()
            mock_loop._process_message = AsyncMock(return_value=MagicMock(content="ok"))
            MockBot.from_config.return_value = MagicMock(_loop=mock_loop)
            with patch("core.agent.subagent_factory.shutil.rmtree") as mock_rmtree:
                with patch(
                    "core.agent.subagent_factory.tempfile.mkdtemp",
                    side_effect=["/tmp/lobuddy_image_analysis_1"],
                ):
                    result = run_async(factory.run_subagent("image_analysis", "prompt"))

                mock_rmtree.assert_called_once_with(
                    Path("/tmp/lobuddy_image_analysis_1"), ignore_errors=True
                )

        assert result == "ok"

    def test_consecutive_calls_use_different_workspaces(self, factory):
        with patch("nanobot.Nanobot") as MockBot:
            mock_loop = MagicMock()
            mock_loop._process_message = AsyncMock(return_value=MagicMock(content="ok"))
            MockBot.from_config.return_value = MagicMock(_loop=mock_loop)
            with patch("core.agent.subagent_factory.shutil.rmtree"):
                with patch(
                    "core.agent.subagent_factory.tempfile.mkdtemp",
                    side_effect=[
                        "/tmp/lobuddy_1",
                        "/tmp/lobuddy_2",
                    ],
                ):
                    run_async(factory.run_subagent("image_analysis", "a"))
                    run_async(factory.run_subagent("image_analysis", "b"))

        workspaces = [
            call.kwargs.get("workspace") or call.kwargs.get("config_path").parent.parent
            for call in MockBot.from_config.call_args_list
        ]
        assert len(workspaces) == 2
        assert workspaces[0] != workspaces[1]

    def test_missing_model_raises_value_error(self, factory):
        factory.settings.llm_multimodal_model = ""

        with pytest.raises(ValueError, match="not configured"):
            run_async(factory.run_subagent("image_analysis", "prompt"))

    def test_unknown_subagent_type_raises(self, factory):
        with pytest.raises(ValueError, match="Unknown subagent type"):
            run_async(factory.run_subagent("unknown_type", "prompt"))

    def test_events_published_on_success(self, factory_with_bus):
        events = []

        async def handler_a(event):
            events.append(("spawned", event))

        async def handler_b(event):
            events.append(("completed", event))

        factory_with_bus.event_bus.subscribe(SubagentSpawned, handler_a)
        factory_with_bus.event_bus.subscribe(SubagentCompleted, handler_b)

        with patch("nanobot.Nanobot") as MockBot:
            mock_loop = MagicMock()
            mock_loop._process_message = AsyncMock(return_value=MagicMock(content="analysis done"))
            MockBot.from_config.return_value = MagicMock(_loop=mock_loop)
            with patch("core.agent.subagent_factory.shutil.rmtree"):
                run_async(factory_with_bus.run_image_analysis("desc", "/tmp/img.png"))

        assert any(e[0] == "spawned" and e[1].subagent_type == "image_analysis" for e in events)
        assert any(
            e[0] == "completed" and e[1].success and e[1].summary == "analysis done" for e in events
        )

    def test_media_passed_to_inbound_message(self, factory):
        with patch("nanobot.Nanobot") as MockBot:
            mock_loop = MagicMock()
            mock_loop._process_message = AsyncMock(return_value=MagicMock(content="ok"))
            MockBot.from_config.return_value = MagicMock(_loop=mock_loop)
            with patch("core.agent.subagent_factory.shutil.rmtree"):
                run_async(factory.run_image_analysis("desc", "/tmp/img.png"))

            call_args = mock_loop._process_message.call_args
            msg = call_args.args[0]
            assert msg.media == ["/tmp/img.png"]

    def test_multimodal_empty_string_does_not_override_main_config(self, factory):
        factory.settings.llm_multimodal_base_url = ""
        factory.settings.llm_multimodal_api_key = ""

        config_captured = {}

        original_build = None

        def capture_build(settings, model, workspace):
            from core.agent.config_builder import build_nanobot_config as real_build

            nonlocal original_build
            if original_build is None:
                original_build = real_build
            config = original_build(settings, model, workspace)
            config_captured["config"] = config
            return config

        with patch("core.agent.subagent_factory.build_nanobot_config", side_effect=capture_build):
            with patch("nanobot.Nanobot") as MockBot:
                mock_loop = MagicMock()
                mock_loop._process_message = AsyncMock(return_value=MagicMock(content="ok"))
                MockBot.from_config.return_value = MagicMock(_loop=mock_loop)
                with patch("core.agent.subagent_factory.shutil.rmtree"):
                    run_async(factory.run_subagent("image_analysis", "prompt"))

        provider = config_captured["config"]["providers"]["custom"]
        assert provider["apiKey"] == "test-key"
        assert provider.get("apiBase") == "https://api.openai.com/v1"

    def test_failure_event_published_and_workspace_cleaned(self, factory_with_bus):
        events = []

        async def handler(event):
            events.append(event)

        factory_with_bus.event_bus.subscribe(SubagentCompleted, handler)

        with patch("nanobot.Nanobot") as MockBot:
            mock_loop = MagicMock()
            mock_loop._process_message = AsyncMock(side_effect=RuntimeError("model boom"))
            MockBot.from_config.return_value = MagicMock(_loop=mock_loop)
            with patch("core.agent.subagent_factory.shutil.rmtree") as mock_rmtree:
                with pytest.raises(RuntimeError, match="model boom"):
                    run_async(factory_with_bus.run_subagent("image_analysis", "prompt"))

                mock_rmtree.assert_called_once()

        assert len(events) == 1
        assert events[0].success is False
        assert "model boom" in events[0].summary

    def test_spec_uses_multimodal_overrides(self, factory):
        spec = factory._get_spec("image_analysis")

        assert spec.model == "qwen-vl"
        assert spec.base_url == "https://multimodal.test/v1"
        assert spec.api_key == "mm-key"
        assert spec.max_iterations == 3

    def test_system_prompt_injected_into_session(self, factory):
        session = MagicMock()
        session.messages = []
        seen_messages = []

        async def fake_process(msg, session_key):
            seen_messages.extend(list(session.messages))
            return MagicMock(content="ok")

        with patch("nanobot.Nanobot") as MockBot:
            mock_loop = MagicMock()
            mock_loop._process_message = fake_process
            mock_sessions = MagicMock()
            mock_sessions.get_or_create.return_value = session
            mock_loop.sessions = mock_sessions
            MockBot.from_config.return_value = MagicMock(_loop=mock_loop)
            with patch("core.agent.subagent_factory.shutil.rmtree"):
                run_async(factory.run_subagent("image_analysis", "prompt"))

        assert any(
            isinstance(m, dict)
            and m.get("role") == "system"
            and "image analysis expert" in m.get("content", "")
            for m in seen_messages
        )
        mock_sessions.save.assert_called()

    def test_session_key_format(self, factory):
        with patch("nanobot.Nanobot") as MockBot:
            mock_loop = MagicMock()
            mock_loop._process_message = AsyncMock(return_value=MagicMock(content="ok"))
            MockBot.from_config.return_value = MagicMock(_loop=mock_loop)
            with patch("core.agent.subagent_factory.shutil.rmtree"):
                run_async(factory.run_subagent("image_analysis", "prompt"))

        call_args = mock_loop._process_message.call_args
        session_key = call_args.kwargs.get("session_key")
        assert session_key is not None
        assert session_key.startswith("subagent:image_analysis:")
