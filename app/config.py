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
    "nanobot_config_path": "NANOBOT_CONFIG_PATH",
    "workspace_path": "WORKSPACE_PATH",
    "nanobot_max_iterations": "NANOBOT_MAX_ITERATIONS",
    "task_timeout": "TASK_TIMEOUT",
    "app_name": "APP_NAME",
    "data_dir": "DATA_DIR",
    "logs_dir": "LOGS_DIR",
    "log_level": "LOG_LEVEL",
    "shell_enabled": "SHELL_ENABLED",
    "pet_name": "PET_NAME",
    "pet_exp_bar_enabled": "PET_EXP_BAR_ENABLED",
    "theme_preset": "THEME_PRESET",
    "theme_primary_color": "THEME_PRIMARY_COLOR",
    "theme_background_color": "THEME_BACKGROUND_COLOR",
    "theme_accent_color": "THEME_ACCENT_COLOR",
    "pet_avatar_animation_enabled": "PET_AVATAR_ANIMATION_ENABLED",
    "companion_greeting_enabled": "COMPANION_GREETING_ENABLED",
    "pet_click_feedback_enabled": "PET_CLICK_FEEDBACK_ENABLED",
    "pet_click_cooldown_ms": "PET_CLICK_COOLDOWN_MS",
    "pet_click_easter_egg_count": "PET_CLICK_EASTER_EGG_COUNT",
    "pet_click_messages": "PET_CLICK_MESSAGES",
    "pet_click_easter_egg_message": "PET_CLICK_EASTER_EGG_MESSAGE",
    "pet_bubble_duration_ms": "PET_BUBBLE_DURATION_MS",
    "pet_clock_enabled": "PET_CLOCK_ENABLED",
    "pet_clock_show_seconds": "PET_CLOCK_SHOW_SECONDS",
    "pet_clock_refresh_ms": "PET_CLOCK_REFRESH_MS",
    "pet_clock_hover_full_format": "PET_CLOCK_HOVER_FULL_FORMAT",
    "chat_message_time_enabled": "CHAT_MESSAGE_TIME_ENABLED",
    "chat_time_divider_enabled": "CHAT_TIME_DIVIDER_ENABLED",
    "chat_time_divider_gap_minutes": "CHAT_TIME_DIVIDER_GAP_MINUTES",
    "chat_time_format": "CHAT_TIME_FORMAT",
    "chat_date_format": "CHAT_DATE_FORMAT",
    "conversation_timeline_enabled": "CONVERSATION_TIMELINE_ENABLED",
    "conversation_timeline_tooltip_enabled": "CONVERSATION_TIMELINE_TOOLTIP_ENABLED",
    "conversation_timeline_preview_max_chars": "CONVERSATION_TIMELINE_PREVIEW_MAX_CHARS",
    "conversation_timeline_min_dot_gap_px": "CONVERSATION_TIMELINE_MIN_DOT_GAP_PX",
    "pet_state_enabled": "PET_STATE_ENABLED",
    "pet_idle_after_minutes": "PET_IDLE_AFTER_MINUTES",
    "pet_sleepy_start_hour": "PET_SLEEPY_START_HOUR",
    "pet_sleepy_end_hour": "PET_SLEEPY_END_HOUR",
    "pet_state_text_idle": "PET_STATE_TEXT_IDLE",
    "pet_state_text_listening": "PET_STATE_TEXT_LISTENING",
    "pet_state_text_thinking": "PET_STATE_TEXT_THINKING",
    "pet_state_text_working": "PET_STATE_TEXT_WORKING",
    "pet_state_text_happy": "PET_STATE_TEXT_HAPPY",
    "pet_state_text_sleepy": "PET_STATE_TEXT_SLEEPY",
    "pet_state_text_error": "PET_STATE_TEXT_ERROR",
    "daily_greeting_enabled": "DAILY_GREETING_ENABLED",
    "daily_greeting_max_per_day": "DAILY_GREETING_MAX_PER_DAY",
    "greeting_morning": "GREETING_MORNING",
    "greeting_afternoon": "GREETING_AFTERNOON",
    "greeting_evening": "GREETING_EVENING",
    "greeting_night": "GREETING_NIGHT",
    "focus_mode_enabled": "FOCUS_MODE_ENABLED",
    "focus_default_minutes": "FOCUS_DEFAULT_MINUTES",
    "focus_break_minutes": "FOCUS_BREAK_MINUTES",
    "message_highlight_enabled": "MESSAGE_HIGHLIGHT_ENABLED",
    "memory_card_enabled": "MEMORY_CARD_ENABLED",
    "history_max_turns": "HISTORY_MAX_TURNS",
    "history_compress_threshold": "HISTORY_COMPRESS_THRESHOLD",
    "history_compress_prompt": "HISTORY_COMPRESS_PROMPT",
}

_BOOL_TRUE_VALUES = {"true", "1", "yes", "on"}
_BOOL_FALSE_VALUES = {"false", "0", "no", "off"}


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

        field_map = {field_name: field_name for field_name in _ENV_VAR_MAP}

        for db_key, field_name in field_map.items():
            value = repo.get_setting(db_key)
            if value is not None:
                current = getattr(settings, field_name)
                if value.strip() == "" and not isinstance(current, (str, type(None))):
                    continue
                try:
                    overrides[field_name] = _coerce_setting_value(value, current)
                except ValueError as e:
                    logger.warning(f"Skipping invalid DB setting {db_key}: {e}")

        if overrides:
            return settings.model_copy(update=overrides)
    except Exception as e:
        logger.warning(f"DB overrides failed: {e}")

    return settings


def _coerce_setting_value(value: str, current):
    """Coerce SQLite string values to the existing Settings field type."""
    if isinstance(current, bool):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE_VALUES:
            return True
        if normalized in _BOOL_FALSE_VALUES:
            return False
        raise ValueError(f"Invalid bool setting value: {value}")
    if isinstance(current, int):
        return int(value)
    if isinstance(current, Path):
        return Path(value).expanduser()
    return value


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
