"""Smoke tests for Lobuddy core functionality."""

import asyncio
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings, reload_settings
from core.agent.nanobot_adapter import AgentResult, NanobotAdapter


class TestConfiguration:
    """Test configuration management."""

    def test_settings_loads_from_env(self, monkeypatch):
        """Test that settings can be loaded from environment variables."""
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")

        settings = reload_settings()

        assert settings.llm_api_key == "test-key"
        assert settings.llm_model == "gpt-4o"

    def test_settings_validates_required_fields(self, monkeypatch):
        """Test that required fields are validated."""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_path_expansion(self, monkeypatch):
        """Test that paths are properly expanded."""
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv("WORKSPACE_PATH", "~/test_workspace")

        settings = reload_settings()
        # Should expand ~ to home directory
        assert "~" not in str(settings.workspace_path)


class TestNanobotAdapter:
    """Test NanobotAdapter functionality."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for testing."""
        return Settings(
            llm_api_key="test-key",
            llm_base_url="https://api.openai.com/v1",
            llm_model="gpt-4o-mini",
            workspace_path=Path(tempfile.mkdtemp()),
            task_timeout=5,
            nanobot_max_iterations=5,
        )

    def test_adapter_initialization(self, mock_settings):
        """Test that adapter can be initialized."""
        adapter = NanobotAdapter(mock_settings)
        assert adapter.settings == mock_settings
        assert adapter._bot is None

    def test_build_session_key(self, mock_settings):
        """Test session key generation."""
        adapter = NanobotAdapter(mock_settings)
        session_key = adapter.build_session_key("test-task")

        assert session_key == "lobuddy:session:test-task"

    def test_generate_summary(self, mock_settings):
        """Test summary generation."""
        adapter = NanobotAdapter(mock_settings)

        # Test short text
        short = "Hello world"
        assert adapter._generate_summary(short) == short

        # Test long text
        long_text = "A" * 500
        summary = adapter._generate_summary(long_text, max_length=100)
        assert "[Content truncated...]" in summary
        assert len(summary) > 100

        # Test empty text
        assert adapter._generate_summary("") == "No output"


class TestAgentResult:
    """Test AgentResult model."""

    def test_agent_result_creation(self):
        """Test that AgentResult can be created."""
        from datetime import datetime

        result = AgentResult(
            success=True,
            raw_output="test output",
            summary="test",
            started_at=datetime.now(),
            finished_at=datetime.now(),
        )

        assert result.success is True
        assert result.raw_output == "test output"


class TestBootstrap:
    """Test bootstrap functionality."""

    def test_directory_creation(self, tmp_path, monkeypatch):
        """Test that bootstrap creates necessary directories."""
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
        monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path / "workspace"))

        from app.bootstrap import create_directories

        settings = reload_settings()
        create_directories(settings)

        assert (tmp_path / "data").exists()
        assert (tmp_path / "logs").exists()
        assert (tmp_path / "workspace").exists()


@pytest.mark.anyio
class TestAsyncFunctionality:
    """Test async functionality."""

    async def test_health_check_with_invalid_config(self):
        """Test health check fails with invalid config."""
        from app.bootstrap import health_check

        settings = Settings(
            llm_api_key="invalid-key-for-testing",
            llm_base_url="https://invalid-url.test",
            workspace_path=Path(tempfile.mkdtemp()),
        )

        results = await health_check(settings)

        assert "config_loaded" in results
        assert "workspace_accessible" in results
        assert "nanobot_available" in results


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
