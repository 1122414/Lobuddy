"""Configuration management for Lobuddy."""

import os
from pathlib import Path
from typing import Optional

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
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    llm_max_tokens: int = Field(default=4096, gt=0, description="Maximum tokens per response")

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
    result_popup_duration: int = Field(
        default=5, gt=0, description="Result popup display duration in seconds"
    )

    # UI Configuration
    pet_name: str = Field(default="Lobuddy", description="Pet display name")
    show_detailed_logs: bool = Field(
        default=False, description="Whether to show detailed logs in UI"
    )

    @field_validator("workspace_path", "data_dir", "logs_dir", mode="before")
    @classmethod
    def convert_to_path(cls, v: str | Path) -> Path:
        """Convert string to Path object."""
        return Path(v) if isinstance(v, str) else v

    @field_validator("nanobot_config_path", mode="before")
    @classmethod
    def expand_nanobot_path(cls, v: str | Path) -> Path:
        """Expand user home directory in path."""
        path = Path(v) if isinstance(v, str) else v
        return path.expanduser()


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Reload settings from environment/.env file."""
    global _settings
    _settings = Settings()
    return _settings
