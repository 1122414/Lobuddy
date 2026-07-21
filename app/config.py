"""Configuration management for Lobuddy."""

import logging
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
    "task_retry_max_attempts": "TASK_RETRY_MAX_ATTEMPTS",
    "task_estimation_history_size": "TASK_ESTIMATION_HISTORY_SIZE",
    "app_name": "APP_NAME",
    "data_dir": "DATA_DIR",
    "logs_dir": "LOGS_DIR",
    "log_level": "LOG_LEVEL",
    "shell_enabled": "SHELL_ENABLED",
    "guardrails_enabled": "GUARDRAILS_ENABLED",
    "user_name": "USER_NAME",
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
    # Active Observation & Companion Presence
    "observation_enabled": "OBSERVATION_ENABLED",
    "observation_active_app_enabled": "OBSERVATION_ACTIVE_APP_ENABLED",
    "observation_interval_seconds": "OBSERVATION_INTERVAL_SECONDS",
    "proactive_companion_enabled": "PROACTIVE_COMPANION_ENABLED",
    "companion_min_intervention_interval_minutes": ("COMPANION_MIN_INTERVENTION_INTERVAL_MINUTES"),
    "companion_max_interventions_per_day": "COMPANION_MAX_INTERVENTIONS_PER_DAY",
    "companion_work_streak_minutes": "COMPANION_WORK_STREAK_MINUTES",
    "companion_return_idle_minutes": "COMPANION_RETURN_IDLE_MINUTES",
    "companion_activity_reset_idle_minutes": "COMPANION_ACTIVITY_RESET_IDLE_MINUTES",
    "companion_quiet_start_hour": "COMPANION_QUIET_START_HOUR",
    "companion_quiet_end_hour": "COMPANION_QUIET_END_HOUR",
    "companion_late_night_hour": "COMPANION_LATE_NIGHT_HOUR",
    "companion_failure_support_threshold": "COMPANION_FAILURE_SUPPORT_THRESHOLD",
    "companion_feedback_snooze_minutes": "COMPANION_FEEDBACK_SNOOZE_MINUTES",
    "companion_checkin_duration_minutes": "COMPANION_CHECKIN_DURATION_MINUTES",
    # Memory Profile
    "memory_profile_enabled": "MEMORY_PROFILE_ENABLED",
    "memory_profile_file": "MEMORY_PROFILE_FILE",
    "memory_profile_inject_enabled": "MEMORY_PROFILE_INJECT_ENABLED",
    "memory_profile_max_inject_chars": "MEMORY_PROFILE_MAX_INJECT_CHARS",
    "memory_profile_update_every_n_user_messages": "MEMORY_PROFILE_UPDATE_EVERY_N_USER_MESSAGES",
    "memory_profile_update_on_session_end": "MEMORY_PROFILE_UPDATE_ON_SESSION_END",
    "memory_profile_update_on_strong_signal": "MEMORY_PROFILE_UPDATE_ON_STRONG_SIGNAL",
    "memory_profile_daily_consolidation": "MEMORY_PROFILE_DAILY_CONSOLIDATION",
    "memory_profile_max_recent_messages": "MEMORY_PROFILE_MAX_RECENT_MESSAGES",
    "memory_profile_max_patch_items": "MEMORY_PROFILE_MAX_PATCH_ITEMS",
    "memory_profile_require_high_confidence": "MEMORY_PROFILE_REQUIRE_HIGH_CONFIDENCE",
    "memory_profile_min_confidence": "MEMORY_PROFILE_MIN_CONFIDENCE",
    "memory_profile_show_update_notice": "MEMORY_PROFILE_SHOW_UPDATE_NOTICE",
    "exit_analysis_enabled": "EXIT_ANALYSIS_ENABLED",
    "exit_analysis_min_messages": "EXIT_ANALYSIS_MIN_MESSAGES",
    "memory_update_every_n_user_messages": "MEMORY_UPDATE_EVERY_N_USER_MESSAGES",
    "memory_update_on_strong_signal": "MEMORY_UPDATE_ON_STRONG_SIGNAL",
    "memory_update_max_recent_messages": "MEMORY_UPDATE_MAX_RECENT_MESSAGES",
    "memory_update_max_patch_items": "MEMORY_UPDATE_MAX_PATCH_ITEMS",
    "memory_min_confidence": "MEMORY_MIN_CONFIDENCE",
    # Focus Mode
    "focus_mode_enabled": "FOCUS_MODE_ENABLED",
    "focus_default_minutes": "FOCUS_DEFAULT_MINUTES",
    "focus_break_minutes": "FOCUS_BREAK_MINUTES",
    "focus_end_reminder_enabled": "FOCUS_END_REMINDER_ENABLED",
    "focus_break_end_reminder_enabled": "FOCUS_BREAK_END_REMINDER_ENABLED",
    "focus_mute_greeting": "FOCUS_MUTE_GREETING",
    "focus_status_text": "FOCUS_STATUS_TEXT",
    "focus_auto_loop": "FOCUS_AUTO_LOOP",
    # Skill Panel
    "skill_panel_enabled": "SKILL_PANEL_ENABLED",
    "skill_panel_show_examples": "SKILL_PANEL_SHOW_EXAMPLES",
    "skill_panel_click_to_fill_input": "SKILL_PANEL_CLICK_TO_FILL_INPUT",
    "skill_panel_show_permission_badge": "SKILL_PANEL_SHOW_PERMISSION_BADGE",
    # Reserved
    "message_highlight_enabled": "MESSAGE_HIGHLIGHT_ENABLED",
    "memory_card_enabled": "MEMORY_CARD_ENABLED",
    "memory_use_fts5": "MEMORY_USE_FTS5",
    "memory_prompt_budget_chars": "MEMORY_PROMPT_BUDGET_CHARS",
    "memory_prompt_budget_min_chars": "MEMORY_PROMPT_BUDGET_MIN_CHARS",
    "memory_prompt_budget_percent": "MEMORY_PROMPT_BUDGET_PERCENT",
    "memory_system_profile_file": "MEMORY_SYSTEM_PROFILE_FILE",
    "memory_project_profile_file": "MEMORY_PROJECT_PROFILE_FILE",
    "memory_max_episodic_results": "MEMORY_MAX_EPISODIC_RESULTS",
    "memory_recall_min_score": "MEMORY_RECALL_MIN_SCORE",
    "memory_summary_trigger_turns": "MEMORY_SUMMARY_TRIGGER_TURNS",
    "memory_summary_max_chars": "MEMORY_SUMMARY_MAX_CHARS",
    "memory_enable_migration": "MEMORY_ENABLE_MIGRATION",
    "skill_auto_candidate_enabled": "SKILL_AUTO_CANDIDATE_ENABLED",
    "skill_candidate_min_tools_used": "SKILL_CANDIDATE_MIN_TOOLS_USED",
    "skill_candidate_auto_approve_threshold": "SKILL_CANDIDATE_AUTO_APPROVE_THRESHOLD",
    "skill_maintenance_interval_hours": "SKILL_MAINTENANCE_INTERVAL_HOURS",
    "skill_stale_review_days": "SKILL_STALE_REVIEW_DAYS",
    "skill_stale_disable_days": "SKILL_STALE_DISABLE_DAYS",
    "skill_max_file_lines": "SKILL_MAX_FILE_LINES",
    "skill_failure_rate_threshold": "SKILL_FAILURE_RATE_THRESHOLD",
    "skill_failure_rate_min_uses": "SKILL_FAILURE_RATE_MIN_USES",
    "skill_lab_enabled": "SKILL_LAB_ENABLED",
    "skill_candidate_review_enabled": "SKILL_CANDIDATE_REVIEW_ENABLED",
    "skill_validation_enabled": "SKILL_VALIDATION_ENABLED",
    "skill_evaluation_enabled": "SKILL_EVALUATION_ENABLED",
    "skill_evaluation_min_score": "SKILL_EVALUATION_MIN_SCORE",
    "skill_allow_delete": "SKILL_ALLOW_DELETE",
    "skill_candidate_min_confidence": "SKILL_CANDIDATE_MIN_CONFIDENCE",
    "skill_max_test_examples": "SKILL_MAX_TEST_EXAMPLES",
    "history_max_turns": "HISTORY_MAX_TURNS",
    "history_compress_threshold": "HISTORY_COMPRESS_THRESHOLD",
    "history_compress_prompt": "HISTORY_COMPRESS_PROMPT",
    "user_themes_max_count": "USER_THEMES_MAX_COUNT",
    "active_user_theme_id": "ACTIVE_USER_THEME_ID",
    # Memory System 5.3
    "memory_session_search_enabled": "MEMORY_SESSION_SEARCH_ENABLED",
    "memory_session_search_default_scope": "MEMORY_SESSION_SEARCH_DEFAULT_SCOPE",
    "memory_session_search_max_result_chars": "MEMORY_SESSION_SEARCH_MAX_RESULT_CHARS",
    "memory_session_search_total_budget_chars": "MEMORY_SESSION_SEARCH_TOTAL_BUDGET_CHARS",
    "memory_gateway_min_confidence": "MEMORY_GATEWAY_MIN_CONFIDENCE",
    "memory_gateway_max_items_per_patch": "MEMORY_GATEWAY_MAX_ITEMS_PER_PATCH",
    "memory_hot_user_profile_tokens": "MEMORY_HOT_USER_PROFILE_TOKENS",
    "memory_hot_system_profile_tokens": "MEMORY_HOT_SYSTEM_PROFILE_TOKENS",
    "memory_hot_project_context_tokens": "MEMORY_HOT_PROJECT_CONTEXT_TOKENS",
    "memory_lint_enabled": "MEMORY_LINT_ENABLED",
    "memory_lint_duplicate_similarity": "MEMORY_LINT_DUPLICATE_SIMILARITY",
    "memory_lint_stale_days": "MEMORY_LINT_STALE_DAYS",
    "memory_lint_low_confidence_days": "MEMORY_LINT_LOW_CONFIDENCE_DAYS",
    "memory_block_dream_commands": "MEMORY_BLOCK_DREAM_COMMANDS",
    # Execution Governance 5.4
    "execution_governance_enabled": "EXECUTION_GOVERNANCE_ENABLED",
    "execution_local_tools_enabled": "EXECUTION_LOCAL_TOOLS_ENABLED",
    "execution_max_tool_calls_per_task": "EXECUTION_MAX_TOOL_CALLS_PER_TASK",
    "execution_max_local_lookup_calls": "EXECUTION_MAX_LOCAL_LOOKUP_CALLS",
    "execution_max_shell_calls_per_task": "EXECUTION_MAX_SHELL_CALLS_PER_TASK",
    "execution_block_shell_for_local_open": "EXECUTION_BLOCK_SHELL_FOR_LOCAL_OPEN",
    "execution_max_tool_result_chars": "EXECUTION_MAX_TOOL_RESULT_CHARS",
    "execution_trace_enabled": "EXECUTION_TRACE_ENABLED",
    # Recoverable Computer Use
    "computer_use_enabled": "COMPUTER_USE_ENABLED",
    "computer_use_max_actions_per_plan": "COMPUTER_USE_MAX_ACTIONS_PER_PLAN",
    "computer_use_max_tool_calls_per_task": "COMPUTER_USE_MAX_TOOL_CALLS_PER_TASK",
    "computer_use_authorization_minutes": "COMPUTER_USE_AUTHORIZATION_MINUTES",
    "computer_use_action_delay_ms": "COMPUTER_USE_ACTION_DELAY_MS",
    "computer_use_observation_ttl_seconds": "COMPUTER_USE_OBSERVATION_TTL_SECONDS",
    "computer_use_high_impact_confirmation": "COMPUTER_USE_HIGH_IMPACT_CONFIRMATION",
    # Screen Region Ask
    "screen_region_enabled": "SCREEN_REGION_ENABLED",
    "screen_region_ttl_seconds": "SCREEN_REGION_TTL_SECONDS",
    "screen_region_min_size_px": "SCREEN_REGION_MIN_SIZE_PX",
    "screen_region_max_pixels": "SCREEN_REGION_MAX_PIXELS",
    # HITL Approval 5.5
    "hitl_approval_timeout_seconds": "HITL_APPROVAL_TIMEOUT_SECONDS",
    # Maintenance Scheduler 5.8
    "maintenance_start_delay_seconds": "MAINTENANCE_START_DELAY_SECONDS",
    "maintenance_poll_interval_seconds": "MAINTENANCE_POLL_INTERVAL_SECONDS",
    "maintenance_memory_cleanup_interval_seconds": "MAINTENANCE_MEMORY_CLEANUP_INTERVAL_SECONDS",
    "maintenance_skill_review_interval_seconds": "MAINTENANCE_SKILL_REVIEW_INTERVAL_SECONDS",
    "maintenance_trace_cleanup_interval_seconds": "MAINTENANCE_TRACE_CLEANUP_INTERVAL_SECONDS",
    "maintenance_asset_cache_cleanup_interval_seconds": (
        "MAINTENANCE_ASSET_CACHE_CLEANUP_INTERVAL_SECONDS"
    ),
    # Observability 5.8
    "observability_max_traces": "OBSERVABILITY_MAX_TRACES",
    "observability_max_hitl_records": "OBSERVABILITY_MAX_HITL_RECORDS",
    "observability_max_token_sessions": "OBSERVABILITY_MAX_TOKEN_SESSIONS",
    "memory_console_enabled": "MEMORY_CONSOLE_ENABLED",
    "memory_console_show_sensitive_content": "MEMORY_CONSOLE_SHOW_SENSITIVE_CONTENT",
    "memory_console_items_per_page": "MEMORY_CONSOLE_ITEMS_PER_PAGE",
    "privacy_mode_enabled": "PRIVACY_MODE_ENABLED",
    "privacy_mode_allow_chat_history": "PRIVACY_MODE_ALLOW_CHAT_HISTORY",
    "privacy_mode_show_indicator": "PRIVACY_MODE_SHOW_INDICATOR",
    "memory_conflict_detection_enabled": "MEMORY_CONFLICT_DETECTION_ENABLED",
    "memory_conflict_auto_resolve_threshold": "MEMORY_CONFLICT_AUTO_RESOLVE_THRESHOLD",
    "memory_conflict_identity_keys": "MEMORY_CONFLICT_IDENTITY_KEYS",
}

_BOOL_TRUE_VALUES = {"true", "1", "yes", "on"}
_BOOL_FALSE_VALUES = {"false", "0", "no", "off"}


def get_settings() -> Settings:
    """Get or create settings singleton.

    Priority (high to low):
    1. Database overrides (runtime user changes via UI)
    2. Process environment / project .env file
    3. Model defaults

    Safety guardrails are a runtime invariant. A legacy setting may still be
    read for backwards compatibility, but the production composition root
    never starts an unrestricted tool executor.
    """
    global _settings
    if _settings is None:
        _settings = Settings(  # type: ignore[call-arg]
            _env_file=".env",
            _env_file_encoding="utf-8",
        )
        _settings = apply_db_overrides(_settings)
        _settings = enforce_runtime_invariants(_settings)
    return _settings


def enforce_runtime_invariants(settings: Settings) -> Settings:
    """Apply non-negotiable production safety invariants."""
    if settings.guardrails_enabled:
        return settings
    logger.warning(
        "GUARDRAILS_ENABLED=false is no longer honored at runtime; "
        "tool argument guardrails remain enabled"
    )
    if hasattr(settings, "model_copy"):
        return settings.model_copy(update={"guardrails_enabled": True})
    return settings.copy(update={"guardrails_enabled": True})


def apply_db_overrides(settings: Settings) -> Settings:
    """Apply database settings overrides to a Settings instance."""
    try:
        from core.storage.db import Database
        from core.storage.settings_repo import SettingsRepository

        # Settings are loaded before the composition root initializes the global
        # database. Read an existing database explicitly so startup does not rely
        # on hidden global state or create an empty database on first launch.
        db_path = settings.data_dir / "lobuddy.db"
        if not db_path.is_file():
            return settings

        repo = SettingsRepository(Database(settings))
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
            if hasattr(settings, "model_copy"):
                return settings.model_copy(update=overrides)
            return settings.copy(update=overrides)
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
    if isinstance(current, float):
        return float(value)
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
