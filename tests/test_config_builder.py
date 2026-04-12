"""Tests for config_builder module."""

import json
import tempfile
from pathlib import Path

import pytest

from app.config import Settings
from core.agent.config_builder import build_nanobot_config, write_temp_config


class TestBuildNanobotConfig:
    """Tests for build_nanobot_config."""

    def test_returns_correct_keys_for_given_model(self):
        """Test that build_nanobot_config returns the expected structure."""
        settings = Settings(
            llm_api_key="test-api-key",
            llm_base_url="https://api.test.com/v1",
            llm_model="gpt-4o",
            nanobot_max_iterations=10,
            history_compress_prompt="Compress this",
        )
        workspace = Path("/tmp/test_workspace")

        config = build_nanobot_config(settings, "gpt-4o-mini", workspace)

        assert config["providers"]["custom"]["apiKey"] == "test-api-key"
        assert config["providers"]["custom"]["apiBase"] == "https://api.test.com/v1"
        assert config["agents"]["defaults"]["provider"] == "custom"
        assert config["agents"]["defaults"]["model"] == "gpt-4o-mini"
        assert config["agents"]["defaults"]["maxToolIterations"] == 10
        assert config["agents"]["defaults"]["historyCompressPrompt"] == "Compress this"
        assert config["agents"]["defaults"]["workspace"] == str(workspace)

    def test_api_base_omitted_when_empty(self):
        """Test that apiBase is omitted when llm_base_url is empty."""
        settings = Settings(
            llm_api_key="test-api-key",
            llm_base_url="",
            llm_model="gpt-4o",
        )
        workspace = Path("/tmp/workspace")

        config = build_nanobot_config(settings, "gpt-4o", workspace)

        assert "apiBase" not in config["providers"]["custom"]

    def test_mcp_servers_included_when_present(self):
        """Test that mcpServers is included when settings has mcp_servers."""
        settings = Settings(
            llm_api_key="test-api-key",
            llm_model="gpt-4o",
        )
        object.__setattr__(
            settings,
            "mcp_servers",
            {
                "server1": {"command": "npx", "args": ["-y", "mcp-server"]},
            },
        )
        workspace = Path("/tmp/workspace")

        config = build_nanobot_config(settings, "gpt-4o", workspace)

        assert config["mcpServers"] == settings.mcp_servers

    def test_mcp_servers_omitted_when_empty(self):
        """Test that mcpServers is omitted when settings has no mcp_servers."""
        settings = Settings(
            llm_api_key="test-api-key",
            llm_model="gpt-4o",
        )
        workspace = Path("/tmp/workspace")

        config = build_nanobot_config(settings, "gpt-4o", workspace)

        assert "mcpServers" not in config


class TestWriteTempConfig:
    """Tests for write_temp_config."""

    def test_creates_file_and_returns_correct_path(self):
        """Test that write_temp_config writes JSON and returns the path."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir)
            config = {"agents": {"defaults": {"model": "test-model"}}}

            path = write_temp_config(config, config_dir, "test-label")

            assert path == config_dir / "nanobot_config_test-label.json"
            assert path.exists()

            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded == config

    def test_creates_missing_directories(self):
        """Test that write_temp_config creates missing directories."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir) / "nested" / "dir"
            config = {"test": "value"}

            path = write_temp_config(config, config_dir, "label")

            assert config_dir.exists()
            assert path.exists()


class TestWorkspacePath:
    """Tests for workspace path handling."""

    def test_workspace_path_resolved_correctly(self):
        """Test that workspace path is converted to string and expanded."""
        settings = Settings(
            llm_api_key="test-key",
            llm_model="gpt-4o",
        )
        workspace = Path.home() / "my_workspace"

        config = build_nanobot_config(settings, "gpt-4o", workspace)

        assert config["agents"]["defaults"]["workspace"] == str(workspace)
        assert "~" not in config["agents"]["defaults"]["workspace"]
