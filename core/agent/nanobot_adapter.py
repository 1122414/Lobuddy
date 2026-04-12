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


class NanobotAdapter:
    """Adapter for nanobot agent integration."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._bot: Any | None = None
        self._config_path: Path | None = None

    async def health_check(self) -> bool:
        """Check if nanobot is properly configured and can initialize."""
        try:
            config_path = self._create_temp_config()
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

    def _is_moonshot_provider(self) -> bool:
        """Check if current provider is Moonshot/Kimi.

        Prioritizes API base URL matching to avoid misclassifying
        non-Moonshot gateways (e.g., OpenRouter with kimi model).
        """
        api_base = (self.settings.llm_base_url or "").lower()
        model = (self.settings.llm_model or "").lower()

        # Primary: Check API base URL host
        if "moonshot" in api_base or "api.moonshot.ai" in api_base:
            return True

        # Secondary: Only use model name if base URL is empty/unknown
        # AND model explicitly indicates Moonshot
        if not api_base or api_base in ("https://api.openai.com/v1", ""):
            return "kimi" in model and "moonshot" in model

        return False

    async def _upload_image_to_moonshot(self, image_path: str) -> str | None:
        """Upload image to Moonshot API and return file_id."""
        import httpx
        import mimetypes

        api_key = self.settings.llm_api_key
        api_base = self.settings.llm_base_url or "https://api.moonshot.ai/v1"

        # Normalize API base URL for files endpoint
        # Handle cases: "https://api.moonshot.ai", "https://api.moonshot.ai/v1", "https://api.moonshot.ai/"
        base = api_base.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        files_url = f"{base}/files"

        try:
            p = Path(image_path)
            if not p.is_file():
                logger.warning(f"Image file not found: {image_path}")
                return None

            mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"

            with open(image_path, "rb") as f:
                file_content = f.read()

            async with httpx.AsyncClient() as client:
                files = {"file": (p.name, file_content, mime_type)}
                data = {"purpose": "image"}
                headers = {"Authorization": f"Bearer {api_key}"}

                response = await client.post(
                    files_url,
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=60.0,
                )

                if response.status_code in (200, 201):
                    result = response.json()
                    file_id = result.get("id")
                    logger.info(f"Image uploaded successfully, file_id: {file_id}")
                    return file_id
                else:
                    logger.error(
                        f"Failed to upload image: {response.status_code} - {response.text}"
                    )
                    return None

        except Exception as e:
            logger.error(f"Error uploading image to Moonshot: {e}")
            return None

    def _build_image_message(self, prompt: str, file_id: str | None) -> list[dict]:
        """Build message content with image reference for Moonshot API."""
        if not file_id:
            return [{"type": "text", "text": prompt or "[Image upload failed]"}]

        content = [{"type": "image_url", "image_url": {"url": f"ms://{file_id}"}}]
        if prompt:
            content.append({"type": "text", "text": prompt})

        return content

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

        try:
            from nanobot import Nanobot
            from nanobot.bus.events import InboundMessage

            config_path = self._ensure_config()
            bot = Nanobot.from_config(
                config_path=config_path,
                workspace=self.settings.workspace_path,
            )

            await self._compress_history_if_needed(bot, session_key)

            if image_path:
                logger.info(f"Processing message with image: {image_path}")

                if self._is_moonshot_provider():
                    file_id = await self._upload_image_to_moonshot(image_path)
                    if not file_id:
                        return AgentResult(
                            success=False,
                            raw_output="",
                            summary="Image upload failed",
                            error_message="Failed to upload image to Moonshot. Please try again or use text-only mode.",
                            started_at=started_at,
                            finished_at=datetime.now(),
                        )
                    content = self._build_image_message(prompt, file_id)
                    session = bot._loop.sessions.get_or_create(session_key)
                    session.add_message(role="user", content=content)
                    bot._loop.sessions.save(session)
                    result = await asyncio.wait_for(
                        bot.run("", session_key=session_key),
                        timeout=self.settings.task_timeout,
                    )
                else:
                    msg = InboundMessage(
                        channel="cli",
                        sender_id="user",
                        chat_id="direct",
                        content=prompt,
                        media=[image_path],
                    )
                    response = await bot._loop._process_message(msg, session_key=session_key)
                    raw_output = response.content if response else ""
                    finished_at = datetime.now()
                    duration = (finished_at - started_at).total_seconds()
                    summary = self._generate_summary(raw_output)
                    return AgentResult(
                        success=True,
                        raw_output=raw_output,
                        summary=summary,
                        error_message=None,
                        started_at=started_at,
                        finished_at=finished_at,
                    )

                raw_output = result.content or ""
                if isinstance(raw_output, list):
                    raw_output = "\n".join(str(item) for item in raw_output)

                finished_at = datetime.now()
                duration = (finished_at - started_at).total_seconds()
                summary = self._generate_summary(raw_output)

                logger.info(
                    f"Task completed for session={session_key}, "
                    f"success={True}, duration={duration:.2f}s, "
                    f"output_length={len(raw_output)}"
                )

                return AgentResult(
                    success=True,
                    raw_output=raw_output,
                    summary=summary,
                    error_message=None,
                    started_at=started_at,
                    finished_at=finished_at,
                )
            else:
                result = await asyncio.wait_for(
                    bot.run(
                        prompt,
                        session_key=session_key,
                    ),
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
                    f"output_length={len(raw_output)}"
                )

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

        temp_dir = Path(tempfile.gettempdir()) / "lobuddy"
        temp_dir.mkdir(exist_ok=True)
        config_path = temp_dir / "nanobot_config.json"

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        logger.debug(f"Created temp config at {config_path}")
        return config_path

    def _ensure_config(self) -> Path:
        """Ensure nanobot config exists and return its path."""
        return self._create_temp_config()

    def _generate_summary(self, raw_output: str | list, max_length: int = 10000) -> str:
        if isinstance(raw_output, list):
            raw_output = "\n".join(str(item) for item in raw_output)

        if not raw_output:
            return "No output"

        if len(raw_output) <= max_length:
            return raw_output

        return raw_output[:max_length] + "\n\n[Content truncated...]"
