import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from core.agent.subagent_factory import SubagentFactory
from core.events.bus import EventBus
from core.events.events import SubagentCompleted, SubagentSpawned


def run_async(coro):
    return asyncio.run(coro)


def _write_test_script(responses: list[dict]) -> Path:
    script = {"responses": responses}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(script, f)
        path = f.name
    return Path(path)


def _set_test_script_env(script_path: Path):
    os.environ["LOBUDDY_SUBAGENT_TEST_SCRIPT"] = str(script_path)


def _clear_test_script_env(script_path: Path | None = None):
    os.environ.pop("LOBUDDY_SUBAGENT_TEST_SCRIPT", None)
    if script_path:
        script_path.unlink(missing_ok=True)


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
        script_path = _write_test_script(
            [{"content": "ok", "tool_calls": [], "finish_reason": "stop"}]
        )
        _set_test_script_env(script_path)

        try:
            with patch("core.agent.subagent_factory.shutil.rmtree") as mock_rmtree:
                result = run_async(factory.run_subagent("image_analysis", "prompt"))

            cleaned_path = mock_rmtree.call_args_list[0].args[0]
            assert cleaned_path.name.startswith("lobuddy_image_analysis_")
            assert result == "ok"
        finally:
            _clear_test_script_env(script_path)

    def test_consecutive_calls_use_different_workspaces(self, factory):
        script_path = _write_test_script(
            [
                {"content": "a", "tool_calls": [], "finish_reason": "stop"},
                {"content": "b", "tool_calls": [], "finish_reason": "stop"},
            ]
        )
        _set_test_script_env(script_path)

        try:
            with patch("core.agent.subagent_factory.shutil.rmtree") as mock_rmtree:
                run_async(factory.run_subagent("image_analysis", "a"))
                run_async(factory.run_subagent("image_analysis", "b"))

            cleaned_paths = {call.args[0] for call in mock_rmtree.call_args_list}
            assert len(cleaned_paths) == 2
            assert all(p.name.startswith("lobuddy_image_analysis_") for p in cleaned_paths)
        finally:
            _clear_test_script_env(script_path)

    def test_consecutive_calls_use_different_workspaces(self, factory):
        script_path = _write_test_script(
            [
                {"content": "a", "tool_calls": [], "finish_reason": "stop"},
                {"content": "b", "tool_calls": [], "finish_reason": "stop"},
            ]
        )
        _set_test_script_env(script_path)

        try:
            with patch(
                "core.agent.subagent_factory.tempfile.mkdtemp",
                side_effect=["/tmp/lobuddy_1", "/tmp/lobuddy_2"],
            ):
                with patch("core.agent.subagent_factory.shutil.rmtree") as mock_rmtree:
                    run_async(factory.run_subagent("image_analysis", "a"))
                    run_async(factory.run_subagent("image_analysis", "b"))

            cleaned_paths = {call.args[0] for call in mock_rmtree.call_args_list}
            assert Path("/tmp/lobuddy_1") in cleaned_paths
            assert Path("/tmp/lobuddy_2") in cleaned_paths
            assert len(cleaned_paths) == 2
        finally:
            _clear_test_script_env(script_path)

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

        script_path = _write_test_script(
            [{"content": "analysis done", "tool_calls": [], "finish_reason": "stop"}]
        )
        _set_test_script_env(script_path)

        try:
            with patch("core.agent.subagent_factory.shutil.rmtree"):
                run_async(factory_with_bus.run_image_analysis("desc", "/tmp/img.png"))

            assert any(e[0] == "spawned" and e[1].subagent_type == "image_analysis" for e in events)
            assert any(
                e[0] == "completed" and e[1].success and e[1].summary == "analysis done"
                for e in events
            )
        finally:
            _clear_test_script_env(script_path)

    def test_media_passed_to_inbound_message(self, factory):
        script_path = _write_test_script(
            [{"content": "ok", "tool_calls": [], "finish_reason": "stop"}]
        )
        _set_test_script_env(script_path)
        old_capture = os.environ.get("LOBUDDY_SUBAGENT_CAPTURE_DETAILS")
        os.environ["LOBUDDY_SUBAGENT_CAPTURE_DETAILS"] = "1"

        try:
            with patch("core.agent.subagent_factory.shutil.rmtree"):
                run_async(factory.run_image_analysis("desc", "/tmp/img.png"))

            details = (factory._last_raw_result or {}).get("_details", {})
            assert details.get("media_paths") == ["/tmp/img.png"]
        finally:
            _clear_test_script_env(script_path)
            if old_capture is None:
                os.environ.pop("LOBUDDY_SUBAGENT_CAPTURE_DETAILS", None)
            else:
                os.environ["LOBUDDY_SUBAGENT_CAPTURE_DETAILS"] = old_capture

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

        script_path = _write_test_script(
            [{"content": "ok", "tool_calls": [], "finish_reason": "stop"}]
        )
        _set_test_script_env(script_path)

        try:
            with patch(
                "core.agent.subagent_factory.build_nanobot_config",
                side_effect=capture_build,
            ):
                with patch("core.agent.subagent_factory.shutil.rmtree"):
                    run_async(factory.run_subagent("image_analysis", "prompt"))

            provider = config_captured["config"]["providers"]["custom"]
            assert provider["apiKey"] == "test-key"
            assert provider.get("apiBase") == "https://api.openai.com/v1"
        finally:
            _clear_test_script_env(script_path)

    def test_failure_event_published_and_workspace_cleaned(self, factory_with_bus):
        events = []

        async def handler(event):
            events.append(event)

        factory_with_bus.event_bus.subscribe(SubagentCompleted, handler)

        script_path = _write_test_script([{"__raise": "model boom"}])
        _set_test_script_env(script_path)

        try:
            with patch("core.agent.subagent_factory.shutil.rmtree") as mock_rmtree:
                with pytest.raises(RuntimeError, match="model boom"):
                    run_async(factory_with_bus.run_subagent("image_analysis", "prompt"))

                mock_rmtree.assert_called_once()

            assert len(events) == 1
            assert events[0].success is False
            assert "model boom" in events[0].summary
        finally:
            _clear_test_script_env(script_path)

    def test_spec_uses_multimodal_overrides(self, factory):
        spec = factory._get_spec("image_analysis")

        assert spec.model == "qwen-vl"
        assert spec.base_url == "https://multimodal.test/v1"
        assert spec.api_key == "mm-key"
        assert spec.max_iterations == 3

    def test_system_prompt_injected_into_session(self, factory):
        script_path = _write_test_script(
            [{"content": "ok", "tool_calls": [], "finish_reason": "stop"}]
        )
        _set_test_script_env(script_path)
        old_capture = os.environ.get("LOBUDDY_SUBAGENT_CAPTURE_DETAILS")
        os.environ["LOBUDDY_SUBAGENT_CAPTURE_DETAILS"] = "1"

        try:
            with patch("core.agent.subagent_factory.shutil.rmtree"):
                run_async(factory.run_subagent("image_analysis", "prompt"))

            details = (factory._last_raw_result or {}).get("_details", {})
            assert details.get("system_prompt_injected") is True
            assert "image analysis expert" in str(details.get("system_prompt_content"))
        finally:
            _clear_test_script_env(script_path)
            if old_capture is None:
                os.environ.pop("LOBUDDY_SUBAGENT_CAPTURE_DETAILS", None)
            else:
                os.environ["LOBUDDY_SUBAGENT_CAPTURE_DETAILS"] = old_capture

    def test_session_key_format(self, factory):
        script_path = _write_test_script(
            [{"content": "ok", "tool_calls": [], "finish_reason": "stop"}]
        )
        _set_test_script_env(script_path)
        old_capture = os.environ.get("LOBUDDY_SUBAGENT_CAPTURE_DETAILS")
        os.environ["LOBUDDY_SUBAGENT_CAPTURE_DETAILS"] = "1"

        try:
            with patch("core.agent.subagent_factory.shutil.rmtree"):
                run_async(factory.run_subagent("image_analysis", "prompt"))

            details = (factory._last_raw_result or {}).get("_details", {})
            session_key = details.get("session_key")
            assert session_key is not None
            assert session_key.startswith("subagent:image_analysis:")
        finally:
            _clear_test_script_env(script_path)
            if old_capture is None:
                os.environ.pop("LOBUDDY_SUBAGENT_CAPTURE_DETAILS", None)
            else:
                os.environ["LOBUDDY_SUBAGENT_CAPTURE_DETAILS"] = old_capture
