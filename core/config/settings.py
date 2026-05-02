"""Core settings model for Lobuddy."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # LLM Configuration (OpenAI compatible)
    llm_api_key: str = Field(..., description="API key for LLM service")
    llm_base_url: str = Field(
        default="https://api.openai.com/v1", description="Base URL for LLM API"
    )
    llm_model: str = Field(default="gpt-4o-mini", description="Model name to use")
    llm_multimodal_model: str = Field(
        default="",
        description="Model name for multimodal tasks (images). Required for image analysis; if empty, image tasks will be rejected.",
    )
    llm_multimodal_base_url: str | None = Field(
        default=None,
        description="Base URL for multimodal API. Falls back to llm_base_url if not set.",
    )
    llm_multimodal_api_key: str | None = Field(
        default=None,
        description="API key for multimodal service. Falls back to llm_api_key if not set.",
    )
    # Nanobot Configuration
    nanobot_config_path: Path = Field(
        default=Path.home() / ".nanobot" / "config.json", description="Path to nanobot config file"
    )
    workspace_path: Path = Field(
        default=Path("./workspace"), description="Workspace directory for nanobot"
    )
    nanobot_max_iterations: int = Field(
        default=40, gt=0, description="Maximum iterations for nanobot tasks"
    )
    task_timeout: int = Field(default=120, gt=0, description="Task execution timeout in seconds")

    # Application Configuration
    app_name: str = Field(default="Lobuddy", description="Application name")
    data_dir: Path = Field(default=Path("./data"), description="Data directory for persistence")
    logs_dir: Path = Field(default=Path("./logs"), description="Logs directory")
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    # Security Configuration
    shell_enabled: bool = Field(default=True, description="Enable shell/exec tool (dangerous)")
    guardrails_enabled: bool = Field(
        default=True,
        description="Enable safety guardrails for tool execution (path/shell/URL validation)",
    )

    # UI Configuration
    pet_name: str = Field(default="Lobuddy", description="Pet display name")
    pet_exp_bar_enabled: bool = Field(default=True, description="Show EXP bar on pet widget")

    # Theme Configuration
    theme_preset: str = Field(
        default="cozy_orange",
        description="Theme preset: cozy_orange, sakura_pink, mint_green, night_companion, custom",
    )
    theme_primary_color: str = Field(
        default="", description="Custom primary color override (empty = use preset)"
    )
    theme_background_color: str = Field(
        default="", description="Custom background color override (empty = use preset)"
    )
    theme_accent_color: str = Field(
        default="", description="Custom accent color override (empty = use preset)"
    )
    active_user_theme_id: str = Field(
        default="", description="Active user theme ID (empty = use preset)"
    )

    # Pet Avatar Configuration
    pet_avatar_animation_enabled: bool = Field(
        default=True, description="Enable pet avatar animations"
    )

    # Companion Configuration
    companion_greeting_enabled: bool = Field(
        default=True, description="Enable proactive greeting messages"
    )

    # Pet Click Feedback
    pet_click_feedback_enabled: bool = Field(
        default=True, description="Enable pet click feedback animation and bubbles"
    )
    pet_click_cooldown_ms: int = Field(
        default=350, description="Cooldown between pet click feedback (ms)"
    )
    pet_click_easter_egg_count: int = Field(
        default=5, description="Consecutive clicks to trigger easter egg"
    )
    pet_click_messages: str = Field(
        default="我在呢～|今天也辛苦啦！|摸摸头成功！|要不要休息一下？|我会陪着你的～",
        description="Pet click feedback messages, separated by |"
    )
    pet_click_easter_egg_message: str = Field(
        default="别戳啦，会害羞的！", description="Easter egg message after rapid clicks"
    )
    pet_bubble_duration_ms: int = Field(
        default=2200, description="Pet bubble display duration (ms)"
    )

    # Pet Clock
    pet_clock_enabled: bool = Field(
        default=True, description="Show clock on pet widget"
    )
    pet_clock_show_seconds: bool = Field(
        default=False, description="Show seconds on pet clock"
    )
    pet_clock_refresh_ms: int = Field(
        default=30000, description="Pet clock refresh interval (ms)"
    )
    pet_clock_hover_full_format: bool = Field(
        default=True, description="Show full datetime on hover"
    )

    # Chat Message Time
    chat_message_time_enabled: bool = Field(
        default=True, description="Show timestamp on chat messages"
    )
    chat_time_divider_enabled: bool = Field(
        default=True, description="Show time dividers between message groups"
    )
    chat_time_divider_gap_minutes: int = Field(
        default=5, description="Minute gap to insert time divider"
    )
    chat_time_format: str = Field(
        default="HH:mm", description="Time format for chat messages"
    )
    chat_date_format: str = Field(
        default="yyyy年M月d日 dddd", description="Date format for time dividers"
    )

    # Conversation Timeline
    conversation_timeline_enabled: bool = Field(
        default=True, description="Show right-side conversation timeline"
    )
    conversation_timeline_tooltip_enabled: bool = Field(
        default=True, description="Show tooltip on timeline dots"
    )
    conversation_timeline_preview_max_chars: int = Field(
        default=32, description="Max chars in timeline preview"
    )
    conversation_timeline_min_dot_gap_px: int = Field(
        default=8, description="Min pixel gap between timeline dots"
    )

    # Pet State System
    pet_state_enabled: bool = Field(
        default=True, description="Enable pet state system"
    )
    pet_idle_after_minutes: int = Field(
        default=10, description="Minutes of inactivity before Idle state"
    )
    pet_sleepy_start_hour: int = Field(
        default=23, description="Hour to start Sleepy state"
    )
    pet_sleepy_end_hour: int = Field(
        default=6, description="Hour to end Sleepy state"
    )
    pet_state_text_idle: str = Field(default="待机中", description="Idle state text")
    pet_state_text_listening: str = Field(default="倾听中", description="Listening state text")
    pet_state_text_thinking: str = Field(default="思考中", description="Thinking state text")
    pet_state_text_working: str = Field(default="工作中", description="Working state text")
    pet_state_text_happy: str = Field(default="开心", description="Happy state text")
    pet_state_text_sleepy: str = Field(default="困困", description="Sleepy state text")
    pet_state_text_error: str = Field(default="需要看看", description="Error state text")

    # Daily Greeting
    daily_greeting_enabled: bool = Field(
        default=False, description="Enable daily greeting on startup"
    )
    daily_greeting_max_per_day: int = Field(
        default=1, description="Max daily greetings"
    )
    greeting_morning: str = Field(
        default="早上好，今天也一起加油～", description="Morning greeting"
    )
    greeting_afternoon: str = Field(
        default="下午好，要不要喝口水？", description="Afternoon greeting"
    )
    greeting_evening: str = Field(
        default="晚上好，今天辛苦啦。", description="Evening greeting"
    )
    greeting_night: str = Field(
        default="已经很晚啦，注意休息哦。", description="Night greeting"
    )

    # ==================== Memory Profile ====================
    memory_profile_enabled: bool = Field(
        default=True, description="Enable AI-maintained user profile memory"
    )
    memory_profile_file: Path = Field(
        default=Path("data/memory/USER.md"),
        description="Path to user profile file",
    )
    memory_profile_inject_enabled: bool = Field(
        default=True, description="Inject compact profile context into AI prompts"
    )
    memory_profile_max_inject_chars: int = Field(
        default=2000, gt=0, description="Max characters for profile injection"
    )
    memory_profile_update_every_n_user_messages: int = Field(
        default=6, gt=0, description="Update profile every N user messages"
    )
    memory_profile_update_on_session_end: bool = Field(
        default=True, description="Update profile when session ends"
    )
    memory_profile_update_on_strong_signal: bool = Field(
        default=True, description="Update profile on strong memory signals"
    )
    memory_profile_daily_consolidation: bool = Field(
        default=False, description="Enable daily profile consolidation"
    )
    memory_profile_max_recent_messages: int = Field(
        default=30, gt=0, description="Max recent messages for context"
    )
    memory_profile_max_patch_items: int = Field(
        default=8, gt=0, description="Max items per profile patch"
    )
    memory_profile_require_high_confidence: bool = Field(
        default=True, description="Require high confidence for profile updates"
    )
    memory_profile_min_confidence: float = Field(
        default=0.75, ge=0.0, le=1.0, description="Minimum confidence threshold"
    )
    memory_profile_show_update_notice: bool = Field(
        default=True, description="Show notice when profile is updated"
    )

    # ==================== Focus Mode ====================
    focus_mode_enabled: bool = Field(
        default=False, description="Enable focus companion mode"
    )
    focus_default_minutes: int = Field(
        default=25, gt=0, description="Default focus duration (minutes)"
    )
    focus_break_minutes: int = Field(
        default=5, gt=0, description="Default break duration (minutes)"
    )
    focus_end_reminder_enabled: bool = Field(
        default=True, description="Remind when focus session ends"
    )
    focus_break_end_reminder_enabled: bool = Field(
        default=True, description="Remind when break ends"
    )
    focus_mute_greeting: bool = Field(
        default=True, description="Mute greeting during focus mode"
    )
    focus_status_text: str = Field(
        default="Focusing", description="Status text during focus mode"
    )
    focus_auto_loop: bool = Field(
        default=False, description="Auto-start next focus after break"
    )

    # ==================== Skill Panel ====================
    skill_panel_enabled: bool = Field(
        default=True, description="Enable skill panel feature"
    )
    skill_panel_show_examples: bool = Field(
        default=True, description="Show example prompts in skill panel"
    )
    skill_panel_click_to_fill_input: bool = Field(
        default=True, description="Click skill example to fill input box"
    )
    skill_panel_show_permission_badge: bool = Field(
        default=True, description="Show permission badges on skills"
    )

    user_themes_max_count: int = Field(
        default=20, ge=1, le=100, description="Maximum number of user themes"
    )

    # Message Highlight (reserved)
    message_highlight_enabled: bool = Field(
        default=False, description="Enable message bookmarking (reserved)"
    )

    # Memory Card (reserved)
    memory_card_enabled: bool = Field(
        default=False, description="Enable memory cards (reserved)"
    )

    memory_use_fts5: bool = Field(
        default=True, description="Enable FTS5 for memory search if available"
    )
    memory_prompt_budget_chars: int = Field(
        default=4000, gt=0, description="Max characters for memory injection into prompts"
    )
    memory_prompt_budget_percent: float = Field(
        default=0.20, ge=0.0, le=1.0, description="Max percent of prompt for memory injection"
    )
    memory_system_profile_file: Path = Field(
        default=Path("data/memory/SYSTEM.md"),
        description="Path to system profile projection file",
    )
    memory_project_profile_file: Path = Field(
        default=Path("data/memory/PROJECT.md"),
        description="Path to project memory projection file",
    )
    memory_max_episodic_results: int = Field(
        default=5, gt=0, description="Max episodic memory results per retrieval"
    )
    memory_summary_trigger_turns: int = Field(
        default=10, gt=0, description="Conversation turns before generating summary"
    )
    memory_summary_max_chars: int = Field(
        default=2000, gt=0, description="Max chars for conversation summary"
    )
    memory_enable_migration: bool = Field(
        default=True, description="Enable automatic migration from old USER.md"
    )

    skill_auto_candidate_enabled: bool = Field(
        default=False, description="Enable automatic skill candidate generation"
    )
    skill_candidate_min_tools_used: int = Field(
        default=2, ge=0, description="Min tool calls to trigger candidate extraction"
    )
    skill_candidate_auto_approve_threshold: float = Field(
        default=0.9, ge=0.0, le=1.0, description="Confidence threshold for auto-approving skill candidates"
    )
    skill_maintenance_interval_hours: int = Field(
        default=24, gt=0, description="Maintenance scheduler interval in hours"
    )
    skill_stale_disable_days: int = Field(
        default=90, gt=0, description="Days of inactivity before auto-disabling skill"
    )
    skill_stale_review_days: int = Field(
        default=60, gt=0, description="Days of inactivity before marking skill for review"
    )
    skill_max_file_lines: int = Field(
        default=500, gt=0, description="Max lines for a skill file before requiring split"
    )
    skill_failure_rate_threshold: float = Field(
        default=0.40, ge=0.0, le=1.0, description="Failure rate threshold for skill review"
    )
    skill_failure_rate_min_uses: int = Field(
        default=5, gt=0, description="Min uses before failure rate review"
    )
    skill_archive_dir: Path = Field(
        default=Path("data/skills/archive"),
        description="Directory for archived skills",
    )

    # Conversation History Configuration
    history_max_turns: int = Field(
        default=10, gt=0, description="Maximum conversation turns before compression"
    )
    history_compress_threshold: int = Field(
        default=5, gt=0, description="Number of oldest turns to compress"
    )
    history_compress_prompt: str = Field(
        default="Summarize the following conversation concisely, preserving key context and decisions.",
        description="Prompt used for history compression",
    )

    @field_validator("workspace_path", "data_dir", "logs_dir", mode="before")
    @classmethod
    def convert_to_path(cls, v: str | Path) -> Path:
        path = Path(v) if isinstance(v, str) else v
        return path.expanduser()

    @field_validator("nanobot_config_path", mode="before")
    @classmethod
    def expand_nanobot_path(cls, v: str | Path) -> Path:
        """Expand user home directory in path."""
        path = Path(v) if isinstance(v, str) else v
        return path.expanduser()
