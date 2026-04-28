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
    theme_corner_radius: str = Field(
        default="large", description="Corner radius preset: small, medium, large"
    )

    # Pet Avatar Configuration
    pet_avatar_animation_enabled: bool = Field(
        default=True, description="Enable pet avatar animations"
    )

    # Companion Configuration
    companion_greeting_enabled: bool = Field(
        default=True, description="Enable proactive greeting messages"
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
