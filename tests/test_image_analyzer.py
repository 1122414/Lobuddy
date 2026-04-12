"""Tests for image analyzer sub-agent."""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
    def _make_png(self, tmp_path, name="test.png"):
        img = tmp_path / name
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake-body")
        return img

    def test_analyze_success(self, mock_settings, tmp_path):
        img = self._make_png(tmp_path)
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
        img = self._make_png(tmp_path)
        analyzer = ImageAnalyzer(mock_settings)

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = run_async(analyzer.analyze(str(img), "describe"))
        assert "timed out" in result

    def test_analyze_file_too_large(self, mock_settings, tmp_path):
        img = self._make_png(tmp_path)
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024))
        analyzer = ImageAnalyzer(mock_settings)
        result = run_async(analyzer.analyze(str(img), "describe"))
        assert "too large" in result

    def test_analyze_unsupported_extension(self, mock_settings, tmp_path):
        img = tmp_path / "malware.exe"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"body")
        analyzer = ImageAnalyzer(mock_settings)
        result = run_async(analyzer.analyze(str(img), "describe"))
        assert "Unsupported file type" in result

    def test_analyze_invalid_magic_bytes(self, mock_settings, tmp_path):
        img = tmp_path / "fake.png"
        img.write_bytes(b"not-an-image")
        analyzer = ImageAnalyzer(mock_settings)
        result = run_async(analyzer.analyze(str(img), "describe"))
        assert "not appear to be a valid image" in result

    def test_analyze_missing_multimodal_model(self, mock_settings, tmp_path):
        mock_settings.llm_multimodal_model = ""
        img = self._make_png(tmp_path)
        analyzer = ImageAnalyzer(mock_settings)
        result = run_async(analyzer.analyze(str(img), "describe"))
        assert "Multimodal model not configured" in result

    def test_analyze_uses_multimodal_endpoint_and_key(self, mock_settings, tmp_path):
        mock_settings.llm_multimodal_base_url = "https://multimodal.test/v1"
        mock_settings.llm_multimodal_api_key = "multi-key"
        img = self._make_png(tmp_path)
        analyzer = ImageAnalyzer(mock_settings)

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"choices": [{"message": {"content": "ok"}}]})

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
        ) as mock_post:
            run_async(analyzer.analyze(str(img), "describe"))

        call_url = mock_post.call_args[0][0]
        call_headers = mock_post.call_args[1]["headers"]
        assert call_url.startswith("https://multimodal.test/v1")
        assert call_headers["Authorization"] == "Bearer multi-key"

    def test_analyze_sanitized_http_error(self, mock_settings, tmp_path):
        img = self._make_png(tmp_path)
        analyzer = ImageAnalyzer(mock_settings)

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Bad Request",
                request=MagicMock(),
                response=MagicMock(status_code=400, text="invalid api key"),
            )
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = run_async(analyzer.analyze(str(img), "describe"))
        assert "service failed" in result
        assert "invalid api key" not in result
