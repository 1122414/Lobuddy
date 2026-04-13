import base64
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from core.agent.nanobot_adapter import NanobotAdapter


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
        adapter.subagent_factory.run_image_analysis = AsyncMock(return_value=sub_agent_result)

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

    asyncio.run(_inner())


def test_subagent_factory_chain_unmocked(valid_image_path: Path):
    sub_agent_result = "Red ball on table."
    final_llm_answer = "I see a red ball."

    async def fake_request_model(self, spec, messages, hook, context):
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        if spec.model == "kimi-2.5":
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

        return LLMResponse(
            content=sub_agent_result,
            tool_calls=[],
            finish_reason="stop",
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

    asyncio.run(_inner())


def test_concurrent_image_requests_use_isolated_sessions(valid_image_path: Path):
    call_ids = []

    async def fake_request_model(self, spec, messages, hook, context):
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        if spec.model == "kimi-2.5":
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
        return LLMResponse(
            content="analysis",
            tool_calls=[],
            finish_reason="stop",
        )

    import nanobot.agent.loop

    original_process_message = nanobot.agent.loop.AgentLoop._process_message

    async def tracking_process_message(self, msg, session_key=None, **kwargs):
        if session_key and session_key.startswith("subagent:"):
            call_ids.append(session_key)
            return type("Response", (), {"content": "analysis"})()
        return await original_process_message(self, msg, session_key=session_key, **kwargs)

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

        nanobot.agent.loop.AgentLoop._process_message = tracking_process_message
        try:
            with patch.object(AgentRunner, "_request_model", fake_request_model):
                with patch("core.agent.subagent_factory.shutil.rmtree"):
                    for i in range(2):
                        await adapter.run_task(
                            f"Image {i}",
                            session_key=f"main-session-{i}",
                            image_path=str(valid_image_path),
                        )
        finally:
            nanobot.agent.loop.AgentLoop._process_message = original_process_message

        subagent_sessions = [
            sid for sid in call_ids if sid and sid.startswith("subagent:image_analysis:")
        ]
        assert len(subagent_sessions) == 2
        assert subagent_sessions[0] != subagent_sessions[1]

    import asyncio

    asyncio.run(_inner())
