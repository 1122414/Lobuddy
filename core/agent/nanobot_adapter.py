"""Nanobot adapter for Lobuddy."""

import asyncio
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.config import Settings

from core.agent.config_builder import build_nanobot_config, write_temp_config
from core.events.bus import EventBus
from core.agent.subagent_factory import SubagentFactory
from core.runtime.token_meter import TokenMeter
from core.agent.nanobot_gateway import NanobotGateway
from core.agent.history_compressor import HistoryCompressor
from core.agent.token_meter_integration import TokenMeterIntegration
from core.agent.tool_registry import ToolRegistry

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

    def __init__(self, guardrails=None):
        self.tools_used: list[str] = []
        self.guardrails = guardrails

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
            # Apply guardrails if configured
            if self.guardrails and hasattr(tc, "arguments"):
                if not isinstance(tc.arguments, dict):
                    raise RuntimeError(
                        f"Guardrail blocked: tool arguments must be dict, got {type(tc.arguments).__name__}"
                    )
                args = tc.arguments
                SAFE_TYPES = (str, int, float, bool, list, dict, type(None))
                for key, value in args.items():
                    if not isinstance(value, SAFE_TYPES):
                        raise RuntimeError(
                            f"Guardrail blocked: argument '{key}' has unsafe type {type(value).__name__}"
                        )

                command = args.get("command", "")
                path = args.get("path", "")
                url = args.get("url", "")

                if command:
                    result = self.guardrails.validate_shell_command(command)
                    if result:
                        raise RuntimeError(result)

                if path:
                    result = self.guardrails.validate_path(path)
                    if result:
                        raise RuntimeError(result)

                if url:
                    result = self.guardrails.validate_web_url(url)
                    if result:
                        raise RuntimeError(result)

                working_dir = args.get("working_dir", "")
                if working_dir:
                    result = self.guardrails.validate_working_dir(working_dir)
                    if result:
                        raise RuntimeError(result)

            self.tools_used.append(tc.name)

    async def after_iteration(self, context: Any) -> None:
        pass

    def finalize_content(self, context: Any, content: str | None) -> str | None:
        return content


def _remove_temp_system_msg(session: Any, marker: dict[str, str]) -> None:
    """Remove temporary system message from session by exact role+content match."""
    target_role = marker.get("role")
    target_content = marker.get("content")
    if not target_role or not target_content:
        return
    original = list(session.messages)
    cleaned = [
        msg
        for msg in original
        if not (
            isinstance(msg, dict)
            and msg.get("role") == target_role
            and msg.get("content") == target_content
        )
    ]
    if len(cleaned) < len(original):
        session.messages[:] = cleaned


class NanobotAdapter:
    """Adapter for nanobot agent integration."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._bot: Any | None = None
        self._config_path: Path | None = None
        self.event_bus = EventBus()
        self.subagent_factory = SubagentFactory(settings, self.event_bus)
        self.token_meter = TokenMeter()
        self.history_compressor = HistoryCompressor(settings, self.token_meter)
        self._token_meter_integration = TokenMeterIntegration(
            self.token_meter, settings.llm_model
        )
        from core.safety.guardrails import SafetyGuardrails

        self.guardrails = SafetyGuardrails(settings.workspace_path)

    async def health_check(self) -> bool:
        """Check if nanobot is properly configured and can initialize."""
        config_path = None
        try:
            config_path = self._create_temp_config(model=self.settings.llm_model)
            if not config_path.exists():
                return False

            from nanobot import Nanobot

            bot = Nanobot.from_config(
                config_path=config_path,
                workspace=self.settings.workspace_path,
            )

            gateway = NanobotGateway(bot)
            if gateway._loop is None:
                return False

            logger.info("Health check passed")
            return True

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
        finally:
            if config_path is not None:
                try:
                    import os
                    if config_path.exists():
                        os.unlink(config_path)
                        logger.debug(f"Cleaned up temp config from health_check: {config_path}")
                except Exception:
                    pass

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

        # Pre-flight guardrail: scan prompt for explicit dangerous shell commands
        if self.guardrails:
            import re
            from core.tools.tool_policy import ToolPolicy

            policy = ToolPolicy()
            # Only scan lines that look like shell commands (start with known shell keywords)
            shell_patterns = re.compile(
                r"^(rm\s|del\s|format\s|mkfs|dd\s|shutdown|reboot|rd\s|rmdir\s)", re.IGNORECASE
            )
            for line in prompt.split("\n"):
                stripped = line.strip()
                if shell_patterns.match(stripped) and policy.is_command_dangerous(stripped):
                    error_msg = "Guardrail blocked: dangerous command detected in prompt"
                    logger.warning(error_msg)
                    return AgentResult(
                        success=False,
                        raw_output="",
                        summary=error_msg,
                        error_message=error_msg,
                        started_at=started_at,
                        finished_at=datetime.now(),
                    )

        bot = None
        config_path = None
        custom_tool = None
        previous_tool = None
        temp_system_msg = None

        try:
            from nanobot import Nanobot

            config_path = self._ensure_config(model=self.settings.llm_model)
            bot = Nanobot.from_config(
                config_path=config_path,
                workspace=self.settings.workspace_path,
            )

            gateway = NanobotGateway(bot)
            await self.history_compressor.compress_if_needed(gateway, session_key)

            if image_path:
                logger.info(f"Processing message with image: {image_path}")
                session = gateway.get_or_create_session(session_key)
                if self.settings.llm_multimodal_model:
                    temp_system_msg = {
                        "role": "system",
                        "content": (
                            "The user has uploaded an image. "
                            "If you need to understand the image contents, use the analyze_image tool."
                        ),
                    }
                    session.messages.append(temp_system_msg)
                    gateway.save_session(session)

                    custom_tool, previous_tool = ToolRegistry.register_analyze_image(
                        gateway, image_path, self.settings, self.subagent_factory
                    )
                else:
                    logger.warning(
                        "LLM_MULTIMODAL_MODEL not configured; image analysis unavailable"
                    )
                    temp_system_msg = {
                        "role": "system",
                        "content": (
                            "The user has uploaded an image, but image analysis is not configured. "
                            "You cannot use the analyze_image tool."
                        ),
                    }
                    session.messages.append(temp_system_msg)
                    gateway.save_session(session)

            tracker = _ToolTracker(guardrails=self.guardrails)
            result = await asyncio.wait_for(
                bot.run(prompt, session_key=session_key, hooks=[tracker]),
                timeout=self.settings.task_timeout,
            )

            finished_at = datetime.now()
            duration = (finished_at - started_at).total_seconds()

            raw_output = result.content or ""
            if isinstance(raw_output, list):
                raw_output = "\n".join(str(item) for item in raw_output)

            summary = self._generate_summary(raw_output)

            self._token_meter_integration.record_task_usage(
                session_key=session_key,
                prompt=prompt,
                raw_output=raw_output,
                result=result,
                tools_used=tracker.tools_used,
            )

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
            if bot is not None:
                try:
                    gateway = NanobotGateway(bot)
                    gateway.cancel()
                    for task in gateway.get_tasks():
                        if hasattr(task, "cancel"):
                            task.cancel()
                except Exception as cancel_err:
                    logger.warning(f"Failed to cancel bot on timeout: {cancel_err}")
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
            safe_error = self._redact_sensitive(str(e))
            logger.error(f"Task failed for session={session_key}: {safe_error}")
            # Only log traceback in debug mode to avoid leaking sensitive info
            if logger.isEnabledFor(logging.DEBUG):
                import traceback
                logger.debug(self._redact_sensitive(traceback.format_exc()))
            return AgentResult(
                success=False,
                raw_output="",
                summary="Task failed",
                error_message=safe_error,
                started_at=started_at,
                finished_at=finished_at,
            )
        finally:
            if bot is not None:
                gateway = NanobotGateway(bot)
                if temp_system_msg is not None:
                    try:
                        session = gateway.get_or_create_session(session_key)
                        _remove_temp_system_msg(session, temp_system_msg)
                        gateway.save_session(session)
                    except Exception as cleanup_err:
                        logger.warning(f"Failed to clean up temp system message: {cleanup_err}")

                ToolRegistry.cleanup(gateway, custom_tool, previous_tool)

            # Clean up temp config file
            if config_path is not None:
                try:
                    import os
                    if config_path.exists():
                        os.unlink(config_path)
                        logger.debug(f"Cleaned up temp config: {config_path}")
                except Exception as config_cleanup_err:
                    logger.warning(f"Failed to clean up temp config: {config_cleanup_err}")

    def build_session_key(self, session_id: str) -> str:
        return f"lobuddy:session:{session_id}"

    def _create_temp_config(self, model: str | None = None) -> Path:
        """Create a temporary nanobot config file."""
        effective_model = model or self.settings.llm_model
        config = build_nanobot_config(self.settings, effective_model, self.settings.workspace_path)
        temp_dir = Path(tempfile.gettempdir()) / "lobuddy"
        safe_model = effective_model.replace("/", "_").replace("\\", "_")
        return write_temp_config(config, temp_dir, safe_model)

    def _ensure_config(self, model: str | None = None) -> Path:
        """Ensure nanobot config exists and return its path."""
        return self._create_temp_config(model=model)

    def _redact_sensitive(self, text: str) -> str:
        import re
        # Redact API keys that look like sk-... or bearer tokens
        redacted = re.sub(r"\b(sk-[a-zA-Z0-9]{20,})\b", "[REDACTED_API_KEY]", text)
        redacted = re.sub(r"\b(bearer\s+[a-zA-Z0-9_-]{20,})\b", "[REDACTED_TOKEN]", redacted, flags=re.IGNORECASE)
        return redacted

    def _generate_summary(self, raw_output: str | list, max_length: int = 10000) -> str:
        if isinstance(raw_output, list):
            raw_output = "\n".join(str(item) for item in raw_output)

        if not raw_output:
            return "No output"

        if len(raw_output) <= max_length:
            return raw_output

        return raw_output[:max_length] + "\n\n[Content truncated...]"
