"""Nanobot adapter for Lobuddy."""

import asyncio
import logging
import os
import re
import tempfile
import traceback
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


logger = logging.getLogger("lobuddy.nanobot_adapter")


def _register_analyze_image(gateway, image_path: str, settings, subagent_factory):
    from core.agent.tools.analyze_image_tool import AnalyzeImageTool

    custom_tool = AnalyzeImageTool(image_path, settings, subagent_factory)
    previous_tool = gateway.get_tool(custom_tool.name)
    gateway.register_tool(custom_tool)
    return custom_tool, previous_tool


def _cleanup_tool(gateway, custom_tool, previous_tool) -> None:
    if custom_tool is None:
        return
    try:
        if previous_tool is not None:
            gateway.register_tool(previous_tool)
        else:
            gateway.unregister_tool(custom_tool.name)
    except Exception as tool_cleanup_err:
        logger.warning(f"Failed to restore tool state: {tool_cleanup_err}")


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
    _SAFE_TYPES = (str, int, float, bool, list, dict, type(None))

    def __init__(self, guardrails=None):
        self.tools_used: list[str] = []
        self.guardrails = guardrails

    def wants_streaming(self) -> bool:
        return False

    def finalize_content(self, context: Any, content: str | None) -> str | None:
        return content

    async def before_execute_tools(self, context: Any) -> None:
        for tc in context.tool_calls:
            if self.guardrails and hasattr(tc, "arguments"):
                if not isinstance(tc.arguments, dict):
                    raise RuntimeError(
                        f"Guardrail blocked: tool arguments must be dict, got {type(tc.arguments).__name__}"
                    )
                args = tc.arguments
                for key, value in args.items():
                    if not isinstance(value, self._SAFE_TYPES):
                        raise RuntimeError(
                            f"Guardrail blocked: argument '{key}' has unsafe type {type(value).__name__}"
                        )

                for field_name, validator in [
                    ("command", self.guardrails.validate_shell_command),
                    ("path", self.guardrails.validate_path),
                    ("url", self.guardrails.validate_web_url),
                    ("working_dir", self.guardrails.validate_working_dir),
                ]:
                    field = args.get(field_name, "")
                    if field:
                        result = validator(field)
                        if result:
                            logger.warning(
                                "Guardrail blocked %s for tool '%s': %s (value=%r)",
                                field_name, tc.name, result, field
                            )
                            raise RuntimeError(result)

            self.tools_used.append(tc.name)

    def __getattr__(self, name: str):
        async def _noop(*args, **kwargs):
            pass
        return _noop


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
        started_at = datetime.now()
        logger.info(
            f"Starting task for session={session_key}, prompt_length={len(prompt)}, has_image={bool(image_path)}"
        )

        guardrail_result = self._preflight_guardrails(prompt)
        if guardrail_result:
            return guardrail_result

        bot = None
        config_path = None
        custom_tool = None
        previous_tool = None
        temp_system_msg = None

        try:
            from nanobot import Nanobot

            config_path = self._create_temp_config(model=self.settings.llm_model)
            bot = Nanobot.from_config(
                config_path=config_path,
                workspace=self.settings.workspace_path,
            )

            gateway = NanobotGateway(bot)
            await self.history_compressor.compress_if_needed(gateway, session_key)
            temp_system_msg, custom_tool, previous_tool = self._setup_image_tools(
                gateway, session_key, image_path
            )

            tracker = _ToolTracker(guardrails=self.guardrails)
            result = await asyncio.wait_for(
                bot.run(prompt, session_key=session_key, hooks=[tracker]),
                timeout=self.settings.task_timeout,
            )

            return self._build_success_result(
                result, tracker, started_at, prompt, session_key
            )

        except asyncio.TimeoutError:
            return self._handle_timeout(bot, session_key, started_at)

        except Exception as e:
            return self._handle_error(e, session_key, started_at)

        finally:
            self._cleanup(
                bot, session_key, temp_system_msg, custom_tool, previous_tool, config_path
            )

    def _preflight_guardrails(self, prompt: str) -> AgentResult | None:
        if not self.guardrails:
            return None
        from core.tools.tool_policy import ToolPolicy

        policy = ToolPolicy()
        shell_patterns = re.compile(
            r"^(rm\s|del\s|format\s|mkfs|dd\s|shutdown|reboot|rd\s|rmdir\s)", re.IGNORECASE
        )
        for line in prompt.split("\n"):
            stripped = line.strip()
            if shell_patterns.match(stripped) and policy.is_command_dangerous(stripped):
                error_msg = "Guardrail blocked: dangerous command detected in prompt"
                logger.warning(error_msg)
                now = datetime.now()
                return AgentResult(
                    success=False,
                    raw_output="",
                    summary=error_msg,
                    error_message=error_msg,
                    started_at=now,
                    finished_at=now,
                )
        return None

    def _setup_image_tools(
        self, gateway, session_key: str, image_path: str | None
    ) -> tuple[Any, Any, Any]:
        if not image_path:
            return None, None, None

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
            custom_tool, previous_tool = _register_analyze_image(
                gateway, image_path, self.settings, self.subagent_factory
            )
            return temp_system_msg, custom_tool, previous_tool
        else:
            logger.warning("LLM_MULTIMODAL_MODEL not configured; image analysis unavailable")
            temp_system_msg = {
                "role": "system",
                "content": (
                    "The user has uploaded an image, but image analysis is not configured. "
                    "You cannot use the analyze_image tool."
                ),
            }
            session.messages.append(temp_system_msg)
            gateway.save_session(session)
            return temp_system_msg, None, None

    @staticmethod
    def _looks_like_api_error(content: str) -> tuple[bool, str]:
        """Check if the content contains known API error signatures."""
        if not content:
            return False, ""
        lowered = content.lower()
        error_patterns = [
            "you didn't provide an api key",
            "incorrect api key provided",
            "invalid api key",
            "unauthorized",
            "rate limit",
            "too many requests",
            "internal server error",
            "bad gateway",
            "service unavailable",
            "invalid request error",
            "api key not valid",
            "authentication failed",
            "billing hard limit reached",
        ]
        for pattern in error_patterns:
            if pattern in lowered:
                return True, content.strip()
        return False, ""

    @staticmethod
    def _friendly_api_error_summary(content: str) -> str:
        """Translate provider/API errors into short user-facing guidance."""
        lowered = content.lower()
        if "didn't provide an api key" in lowered or "no api key" in lowered:
            return "AI 配置缺少 API Key，请在设置小窝的高级设置里填写 LLM API Key。"
        if (
            "incorrect api key" in lowered
            or "invalid api key" in lowered
            or "api key not valid" in lowered
            or "authentication failed" in lowered
            or "unauthorized" in lowered
        ):
            return "API Key 无效或没有权限，请在高级设置里检查 LLM API Key。"
        if "rate limit" in lowered or "too many requests" in lowered:
            return "模型服务请求太频繁了，请稍等一会儿再试，或检查当前账号额度。"
        if (
            "service unavailable" in lowered
            or "bad gateway" in lowered
            or "internal server error" in lowered
        ):
            return "模型服务暂时不可用，请稍后重试。"
        if "timeout" in lowered or "timed out" in lowered:
            return "这次请求超时了，可以在高级设置里调大任务超时时间后重试。"
        if (
            "invalid request" in lowered
            or "model" in lowered
            or "base url" in lowered
            or "billing hard limit" in lowered
        ):
            return "AI 请求配置可能不正确，请检查 Base URL、模型名和账号额度。"
        return "AI 请求失败了，请检查高级设置里的 API Key、Base URL 和模型名。"

    def _build_success_result(
        self, result, tracker, started_at: datetime, prompt: str, session_key: str
    ) -> AgentResult:
        finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()
        raw_output = result.content or ""
        if isinstance(raw_output, list):
            raw_output = "\n".join(str(item) for item in raw_output)

        is_api_error, error_detail = self._looks_like_api_error(raw_output)
        if is_api_error:
            friendly_summary = self._friendly_api_error_summary(error_detail)
            logger.warning(
                f"Task failed for session={session_key}: API error detected, "
                f"duration={duration:.2f}s"
            )
            return AgentResult(
                success=False,
                raw_output=raw_output,
                summary=friendly_summary,
                error_message=error_detail,
                started_at=started_at,
                finished_at=finished_at,
                tools_used=tracker.tools_used or None,
            )

        summary = self._generate_summary(raw_output)
        self._token_meter_integration.record_task_usage(
            session_key=session_key,
            prompt=prompt,
            raw_output=raw_output,
            result=result,
            tools_used=tracker.tools_used,
        )
        logger.info(
            f"Task completed for session={session_key}, success=True, "
            f"duration={duration:.2f}s, output_length={len(raw_output)}, tools_used={tracker.tools_used}"
        )
        return AgentResult(
            success=True,
            raw_output=raw_output,
            summary=summary,
            started_at=started_at,
            finished_at=finished_at,
            tools_used=tracker.tools_used or None,
        )

    def _handle_timeout(self, bot, session_key: str, started_at: datetime) -> AgentResult:
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
            summary="这次请求超时了，可以在高级设置里调大任务超时时间后重试。",
            error_message=f"Task exceeded {self.settings.task_timeout} seconds timeout",
            started_at=started_at,
            finished_at=finished_at,
        )

    def _handle_error(self, exc: Exception, session_key: str, started_at: datetime) -> AgentResult:
        finished_at = datetime.now()
        safe_error = self._redact_sensitive(str(exc))
        is_api_error, error_detail = self._looks_like_api_error(safe_error)
        summary = (
            self._friendly_api_error_summary(error_detail)
            if is_api_error
            else "任务执行失败了，请稍后重试；如果持续失败，可以查看详情排查。"
        )
        logger.error(f"Task failed for session={session_key}: {safe_error}")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(self._redact_sensitive(traceback.format_exc()))
        return AgentResult(
            success=False,
            raw_output="",
            summary=summary,
            error_message=safe_error,
            started_at=started_at,
            finished_at=finished_at,
        )

    def _cleanup(
        self,
        bot,
        session_key: str,
        temp_system_msg: Any,
        custom_tool: Any,
        previous_tool: Any,
        config_path: Path | None,
    ) -> None:
        if bot is not None:
            gateway = NanobotGateway(bot)
            if temp_system_msg is not None:
                try:
                    session = gateway.get_or_create_session(session_key)
                    _remove_temp_system_msg(session, temp_system_msg)
                    gateway.save_session(session)
                except Exception as cleanup_err:
                    logger.warning(f"Failed to clean up temp system message: {cleanup_err}")
            _cleanup_tool(gateway, custom_tool, previous_tool)

        if config_path is not None:
            try:
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

    def _redact_sensitive(self, text: str) -> str:
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
