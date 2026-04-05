"""Nanobot adapter for Lobuddy."""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.config import Settings


class AgentResult(BaseModel):
    """Result of an agent task execution."""

    success: bool
    raw_output: str
    summary: str
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime


class NanobotAdapter:
    """Adapter for nanobot agent integration.

    This is the ONLY entry point for Lobuddy to interact with nanobot.
    All nanobot calls must go through this adapter.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._bot: Any | None = None
        self._config_path: Path | None = None

    async def health_check(self) -> bool:
        """Check if nanobot is properly configured and can initialize.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            # Check if we can create a temporary config
            config_path = self._create_temp_config()
            if not config_path.exists():
                return False

            # Try to import and initialize nanobot
            from nanobot import Nanobot

            bot = Nanobot.from_config(
                config_path=config_path,
                workspace=self.settings.workspace_path,
            )

            # Try a simple health check by checking if the loop is ready
            if bot._loop is None:
                return False

            return True

        except Exception as e:
            print(f"Health check failed: {e}")
            return False

    async def run_task(self, prompt: str, session_key: str) -> AgentResult:
        """Run a task through nanobot.

        Args:
            prompt: The user prompt to execute.
            session_key: Session identifier for conversation isolation.

        Returns:
            AgentResult with execution details.
        """
        started_at = datetime.now()

        try:
            from nanobot import Nanobot

            # Create or reuse config
            config_path = self._ensure_config()

            # Initialize nanobot
            bot = Nanobot.from_config(
                config_path=config_path,
                workspace=self.settings.workspace_path,
            )

            # Run the task with timeout
            result = await asyncio.wait_for(
                bot.run(prompt, session_key=session_key),
                timeout=self.settings.task_timeout,
            )

            finished_at = datetime.now()

            # Generate summary (truncate if too long)
            raw_output = result.content or ""
            summary = self._generate_summary(raw_output)

            return AgentResult(
                success=True,
                raw_output=raw_output,
                summary=summary,
                error_message=None,
                started_at=started_at,
                finished_at=finished_at,
            )

        except asyncio.TimeoutError:
            finished_at = datetime.now()
            return AgentResult(
                success=False,
                raw_output="",
                summary="Task timed out",
                error_message=f"Task exceeded {self.settings.task_timeout} seconds timeout",
                started_at=started_at,
                finished_at=finished_at,
            )

        except Exception as e:
            finished_at = datetime.now()
            return AgentResult(
                success=False,
                raw_output="",
                summary="Task failed",
                error_message=str(e),
                started_at=started_at,
                finished_at=finished_at,
            )

    def build_session_key(self, task_id: str) -> str:
        """Build a unique session key for a task.

        Args:
            task_id: The task identifier.

        Returns:
            Session key string.
        """
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"lobuddy:{task_id}:{timestamp}"

    def _create_temp_config(self) -> Path:
        """Create a temporary nanobot config file."""
        config = {
            "providers": {
                "custom": {
                    "apiKey": self.settings.llm_api_key,
                    "apiBase": self.settings.llm_base_url,
                }
            },
            "agents": {
                "defaults": {
                    "provider": "custom",
                    "model": self.settings.llm_model,
                    "maxToolIterations": self.settings.nanobot_max_iterations,
                }
            },
        }

        # Use a temporary file
        temp_dir = Path(tempfile.gettempdir()) / "lobuddy"
        temp_dir.mkdir(exist_ok=True)
        config_path = temp_dir / "nanobot_config.json"

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        return config_path

    def _ensure_config(self) -> Path:
        """Ensure nanobot config exists and return its path."""
        # Always create a fresh temp config to ensure settings are up to date
        return self._create_temp_config()

    def _generate_summary(self, raw_output: str, max_length: int = 200) -> str:
        """Generate a summary from raw output.

        Args:
            raw_output: The full output from nanobot.
            max_length: Maximum length for summary.

        Returns:
            Truncated summary.
        """
        if not raw_output:
            return "No output"

        # Take first max_length characters
        if len(raw_output) <= max_length:
            return raw_output

        # Try to break at a sentence boundary
        truncated = raw_output[:max_length]
        last_period = truncated.rfind(".")
        last_newline = truncated.rfind("\n")

        # Prefer breaking at newline, then period
        break_point = max(last_newline, last_period)
        if break_point > max_length * 0.7:  # Only use if it's not too short
            return truncated[: break_point + 1] + "..."

        return truncated + "..."
