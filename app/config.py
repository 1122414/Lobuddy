"""Configuration management for Lobuddy."""

import logging
import os
from pathlib import Path
from typing import Optional

from core.config import Settings

logger = logging.getLogger(__name__)


_settings: Optional[Settings] = None

# Mapping between Settings field names and .env variable names
_ENV_VAR_MAP = {
    "llm_api_key": "LLM_API_KEY",
    "llm_base_url": "LLM_BASE_URL",
    "llm_model": "LLM_MODEL",
    "llm_multimodal_model": "LLM_MULTIMODAL_MODEL",
    "llm_multimodal_base_url": "LLM_MULTIMODAL_BASE_URL",
    "llm_multimodal_api_key": "LLM_MULTIMODAL_API_KEY",
    "task_timeout": "TASK_TIMEOUT",
    "shell_enabled": "ENABLE_SHELL_TOOL",
    "pet_name": "PET_NAME",
}


def get_settings() -> Settings:
    """Get or create settings singleton.

    Priority (high to low):
    1. Environment variables / .env file (Pydantic Settings)
    2. Database overrides (runtime user changes via UI)
    3. Default values

    This means DB settings override env defaults, but env vars
    take precedence on first load if no DB value exists.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings = apply_db_overrides(_settings)
    return _settings


def apply_db_overrides(settings: Settings) -> Settings:
    """Apply database settings overrides to a Settings instance."""
    try:
        from core.storage.settings_repo import SettingsRepository

        repo = SettingsRepository()
        overrides = {}

        field_map = {
            "pet_name": "pet_name",
            "llm_api_key": "llm_api_key",
            "llm_base_url": "llm_base_url",
            "llm_model": "llm_model",
            "task_timeout": "task_timeout",
            "shell_enabled": "shell_enabled",
        }

        for db_key, field_name in field_map.items():
            value = repo.get_setting(db_key)
            if value is not None and value.strip() != "":
                current = getattr(settings, field_name)
                if isinstance(current, bool):
                    overrides[field_name] = value.lower() == "true"
                elif isinstance(current, int):
                    overrides[field_name] = int(value)
                else:
                    overrides[field_name] = value

        if overrides:
            return settings.model_copy(update=overrides)
    except Exception as e:
        logger.warning(f"DB overrides failed: {e}")

    return settings


def reload_settings() -> Settings:
    """Reload settings from environment/.env file."""
    global _settings
    _settings = None
    return get_settings()


def save_settings_to_env(settings: Settings) -> None:
    """Save settings back to .env file so they persist across restarts.

    Writes all configured fields to the .env file, preserving comments
    and non-managed variables. Values are saved as plain text (API keys
    are the user's own responsibility in their local .env).
    """
    env_path = Path(".env")
    if not env_path.exists():
        env_path = Path(__file__).parent.parent / ".env"

    # Read existing lines to preserve comments and unmanaged vars
    existing_lines = []
    if env_path.exists():
        try:
            existing_lines = env_path.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            logger.warning(f"Failed to read .env for update: {e}")

    # Track which fields we've written
    managed_keys = set(_ENV_VAR_MAP.values())
    written_keys = set()
    new_lines = []

    # Update existing managed lines
    for line in existing_lines:
        stripped = line.strip()
        # Preserve empty lines and comments
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue

        # Parse KEY=VALUE
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in managed_keys:
                field_name = _env_var_to_field(key)
                if field_name and hasattr(settings, field_name):
                    value = getattr(settings, field_name)
                    if isinstance(value, bool):
                        value = str(value).lower()
                    elif isinstance(value, int):
                        value = str(value)
                    else:
                        value = str(value) if value is not None else ""
                    new_lines.append(f"{key}={value}")
                    written_keys.add(key)
                    continue
        new_lines.append(line)

    # Append any managed fields that weren't in the file
    for field_name, env_var in _ENV_VAR_MAP.items():
        if env_var not in written_keys and hasattr(settings, field_name):
            value = getattr(settings, field_name)
            if value is not None and str(value):
                if isinstance(value, bool):
                    value = str(value).lower()
                elif isinstance(value, int):
                    value = str(value)
                else:
                    value = str(value)
                new_lines.append(f"{env_var}={value}")

    # Write back
    try:
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        logger.info(f"Settings saved to {env_path}")
    except Exception as e:
        logger.error(f"Failed to write .env: {e}")
        raise


def _env_var_to_field(env_var: str) -> Optional[str]:
    """Reverse lookup: env var name -> Settings field name."""
    for field_name, var_name in _ENV_VAR_MAP.items():
        if var_name == env_var:
            return field_name
    return None
