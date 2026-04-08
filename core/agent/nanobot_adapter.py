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


class _MessageCaptureHook:
    """Hook to capture message tool calls."""

    def __init__(self):
        self.messages: list[str] = []

    def wants_streaming(self) -> bool:
        return False

    async def before_iteration(self, ctx: Any) -> None:
        pass

    async def on_stream(self, ctx: Any, delta: str) -> None:
        pass

    async def on_stream_end(self, ctx: Any, *, resuming: bool) -> None:
        pass

    async def before_execute_tools(self, ctx: Any) -> None:
        from nanobot.agent.hook import AgentHookContext

        if isinstance(ctx, AgentHookContext):
            for tc in ctx.tool_calls:
                if tc.name == "message" and tc.arguments:
                    args = tc.arguments
                    if isinstance(args, list) and len(args) > 0:
                        args = args[0]
                    if isinstance(args, dict) and "content" in args:
                        self.messages.append(args["content"])

    async def after_iteration(self, ctx: Any) -> None:
        pass

    def finalize_content(self, ctx: Any, content: str | None) -> str | None:
        return content


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
            config_path = self._create_temp_config(None)
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

    async def run_task(
        self,
        prompt: str,
        session_key: str,
        chat_history: list[dict[str, Any]] | None = None,
        pet_state: dict[str, Any] | None = None,
    ) -> AgentResult:
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
            config_path = self._ensure_config(pet_state)

            # Initialize nanobot
            bot = Nanobot.from_config(
                config_path=config_path,
                workspace=self.settings.workspace_path,
            )

            # Inject chat history into nanobot's session if provided
            if chat_history:
                session = bot._loop.sessions.get_or_create(session_key)
                # Only inject if session is empty (to avoid duplicates)
                if not session.messages:
                    for msg in chat_history:
                        session.add_message(
                            role=msg.get("role", "user"),
                            content=msg.get("content", ""),
                        )
                    bot._loop.sessions.save(session)

            # Create hook to capture message tool calls
            capture_hook = _MessageCaptureHook()

            # nanobot manages history via session_key; only pass current prompt
            result = await asyncio.wait_for(
                bot.run(
                    prompt,
                    session_key=session_key,
                    hooks=[capture_hook],
                ),
                timeout=self.settings.task_timeout,
            )

            finished_at = datetime.now()

            raw_output = result.content or ""
            if isinstance(raw_output, list):
                raw_output = "\n".join(str(item) for item in raw_output)

            if not raw_output.strip() and capture_hook.messages:
                raw_output = "\n\n".join(capture_hook.messages)

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

    def build_session_key(self, session_id: str) -> str:
        return f"lobuddy:session:{session_id}"

    def _create_temp_config(self, pet_state: dict[str, Any] | None = None) -> Path:
        """Create a temporary nanobot config file."""
        # Build system prompt with pet info if available
        system_prompt = "You are a helpful AI assistant."
        if pet_state:
            system_prompt += f"\n\n[Current Pet State]"
            system_prompt += f"\n- Name: {pet_state.get('name', 'Unknown')}"
            system_prompt += f"\n- Level: {pet_state.get('level', 1)}"
            system_prompt += (
                f"\n- EXP: {pet_state.get('exp', 0)} / {pet_state.get('exp_for_next_level', 100)}"
            )
            system_prompt += f"\n- Evolution Stage: {pet_state.get('evolution_stage', 1)}"
            system_prompt += (
                "\n\nWhen asked about pet status, level, or EXP, use the information above."
            )

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
                    "systemPrompt": system_prompt,
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

    def _ensure_config(self, pet_state: dict[str, Any] | None = None) -> Path:
        """Ensure nanobot config exists and return its path."""
        # Always create a fresh temp config to ensure settings are up to date
        return self._create_temp_config(pet_state)

    def _generate_summary(self, raw_output: str | list, max_length: int = 10000) -> str:
        if isinstance(raw_output, list):
            raw_output = "\n".join(str(item) for item in raw_output)

        if not raw_output:
            return "No output"

        if len(raw_output) <= max_length:
            return raw_output

        return raw_output[:max_length] + "\n\n[Content truncated...]"
