"""Integration test for main-agent -> analyze_image tool -> sub-agent chain."""

import base64
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from core.agent.image_analyzer import ImageAnalyzer
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


def test_full_image_analysis_chain(valid_image_path: Path):
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

    with patch.object(AgentRunner, "_request_model", fake_request_model):
        with patch.object(
            ImageAnalyzer,
            "analyze",
            new_callable=AsyncMock,
        ) as mock_analyze:
            mock_analyze.return_value = sub_agent_result

            import asyncio

            result = asyncio.run(_run_task(valid_image_path))

    assert result.success is True
    assert result.tools_used is not None
    assert "analyze_image" in result.tools_used
    assert final_llm_answer in result.raw_output
    assert call_count == 2
    mock_analyze.assert_awaited_once()
    assert str(valid_image_path) == str(mock_analyze.await_args.args[0])


async def _run_task(valid_image_path: Path):
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
    return await adapter.run_task(
        "What is in this image?",
        session_key="integration-test-session",
        image_path=str(valid_image_path),
    )
