"""Tests for nanobot adapter image upload functionality."""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open, AsyncMock

sys.modules["nanobot"] = MagicMock()
sys.modules["nanobot.bus"] = MagicMock()
sys.modules["nanobot.bus.events"] = MagicMock()

from core.agent.nanobot_adapter import NanobotAdapter, AgentResult
from app.config import Settings


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestMoonshotProviderDetection:
    def test_moonshot_by_api_base(self):
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://api.moonshot.ai/v1",
            llm_model="kimi-k2.5",
        )
        adapter = NanobotAdapter(settings)
        assert adapter._is_moonshot_provider() is True

    def test_moonshot_by_base_url_containing_moonshot(self):
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://custom.moonshot.cn/v1",
            llm_model="gpt-4",
        )
        adapter = NanobotAdapter(settings)
        assert adapter._is_moonshot_provider() is True

    def test_not_moonshot_openrouter_with_kimi_model(self):
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://openrouter.ai/api/v1",
            llm_model="moonshot/kimi-k2.5",
        )
        adapter = NanobotAdapter(settings)
        assert adapter._is_moonshot_provider() is False

    def test_not_moonshot_openai_base(self):
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://api.openai.com/v1",
            llm_model="kimi-k2.5",
        )
        adapter = NanobotAdapter(settings)
        assert adapter._is_moonshot_provider() is False

    def test_moonshot_fallback_when_empty_base(self):
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="",
            llm_model="kimi-moonshot-k2.5",
        )
        adapter = NanobotAdapter(settings)
        assert adapter._is_moonshot_provider() is True

    def test_not_moonshot_other_provider(self):
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://api.deepseek.com",
            llm_model="deepseek-chat",
        )
        adapter = NanobotAdapter(settings)
        assert adapter._is_moonshot_provider() is False


class TestImageMessageBuilding:
    def test_build_message_with_file_id(self):
        settings = Settings(llm_api_key="test")
        adapter = NanobotAdapter(settings)
        content = adapter._build_image_message("Analyze this", "file-123")
        assert len(content) == 2
        assert content[0] == {"type": "image_url", "image_url": {"url": "ms://file-123"}}
        assert content[1] == {"type": "text", "text": "Analyze this"}

    def test_build_message_without_prompt(self):
        settings = Settings(llm_api_key="test")
        adapter = NanobotAdapter(settings)
        content = adapter._build_image_message("", "file-456")
        assert len(content) == 1
        assert content[0] == {"type": "image_url", "image_url": {"url": "ms://file-456"}}

    def test_build_message_without_file_id(self):
        settings = Settings(llm_api_key="test")
        adapter = NanobotAdapter(settings)
        content = adapter._build_image_message("Analyze this", None)
        assert len(content) == 1
        assert content[0]["type"] == "text"


class TestUploadToMoonshotRuntime:
    def test_upload_makes_correct_api_call(self):
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://api.moonshot.ai/v1",
        )
        adapter = NanobotAdapter(settings)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "file-abc123"}

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = mock_response
            with patch("builtins.open", mock_open(read_data=b"fake-image-data")):
                with patch.object(Path, "is_file", return_value=True):
                    with patch("mimetypes.guess_type", return_value=("image/jpeg", None)):
                        result = run_async(adapter._upload_image_to_moonshot("/path/to/image.jpg"))

        assert result == "file-abc123"
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://api.moonshot.ai/v1/files"
        assert call_args[1]["data"]["purpose"] == "image"

    def test_upload_with_url_normalization(self):
        settings = Settings(
            llm_api_key="test-key",
            llm_base_url="https://api.moonshot.ai",
        )
        adapter = NanobotAdapter(settings)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "file-xyz"}

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = mock_response
            with patch("builtins.open", mock_open(read_data=b"fake")):
                with patch.object(Path, "is_file", return_value=True):
                    with patch("mimetypes.guess_type", return_value=("image/png", None)):
                        result = run_async(adapter._upload_image_to_moonshot("/path/to/img.png"))

        call_args = mock_post.call_args
        assert call_args[0][0] == "https://api.moonshot.ai/v1/files"


class TestAdapterStructure:
    def test_has_all_required_methods(self):
        settings = Settings(llm_api_key="test")
        adapter = NanobotAdapter(settings)
        required_methods = [
            "run_task",
            "_upload_image_to_moonshot",
            "_build_image_message",
            "_is_moonshot_provider",
            "build_session_key",
            "_create_temp_config",
        ]
        for method in required_methods:
            assert hasattr(adapter, method), f"Missing method: {method}"

    def test_is_moonshot_provider_returns_bool(self):
        settings = Settings(
            llm_api_key="test",
            llm_base_url="https://api.moonshot.ai/v1",
        )
        adapter = NanobotAdapter(settings)
        result = adapter._is_moonshot_provider()
        assert isinstance(result, bool)
