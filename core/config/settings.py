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

    # Focus Mode (reserved)
    focus_mode_enabled: bool = Field(
        default=False, description="Enable focus companion mode (reserved)"
    )
    focus_default_minutes: int = Field(
        default=25, description="Default focus duration (minutes)"
    )
    focus_break_minutes: int = Field(
        default=5, description="Default break duration (minutes)"
    )

    # Message Highlight (reserved)
    message_highlight_enabled: bool = Field(
        default=False, description="Enable message bookmarking (reserved)"
    )

    # Memory Card (reserved)
    memory_card_enabled: bool = Field(
        default=False, description="Enable memory cards (reserved)"
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
