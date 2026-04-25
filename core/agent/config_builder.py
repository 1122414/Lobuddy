"""Nanobot config builder utilities."""

import json
import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from core.config import Settings

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
            "restrictToWorkspace": False,
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
    fd, temp_path = tempfile.mkstemp(
        suffix=f"_{label}.json",
        prefix="nanobot_config_",
        dir=config_dir,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            FILE_ALL_ACCESS = 0x1F01FF
            FILE_GENERIC_READ = 0x80000000
            FILE_GENERIC_WRITE = 0x40000000
            DACL_SECURITY_INFORMATION = 0x00000004
            SE_FILE_OBJECT = 1

            def set_windows_acl(path_str: str) -> None:
                advapi32 = ctypes.windll.advapi32
                kernel32 = ctypes.windll.kernel32

                # Get current user SID
                token = kernel32.GetCurrentProcess()
                sid = ctypes.create_unicode_buffer(256)
                cb_sid = wintypes.DWORD(256)
                domain = ctypes.create_unicode_buffer(256)
                cb_domain = wintypes.DWORD(256)
                snu = wintypes.DWORD()

                # Simplified: use icacls command as fallback
                import subprocess
                subprocess.run(
                    ["icacls", path_str, "/inheritance:r", "/grant:r", f"{os.getlogin()}:F"],
                    check=True,
                    capture_output=True,
                )

            try:
                set_windows_acl(temp_path)
            except Exception as e:
                logger.error(f"Windows ACL setup failed: {e}")
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                raise RuntimeError(
                    f"Failed to restrict temp config permissions on Windows: {e}"
                ) from e
        else:
            os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)

        return Path(temp_path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
