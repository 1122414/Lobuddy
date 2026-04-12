"""Nanobot adapter for Lobuddy."""

import asyncio
import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.config import Settings

logger = logging.getLogger("lobuddy.nanobot_adapter")


class AgentResult(BaseModel):
    """Result of an agent task execution."""

    success: bool
    raw_output: str
    summary: str
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime
    tools_used: list[str] | None = None


class _ToolTracker:
    """Simple hook to track which tools are executed during a run."""

    def __init__(self):
        self.tools_used: list[str] = []

    def wants_streaming(self) -> bool:
        return False

    async def before_iteration(self, context: Any) -> None:
        pass

    async def on_stream(self, context: Any, delta: str) -> None:
        pass

    async def on_stream_end(self, context: Any, *, resuming: bool) -> None:
        pass

    async def before_execute_tools(self, context: Any) -> None:
        for tc in context.tool_calls:
            self.tools_used.append(tc.name)

    async def after_iteration(self, context: Any) -> None:
        pass

    def finalize_content(self, context: Any, content: str | None) -> str | None:
        return content


class NanobotAdapter:
    """Adapter for nanobot agent integration."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._bot: Any | None = None
        self._config_path: Path | None = None

    async def health_check(self) -> bool:
        """Check if nanobot is properly configured and can initialize."""
        try:
            config_path = self._create_temp_config(model=self.settings.llm_model)
            if not config_path.exists():
                return False

            from nanobot import Nanobot

            bot = Nanobot.from_config(
                config_path=config_path,
                workspace=self.settings.workspace_path,
            )

            if bot._loop is None:
                return False

            logger.info("Health check passed")
            return True

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    async def run_task(
        self,
        prompt: str,
        session_key: str,
        pet_state: dict[str, Any] | None = None,
        image_path: str | None = None,
    ) -> AgentResult:
        """Run a task through nanobot."""
        started_at = datetime.now()
        logger.info(
            f"Starting task for session={session_key}, prompt_length={len(prompt)}, has_image={bool(image_path)}"
        )

        bot = None
        custom_tool = None

        try:
            from nanobot import Nanobot

            config_path = self._ensure_config(model=self.settings.llm_model)
            bot = Nanobot.from_config(
                config_path=config_path,
                workspace=self.settings.workspace_path,
            )

            await self._compress_history_if_needed(bot, session_key)

            effective_prompt = prompt
            if image_path:
                logger.info(f"Processing message with image: {image_path}")
                effective_prompt = (
                    f"{prompt}\n\n[SYSTEM NOTE: The user has uploaded an image. "
                    f"If you need to understand the image contents, use the analyze_image tool.]"
                )
                from core.agent.tools.analyze_image_tool import AnalyzeImageTool

                custom_tool = AnalyzeImageTool(image_path, self.settings)
                bot._loop.tools.register(custom_tool)

            tracker = _ToolTracker()
            result = await asyncio.wait_for(
                bot.run(effective_prompt, session_key=session_key, hooks=[tracker]),
                timeout=self.settings.task_timeout,
            )

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()

            raw_output = result.content or ""
            if isinstance(raw_output, list):
                raw_output = "\n".join(str(item) for item in raw_output)

            summary = self._generate_summary(raw_output)

            logger.info(
                f"Task completed for session={session_key}, "
                f"success={True}, duration={duration:.2f}s, "
                f"output_length={len(raw_output)}, tools_used={tracker.tools_used}"
            )

            return AgentResult(
                success=True,
                raw_output=raw_output,
                summary=summary,
                error_message=None,
                started_at=started_at,
                finished_at=finished_at,
                tools_used=tracker.tools_used or None,
            )

        except asyncio.TimeoutError:
            finished_at = datetime.now()
            logger.warning(f"Task timeout for session={session_key}")
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
            logger.error(f"Task failed for session={session_key}: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return AgentResult(
                success=False,
                raw_output="",
                summary="Task failed",
                error_message=str(e),
                started_at=started_at,
                finished_at=finished_at,
            )
        finally:
            if custom_tool is not None and bot is not None:
                bot._loop.tools.unregister(custom_tool.name)

    async def _compress_history_if_needed(self, bot: Any, session_key: str) -> None:
        """Compress oldest messages when history exceeds threshold."""
        session = bot._loop.sessions.get_or_create(session_key)
        messages = session.messages
        max_turns = self.settings.history_max_turns
        compress_threshold = self.settings.history_compress_threshold

        if len(messages) <= max_turns:
            return

        to_compress_count = min(compress_threshold, len(messages) // 2)
        to_compress = messages[:to_compress_count]
        remaining = messages[to_compress_count:]

        logger.info(
            f"Compressing {to_compress_count} messages for session {session_key} "
            f"(total: {len(messages)} -> {len(remaining) + 1})"
        )

        history_text = self._format_messages_for_summary(to_compress)
        summary_prompt = (
            f"{self.settings.history_compress_prompt}\n\nConversation to summarize:\n{history_text}"
        )

        try:
            from nanobot.bus.events import InboundMessage

            msg = InboundMessage(
                channel="cli",
                sender_id="user",
                chat_id="direct",
                content=summary_prompt,
            )
            response = await bot._loop._process_message(msg, session_key=f"{session_key}:compress")
            summary = response.content if response else "[Earlier conversation]"

            summary_msg = {"role": "system", "content": f"[Earlier context]: {summary}"}
            session.messages = [summary_msg] + remaining
            bot._loop.sessions.save(session)

            logger.debug(f"Compression complete, new message count: {len(session.messages)}")

        except Exception as e:
            logger.warning(f"History compression failed: {e}, falling back to truncation")
            session.messages = remaining
            bot._loop.sessions.save(session)

    def _format_messages_for_summary(self, messages: list) -> str:
        """Format messages for compression prompt."""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 500:
                content = content[:500] + "..."
            elif isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if len(text) > 500:
                            text = text[:500] + "..."
                        text_parts.append(text)
                content = " ".join(text_parts) if text_parts else "[multimodal content]"
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def build_session_key(self, session_id: str) -> str:
        return f"lobuddy:session:{session_id}"

    def _create_temp_config(self, model: str | None = None) -> Path:
        """Create a temporary nanobot config file."""
        effective_model = model or self.settings.llm_model
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
                    "model": effective_model,
                    "maxToolIterations": self.settings.nanobot_max_iterations,
                }
            },
        }

        temp_dir = Path(tempfile.gettempdir()) / "lobuddy"
        temp_dir.mkdir(exist_ok=True)
        safe_model = effective_model.replace("/", "_").replace("\\", "_")
        config_path = temp_dir / f"nanobot_config_{safe_model}.json"

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        logger.debug(f"Created temp config at {config_path} (model={effective_model})")
        return config_path

    def _ensure_config(self, model: str | None = None) -> Path:
        """Ensure nanobot config exists and return its path."""
        return self._create_temp_config(model=model)

    def _generate_summary(self, raw_output: str | list, max_length: int = 10000) -> str:
        if isinstance(raw_output, list):
            raw_output = "\n".join(str(item) for item in raw_output)

        if not raw_output:
            return "No output"

        if len(raw_output) <= max_length:
            return raw_output

        return raw_output[:max_length] + "\n\n[Content truncated...]"
