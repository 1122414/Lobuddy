"""Nanobot config builder utilities."""

import json
import logging
from pathlib import Path
from typing import Any

from app.config import Settings

logger = logging.getLogger("lobuddy.config_builder")


def build_nanobot_config(settings: Settings, model: str, workspace: Path) -> dict[str, Any]:
    """Build a nanobot config dictionary from settings."""
    config: dict[str, Any] = {
        "providers": {
            "custom": {
                "apiKey": settings.llm_api_key,
            }
        },
        "agents": {
            "defaults": {
                "provider": "custom",
                "model": model,
                "maxToolIterations": settings.nanobot_max_iterations,
                "historyCompressPrompt": settings.history_compress_prompt,
                "workspace": str(workspace),
            }
        },
        "tools": {
            "restrictToWorkspace": True,
            "exec": {
                "enable": settings.shell_enabled,
            },
        },
    }

    if settings.llm_base_url:
        config["providers"]["custom"]["apiBase"] = settings.llm_base_url

    mcp_servers = getattr(settings, "mcp_servers", None)
    if mcp_servers:
        config["mcpServers"] = mcp_servers

    return config


def write_temp_config(config: dict[str, Any], config_dir: Path, label: str) -> Path:
    """Write a nanobot config dict to a temporary JSON file."""
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"nanobot_config_{label}.json"

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    logger.debug(f"Created temp config at {config_path}")
    return config_path
