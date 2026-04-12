"""Tests for image analyzer sub-agent."""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, MagicMock

import httpx

from app.config import Settings
from core.agent.image_analyzer import ImageAnalyzer


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def mock_settings():
    return Settings(
        llm_api_key="test-key",
        llm_base_url="https://api.test/v1",
        llm_model="kimi-2.5",
        llm_multimodal_model="qwen-vl",
        task_timeout=10,
        llm_temperature=0.7,
        llm_max_tokens=4096,
    )


class TestImageAnalyzer:
    def test_analyze_success(self, mock_settings, tmp_path):
        img = tmp_path / "test.png"
        img.write_bytes(b"fake-image")
        analyzer = ImageAnalyzer(mock_settings)

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value={"choices": [{"message": {"content": "A red circle."}}]}
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = run_async(analyzer.analyze(str(img), "What color is the circle?"))
        assert "red circle" in result

    def test_analyze_missing_file(self, mock_settings):
        analyzer = ImageAnalyzer(mock_settings)
        result = run_async(analyzer.analyze("/nonexistent.png", "describe"))
        assert "not found" in result

    def test_analyze_timeout(self, mock_settings, tmp_path):
        img = tmp_path / "test.png"
        img.write_bytes(b"fake-image")
        analyzer = ImageAnalyzer(mock_settings)

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = run_async(analyzer.analyze(str(img), "describe"))
        assert "timed out" in result

    def test_analyze_uses_fallback_model(self, mock_settings, tmp_path):
        mock_settings.llm_multimodal_model = ""
        img = tmp_path / "test.png"
        img.write_bytes(b"fake-image")
        analyzer = ImageAnalyzer(mock_settings)

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"choices": [{"message": {"content": "ok"}}]})

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
        ) as mock_post:
            run_async(analyzer.analyze(str(img), "describe"))
        call_json = mock_post.call_args[1]["json"]
        assert call_json["model"] == "kimi-2.5"
