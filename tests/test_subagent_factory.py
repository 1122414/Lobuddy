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
        received_prompt = None

        async def mock_run_subagent(subagent_type, prompt):
            nonlocal received_prompt
            received_prompt = prompt
            return "analysis result"

        factory.run_subagent = mock_run_subagent

        result = run_async(factory.run_image_analysis("describe", "data:image/png;base64,abc"))

        assert result == "analysis result"
        assert "describe" in received_prompt
        assert "data:image/png;base64,abc" in received_prompt

    def test_run_subagent_creates_isolated_workspace(self, factory):
        workspaces = []

        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=MagicMock(content="ok"))

        with patch("nanobot.Nanobot") as MockBot:
            MockBot.from_config.return_value = mock_instance
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

        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=MagicMock(content="analysis done"))

        with patch("nanobot.Nanobot") as MockBot:
            MockBot.from_config.return_value = mock_instance
            with patch("core.agent.subagent_factory.shutil.rmtree"):
                run_async(factory_with_bus.run_image_analysis("desc", "data:url"))

        assert any(e[0] == "spawned" and e[1].subagent_type == "image_analysis" for e in events)
        assert any(
            e[0] == "completed" and e[1].success and e[1].summary == "analysis done" for e in events
        )

    def test_failure_event_published_and_workspace_cleaned(self, factory_with_bus):
        events = []

        async def handler(event):
            events.append(event)

        factory_with_bus.event_bus.subscribe(SubagentCompleted, handler)

        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(side_effect=RuntimeError("model boom"))

        with patch("nanobot.Nanobot") as MockBot:
            MockBot.from_config.return_value = mock_instance
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
