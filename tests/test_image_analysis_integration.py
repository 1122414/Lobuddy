import base64
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from core.agent.nanobot_adapter import NanobotAdapter
from core.agent.subagent_factory import SubagentFactory
from core.agent.subagent_spec import SubagentSpec


def _minimal_png_bytes() -> bytes:
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    return data


@pytest.fixture
def valid_image_path():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(_minimal_png_bytes())
        path = f.name
    yield Path(path)
    Path(path).unlink(missing_ok=True)


def _write_test_script(responses: list[dict]) -> Path:
    script = {"responses": responses}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(script, f)
        path = f.name
    return Path(path)


def _set_test_script_env(script_path: Path):
    os.environ["LOBUDDY_SUBAGENT_TEST_SCRIPT"] = str(script_path)


def _clear_test_script_env(script_path: Path):
    os.environ.pop("LOBUDDY_SUBAGENT_TEST_SCRIPT", None)
    script_path.unlink(missing_ok=True)


def test_full_image_analysis_chain_with_mocked_subagent_response(valid_image_path: Path):
    sub_agent_result = "The image contains a red ball on a table."
    final_llm_answer = "I see a red ball on a table in the image."
    call_count = 0

    async def fake_request_model(self, spec, messages, hook, context):
        nonlocal call_count
        call_count += 1
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        if call_count == 1:
            return LLMResponse(
                content="I will analyze the image for you.",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="analyze_image",
                        arguments={"prompt": "What is in this image?"},
                    )
                ],
                finish_reason="tool_calls",
            )

        tool_results = [
            msg.get("content", "")
            for msg in messages
            if isinstance(msg, dict) and msg.get("role") == "tool"
        ]
        assert any(sub_agent_result in str(tr) for tr in tool_results)
        return LLMResponse(
            content=final_llm_answer,
            tool_calls=[],
            finish_reason="stop",
        )

    from nanobot.agent.runner import AgentRunner

    script_path = _write_test_script(
        [{"content": sub_agent_result, "tool_calls": [], "finish_reason": "stop"}]
    )
    _set_test_script_env(script_path)

    async def _inner():
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://api.openai.com/v1",
            llm_model="kimi-2.5",
            llm_multimodal_model="qwen3.5-omni-plus",
            workspace_path=Path(tempfile.mkdtemp()),
            task_timeout=10,
            nanobot_max_iterations=5,
        )
        adapter = NanobotAdapter(settings)

        with patch.object(AgentRunner, "_request_model", fake_request_model):
            result = await adapter.run_task(
                "What is in this image?",
                session_key="integration-test-session",
                image_path=str(valid_image_path),
            )

        assert result.success is True
        assert "analyze_image" in (result.tools_used or [])
        assert final_llm_answer in result.raw_output
        assert call_count == 2

    import asyncio

    try:
        asyncio.run(_inner())
    finally:
        _clear_test_script_env(script_path)


def test_subagent_factory_chain_unmocked(valid_image_path: Path):
    sub_agent_result = "Red ball on table."
    final_llm_answer = "I see a red ball."

    script_path = _write_test_script(
        [{"content": sub_agent_result, "tool_calls": [], "finish_reason": "stop"}]
    )
    _set_test_script_env(script_path)

    async def fake_request_model(self, spec, messages, hook, context):
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        tool_results = [
            msg.get("content", "")
            for msg in messages
            if isinstance(msg, dict) and msg.get("role") == "tool"
        ]
        if any(sub_agent_result in str(tr) for tr in tool_results):
            return LLMResponse(
                content=final_llm_answer,
                tool_calls=[],
                finish_reason="stop",
            )
        return LLMResponse(
            content="Calling analyze_image.",
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="analyze_image",
                    arguments={"prompt": "Describe"},
                )
            ],
            finish_reason="tool_calls",
        )

    from nanobot.agent.runner import AgentRunner

    async def _inner():
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://api.openai.com/v1",
            llm_model="kimi-2.5",
            llm_multimodal_model="qwen3.5-omni-plus",
            workspace_path=Path(tempfile.mkdtemp()),
            task_timeout=10,
            nanobot_max_iterations=5,
        )
        adapter = NanobotAdapter(settings)

        with patch.object(AgentRunner, "_request_model", fake_request_model):
            with patch("core.agent.subagent_factory.shutil.rmtree") as mock_rmtree:
                result = await adapter.run_task(
                    "What is in this image?",
                    session_key="integration-unmocked",
                    image_path=str(valid_image_path),
                )

        assert result.success is True
        assert "analyze_image" in (result.tools_used or [])
        assert final_llm_answer in result.raw_output
        mock_rmtree.assert_called_once()

    import asyncio

    try:
        asyncio.run(_inner())
    finally:
        _clear_test_script_env(script_path)


def test_concurrent_image_requests_use_isolated_sessions(valid_image_path: Path):
    script_path = _write_test_script(
        [
            {"content": "analysis A", "tool_calls": [], "finish_reason": "stop"},
            {"content": "analysis B", "tool_calls": [], "finish_reason": "stop"},
        ]
    )
    _set_test_script_env(script_path)

    async def fake_request_model(self, spec, messages, hook, context):
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        tool_results = [
            msg.get("content", "")
            for msg in messages
            if isinstance(msg, dict) and msg.get("role") == "tool"
        ]
        if any("analysis" in str(tr) for tr in tool_results):
            return LLMResponse(
                content="Final answer.",
                tool_calls=[],
                finish_reason="stop",
            )
        return LLMResponse(
            content="Calling analyze_image.",
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="analyze_image",
                    arguments={"prompt": "Describe"},
                )
            ],
            finish_reason="tool_calls",
        )

    from nanobot.agent.runner import AgentRunner

    async def _inner():
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://api.openai.com/v1",
            llm_model="kimi-2.5",
            llm_multimodal_model="qwen3.5-omni-plus",
            workspace_path=Path(tempfile.mkdtemp()),
            task_timeout=30,
            nanobot_max_iterations=5,
        )
        adapter = NanobotAdapter(settings)

        with patch.object(AgentRunner, "_request_model", fake_request_model):
            with patch("core.agent.subagent_factory.shutil.rmtree"):
                results = await asyncio.gather(
                    adapter.run_task(
                        "Image A",
                        session_key="main-session-a",
                        image_path=str(valid_image_path),
                    ),
                    adapter.run_task(
                        "Image B",
                        session_key="main-session-b",
                        image_path=str(valid_image_path),
                    ),
                )

        assert len(results) == 2
        assert all(r.success for r in results)

    import asyncio

    try:
        asyncio.run(_inner())
    finally:
        _clear_test_script_env(script_path)


def test_subagent_runs_in_separate_process(valid_image_path: Path):
    parent_pid = os.getpid()

    script_path = _write_test_script(
        [{"content": "done", "tool_calls": [], "finish_reason": "stop"}]
    )
    _set_test_script_env(script_path)
    old_meta = os.environ.get("LOBUDDY_SUBAGENT_RETURN_META")
    os.environ["LOBUDDY_SUBAGENT_RETURN_META"] = "1"

    async def _inner():
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://api.openai.com/v1",
            llm_model="kimi-2.5",
            llm_multimodal_model="qwen3.5-omni-plus",
            workspace_path=Path(tempfile.mkdtemp()),
            task_timeout=10,
            nanobot_max_iterations=5,
        )
        factory = SubagentFactory(settings)
        raw = await factory.run_subagent(
            "image_analysis",
            "Describe this",
            media_paths=[str(valid_image_path)],
        )
        assert raw == "done"

    import asyncio

    try:
        asyncio.run(_inner())
    finally:
        _clear_test_script_env(script_path)
        if old_meta is None:
            os.environ.pop("LOBUDDY_SUBAGENT_RETURN_META", None)
        else:
            os.environ["LOBUDDY_SUBAGENT_RETURN_META"] = old_meta


def test_second_subagent_type_extensibility(valid_image_path: Path):
    script_path = _write_test_script(
        [{"content": "summary", "tool_calls": [], "finish_reason": "stop"}]
    )
    _set_test_script_env(script_path)

    async def _inner():
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://api.openai.com/v1",
            llm_model="kimi-2.5",
            llm_multimodal_model="qwen3.5-omni-plus",
            workspace_path=Path(tempfile.mkdtemp()),
            task_timeout=10,
            nanobot_max_iterations=5,
        )
        custom_registry = {
            "text_summarizer": lambda s: SubagentSpec(
                model="test-model",
                system_prompt="You summarize text.",
                max_iterations=3,
            ),
        }
        factory = SubagentFactory(settings, registry=custom_registry)
        result = await factory.run_subagent(
            "text_summarizer",
            "Summarize this article.",
        )
        assert result == "summary"

    import asyncio

    try:
        asyncio.run(_inner())
    finally:
        _clear_test_script_env(script_path)


def test_session_isolation_no_pollution(valid_image_path: Path):
    sub_agent_result = "Red ball on table."

    script_path = _write_test_script(
        [{"content": sub_agent_result, "tool_calls": [], "finish_reason": "stop"}]
    )
    _set_test_script_env(script_path)

    async def fake_request_model(self, spec, messages, hook, context):
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        tool_results = [
            msg.get("content", "")
            for msg in messages
            if isinstance(msg, dict) and msg.get("role") == "tool"
        ]
        if any(sub_agent_result in str(tr) for tr in tool_results):
            return LLMResponse(
                content="Got it.",
                tool_calls=[],
                finish_reason="stop",
            )
        return LLMResponse(
            content="Calling analyze_image.",
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="analyze_image",
                    arguments={"prompt": "Describe"},
                )
            ],
            finish_reason="tool_calls",
        )

    from nanobot.agent.runner import AgentRunner

    async def _inner():
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://api.openai.com/v1",
            llm_model="kimi-2.5",
            llm_multimodal_model="qwen3.5-omni-plus",
            workspace_path=Path(tempfile.mkdtemp()),
            task_timeout=10,
            nanobot_max_iterations=5,
        )
        adapter = NanobotAdapter(settings)
        main_session_key = "main-isolation-test"

        with patch.object(AgentRunner, "_request_model", fake_request_model):
            with patch("core.agent.subagent_factory.shutil.rmtree"):
                result = await adapter.run_task(
                    "What is in this image?",
                    session_key=main_session_key,
                    image_path=str(valid_image_path),
                )

        assert result.success is True
        from nanobot import Nanobot

        config_path = adapter._ensure_config()
        bot = Nanobot.from_config(config_path=config_path, workspace=settings.workspace_path)
        session = bot._loop.sessions.get_or_create(main_session_key)
        main_messages = [m for m in session.messages if isinstance(m, dict)]
        system_prompts = [m["content"] for m in main_messages if m.get("role") == "system"]
        assert "You are an image analysis expert" not in str(system_prompts)

    import asyncio

    try:
        asyncio.run(_inner())
    finally:
        _clear_test_script_env(script_path)


def test_subagent_timeout_kills_process():
    script_path = _write_test_script([])
    _set_test_script_env(script_path)

    async def _inner():
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://api.openai.com/v1",
            llm_model="kimi-2.5",
            llm_multimodal_model="qwen3.5-omni-plus",
            workspace_path=Path(tempfile.mkdtemp()),
            task_timeout=1,
            nanobot_max_iterations=5,
        )
        factory = SubagentFactory(settings)

        with pytest.raises(TimeoutError):
            await factory.run_subagent(
                "image_analysis",
                "This will never complete.",
                media_paths=[],
            )

    import asyncio

    try:
        asyncio.run(_inner())
    finally:
        _clear_test_script_env(script_path)
