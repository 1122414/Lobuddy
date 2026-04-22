"""Configuration management for Lobuddy."""

import logging
from typing import Optional

from core.config import Settings

logger = logging.getLogger(__name__)


_settings: Optional[Settings] = None


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
            "result_popup_duration": "result_popup_duration",
            "shell_enabled": "shell_enabled",
        }

        for db_key, field_name in field_map.items():
            value = repo.get_setting(db_key)
            if value is not None:
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
