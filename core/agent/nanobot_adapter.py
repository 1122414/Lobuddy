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

from core.memory.memory_service import MemoryService
from core.memory.memory_schema import MemoryType
from core.logging.trace import set_trace_id, clear_trace_id, get_logger
from core.logging.trace_hook import AgentTracingHook
from core.safety.hitl_approval import (
    DenyAllHitlApprovalProvider,
    HitlApprovalProvider,
    HitlApprovalRequest,
    request_approval_with_timeout,
)
from core.safety.command_risk import CommandRiskAction, HumanApprovalDenied


logger = logging.getLogger("lobuddy.nanobot_adapter")
agent_log = get_logger("agent")
tool_log = get_logger("tool")
task_log = get_logger("task")
security_log = get_logger("security")

_DREAM_COMMANDS = ("/dream", "/dream-log", "/dream-restore")


def _register_analyze_image(gateway, image_path: str, subagent_factory):
    from core.agent.tools.analyze_image_tool import AnalyzeImageTool

    custom_tool = AnalyzeImageTool(image_path, subagent_factory)
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

    def __init__(
        self,
        guardrails=None,
        guardrails_enabled: bool = True,
        block_dream_commands: bool = True,
        hitl_approval_provider: HitlApprovalProvider | None = None,
        session_id: str = "",
        hitl_timeout_seconds: int = 120,
    ):
        self.tools_used: list[str] = []
        self.guardrails = guardrails
        self.guardrails_enabled = guardrails_enabled
        self.block_dream_commands = block_dream_commands
        self._hitl_approval_provider = hitl_approval_provider
        self._session_id = session_id
        self._hitl_timeout_seconds = hitl_timeout_seconds

    def wants_streaming(self) -> bool:
        return False

    def finalize_content(self, context: Any, content: str | None) -> str | None:
        return content

    async def before_execute_tools(self, context: Any) -> None:
        # Track all HITL commands in this round to enforce single-command rule
        hitl_commands: list[dict] = []

        for tc in context.tool_calls:
            if self.guardrails_enabled and self.guardrails and hasattr(tc, "arguments"):
                if not isinstance(tc.arguments, dict):
                    reason = f"Guardrail blocked: tool arguments must be dict, got {type(tc.arguments).__name__}"
                    security_log.warning("Tool '%s': %s", tc.name, reason)
                    raise RuntimeError(reason)
                args = tc.arguments
                for key, value in args.items():
                    if not isinstance(value, self._SAFE_TYPES):
                        reason = f"Guardrail blocked: argument '{key}' has unsafe type {type(value).__name__}"
                        security_log.warning("Tool '%s': %s", tc.name, reason)
                        raise RuntimeError(reason)

                # HITL-aware command validation (replaces old validate_shell_command)
                command = args.get("command", "")
                if command and (tc.name == "exec" or tc.name == "shell"):
                    assessment = self.guardrails.assess_shell_command(
                        command,
                        working_dir=args.get("working_dir", ""),
                    )
                    if assessment.action == CommandRiskAction.DENY:
                        security_log.warning(
                            "Guardrail: tool='%s' command blocked — %s",
                            tc.name, assessment.reason,
                        )
                        raise RuntimeError(f"Dangerous command blocked: {assessment.reason}")
                    elif assessment.action == CommandRiskAction.HITL_REQUIRED:
                        hitl_commands.append({
                            "tc": tc,
                            "assessment": assessment,
                            "working_dir": args.get("working_dir", ""),
                        })
                        continue  # Skip normal validation for HITL commands

                # Non-command field validations (path, url, working_dir)
                for field_name, validator in [
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
                            security_log.warning(
                                "Guardrail: tool='%s' field='%s' blocked — %s",
                                tc.name, field_name, result,
                            )
                            raise RuntimeError(result)
            elif self.guardrails and hasattr(tc, "arguments"):
                # guardrails_enabled=False: all commands pass but HITL still applies
                # to destructive commands (delete); DENY is demoted to warning only.
                if isinstance(tc.arguments, dict):
                    command = tc.arguments.get("command", "")
                    if command and (tc.name == "exec" or tc.name == "shell"):
                        assessment = self.guardrails.assess_shell_command(
                            command,
                            working_dir=tc.arguments.get("working_dir", ""),
                        )
                        if assessment.action == CommandRiskAction.DENY:
                            security_log.warning(
                                "Guardrails disabled: tool='%s' risky command allowed — %s",
                                tc.name, assessment.reason,
                            )
                        elif assessment.action == CommandRiskAction.HITL_REQUIRED:
                            hitl_commands.append({
                                "tc": tc,
                                "assessment": assessment,
                                "working_dir": tc.arguments.get("working_dir", ""),
                            })

            # Block dream commands in exec tool calls (if enabled)
            if self.block_dream_commands and tc.name == "exec" and isinstance(tc.arguments, dict):
                command = tc.arguments.get("command", "")
                if any(dream_cmd in command for dream_cmd in ("/dream", "/dream-log", "/dream-restore")):
                    raise RuntimeError(
                        "Dream commands are disabled in Lobuddy mode. "
                        "Memory management is handled by Lobuddy MemoryService."
                    )

            self.tools_used.append(tc.name)

        # Process HITL commands — only one allowed per round
        if len(hitl_commands) > 1:
            raise RuntimeError(
                "Multiple dangerous commands in one tool call round. "
                "Please submit dangerous commands one at a time for safety review."
            )
        if hitl_commands:
            hc = hitl_commands[0]
            assessment = hc["assessment"]
            tc = hc["tc"]

            provider = self._hitl_approval_provider
            if provider is None:
                provider = DenyAllHitlApprovalProvider()

            request = HitlApprovalRequest.create(
                session_id=self._session_id,
                tool_name=tc.name,
                command=assessment.command,
                working_dir=hc["working_dir"],
                reason=assessment.reason,
                affected_paths=assessment.affected_paths,
                risk_tags=assessment.risk_tags,
                timeout_seconds=self._hitl_timeout_seconds,
            )

            decision = await request_approval_with_timeout(provider, request)

            self._log_hitl_decision(request, assessment, decision)

            if not decision.approved:
                raise HumanApprovalDenied(
                    f"Dangerous command cancelled: {decision.reason}"
                )

            self.tools_used.append(tc.name)

    @staticmethod
    def _log_hitl_decision(request, assessment, decision) -> None:
        try:
            from core.storage.hitl_approval_repo import HitlApprovalRepository

            repo = HitlApprovalRepository()
            repo.log_decision(
                session_id=request.session_id,
                tool_name=request.tool_name,
                command=request.command,
                working_dir=request.working_dir,
                affected_paths=request.affected_paths,
                risk_tags=request.risk_tags,
                reason=request.reason,
                approved=decision.approved,
                decision_reason=decision.reason,
            )
        except Exception:
            pass

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
        self._memory_service: MemoryService | None = None
        self._memory_gateway = None
        self._memory_user_message_count: int = 0
        self._skill_manager = None
        self._hitl_approval_provider: HitlApprovalProvider | None = None

    def set_memory_service(self, service: MemoryService) -> None:
        self._memory_service = service

    def set_skill_manager(self, manager) -> None:
        """5.3: Set skill manager. Active skills are prompt-visible via SkillSelector.
        Usage feedback (record_result) is intentionally not recorded here because
        nanobot does not expose reliable per-skill execution events yet. When nanobot
        adds skill execution hooks, wire record_result() through _ToolTracker."""
        self._skill_manager = manager

    def set_memory_gateway(self, gateway) -> None:
        """5.3: Set memory write gateway for all long-term memory writes."""
        self._memory_gateway = gateway

    def set_hitl_approval_provider(self, provider: HitlApprovalProvider | None) -> None:
        self._hitl_approval_provider = provider

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
        task_id = session_key.split(":")[-1] if ":" in session_key else session_key
        set_trace_id(task_id)
        logger.info(
            f"Starting task for session={session_key}, prompt_length={len(prompt)}, has_image={bool(image_path)}"
        )
        task_log.info(
            "Task start — session=%s, prompt_len=%d, image=%s",
            session_key, len(prompt), bool(image_path),
        )

        original_prompt = prompt
        self._memory_user_message_count += 1
        self._sync_strong_signal_memory(original_prompt, session_key)

        boundary_result = self._preflight_lobuddy_memory_boundary(original_prompt)
        if boundary_result is not None:
            return boundary_result

        if self._memory_service is not None:
            bundle = self._memory_service.build_prompt_context(original_prompt, session_key)
            if self._skill_manager is not None:
                from core.skills.skill_selector import SkillSelector
                bundle.active_skills = SkillSelector(self._skill_manager).build_skills_summary()
            injection = bundle.build_injection_text()
            if injection:
                prompt = injection + original_prompt

        route = None
        governance_enabled = getattr(
            self.settings, "execution_governance_enabled", False
        )
        if governance_enabled:
            try:
                from core.agent.execution_intent import ExecutionIntentRouter
                router = ExecutionIntentRouter()
                route = router.route(original_prompt)
                if router.should_govern(route):
                    execution_prompt = self._build_execution_prompt(route)
                    if execution_prompt:
                        prompt = execution_prompt + "\n\n" + prompt
            except Exception as e:
                logger.debug("Execution routing skipped: %s", e)

        guardrail_result = self._preflight_guardrails(original_prompt)
        if guardrail_result:
            return guardrail_result

        bot = None
        config_path = None
        custom_tool = None
        previous_tool = None
        session_search_tool = None
        temp_system_msg = None
        resolver_tool = None
        open_tool = None
        execution_hook = None

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

            if self.settings.memory_session_search_enabled:
                try:
                    from core.agent.tools.session_search_tool import SessionSearchTool

                    session_search_tool = SessionSearchTool(
                        settings=self.settings,
                        current_session_id=session_key.split(":")[-1] if ":" in session_key else session_key,
                    )
                    gateway.register_tool(session_search_tool)
                    logger.debug("session_search tool registered for session=%s", session_key)
                except ImportError as e:
                    logger.warning(
                        "session_search_enabled_but_unavailable: "
                        "SessionSearchTool could not be imported (session=%s): %s",
                        session_key, e,
                    )
                except Exception as e:
                    logger.warning("Failed to register session_search tool (session=%s): %s", session_key, e)

            if (
                route is not None
                and governance_enabled
                and getattr(route, "requires_tools", False)
            ):
                try:
                    from core.agent.tools.local_app_resolve_tool import LocalAppResolveTool
                    from core.agent.tools.local_open_tool import LocalOpenTool
                    from core.agent.execution_budget import ExecutionBudget
                    from core.agent.execution_hook import ExecutionGovernanceHook
                    from core.agent.execution_intent import ExecutionIntent

                    if route.intent == ExecutionIntent.LOCAL_OPEN_TARGET:
                        local_tools_enabled = getattr(
                            self.settings, "execution_local_tools_enabled", True
                        )
                        if local_tools_enabled:
                            shared_candidates: list[dict[str, Any]] = []
                            resolver_tool = LocalAppResolveTool(
                                candidate_sink=shared_candidates,
                                guardrails=self.guardrails,
                            )
                            gateway.register_tool(resolver_tool)
                            logger.debug("local_app_resolve tool registered")

                            open_tool = LocalOpenTool(
                                resolver_candidates=shared_candidates,
                                guardrails=self.guardrails,
                            )
                            gateway.register_tool(open_tool)
                            logger.debug("local_open tool registered")
                except Exception as e:
                    logger.warning("Failed to register execution tools: %s", e)

            tracker = _ToolTracker(
                guardrails=self.guardrails,
                guardrails_enabled=self.settings.guardrails_enabled,
                block_dream_commands=self.settings.memory_block_dream_commands,
                hitl_approval_provider=self._hitl_approval_provider,
                session_id=session_key,
                hitl_timeout_seconds=getattr(
                    self.settings, "hitl_approval_timeout_seconds", 120
                ),
            )

            hooks: list[Any] = [tracker, AgentTracingHook()]
            if route is not None and governance_enabled:
                try:
                    from core.agent.execution_budget import ExecutionBudget
                    from core.agent.execution_hook import ExecutionGovernanceHook

                    trace_repo = None
                    trace_enabled = getattr(self.settings, "execution_trace_enabled", True)
                    if trace_enabled:
                        try:
                            from core.storage.execution_trace_repository import ExecutionTraceRepository
                            trace_repo = ExecutionTraceRepository()
                        except Exception:
                            pass

                    budget = ExecutionBudget(
                        max_tool_calls_per_task=getattr(
                            self.settings, "execution_max_tool_calls_per_task", 6
                        ),
                        max_local_lookup_calls=getattr(
                            self.settings, "execution_max_local_lookup_calls", 2
                        ),
                        max_shell_calls_per_task=getattr(
                            self.settings, "execution_max_shell_calls_per_task", 2
                        ),
                        block_shell_for_local_open=getattr(
                            self.settings, "execution_block_shell_for_local_open", True
                        ),
                        max_tool_result_chars=getattr(
                            self.settings, "execution_max_tool_result_chars", 3000
                        ),
                        enabled=governance_enabled,
                    )
                    execution_hook = ExecutionGovernanceHook(
                        route,
                        budget,
                        session_id=session_key,
                        trace_repo=trace_repo,
                        guardrails=self.guardrails,
                    )
                    hooks.append(execution_hook)
                except Exception as e:
                    logger.warning("Execution governance hook skipped: %s", e)

            result = await asyncio.wait_for(
                bot.run(prompt, session_key=session_key, hooks=hooks),
                timeout=self.settings.task_timeout,
            )

            self._maybe_trigger_memory_update(original_prompt, session_key)

            return self._build_success_result(
                result, tracker, started_at, prompt, session_key
            )

        except asyncio.TimeoutError:
            return self._handle_timeout(bot, session_key, started_at)

        except Exception as e:
            return self._handle_error(e, session_key, started_at)

        finally:
            self._cleanup(
                bot, session_key, temp_system_msg,
                custom_tool, previous_tool, session_search_tool,
                resolver_tool, open_tool,
                config_path,
            )

    def _maybe_trigger_memory_update(self, last_user_message: str, session_key: str) -> None:
        if self._memory_service is None:
            return
        count_trigger = (
            self._memory_user_message_count > 0
            and self._memory_user_message_count
            % self.settings.memory_update_every_n_user_messages
            == 0
        )
        signal_trigger = (
            self.settings.memory_update_on_strong_signal
            and self._has_memory_signal(last_user_message)
        )
        if not count_trigger and not signal_trigger:
            return
        try:
            asyncio.ensure_future(
                self._run_memory_update(session_key)
            )
        except Exception as e:
            logger.debug("Failed to schedule memory update: %s", e)

    @staticmethod
    def _build_execution_prompt(route) -> str:
        """Build a short execution governance prompt for the current route."""
        from core.agent.execution_intent import ExecutionIntent

        base = f"Lobuddy execution route: {route.intent.value.upper()}."
        if route.intent == ExecutionIntent.LOCAL_OPEN_TARGET:
            return (
                f"{base}\n"
                "Use local_app_resolve first to find the application or shortcut. "
                "If one high-confidence openable candidate is found, use local_open to open it. "
                "Do not use exec for recursive search. "
                "Do not search Program Files or AppData unless the user provides an install path. "
                "If no candidate is found in desktop/start menu, stop and report that."
            )
        if route.intent == ExecutionIntent.LOCAL_FIND_FILE:
            return (
                f"{base}\n"
                "Use controlled directory listing to find the file. "
                "Do not use exec for recursive file search."
            )
        return ""

    def _sync_strong_signal_memory(self, user_message: str, session_key: str = "") -> None:
        if self._memory_gateway is None:
            return
        try:
            from core.memory.memory_schema import MemoryType
            from core.memory.memory_write_gateway import WriteContext

            context = WriteContext(
                source="strong_signal",
                session_id=session_key,
                triggered_by="adapter",
            )

            user_name = self._extract_user_name(user_message)
            if user_name:
                self._memory_gateway.submit_identity_memory(
                    memory_type=MemoryType.USER_PROFILE,
                    title="Basic Notes",
                    content=f"The user's name is {user_name}.",
                    context=context,
                )
                logger.info("Synced user name from strong signal: %s", user_name)

            pet_name = self._extract_pet_name(user_message)
            if pet_name:
                self._memory_gateway.submit_identity_memory(
                    memory_type=MemoryType.SYSTEM_PROFILE,
                    title="Identity",
                    content=f"My name is {pet_name}. I am an AI desktop pet assistant.",
                    context=context,
                )
                logger.info("Synced pet name from strong signal: %s", pet_name)
        except Exception as e:
            logger.debug("Strong signal sync failed: %s", e)

    def _preflight_lobuddy_memory_boundary(self, prompt: str) -> AgentResult | None:
        """Block nanobot Dream commands — Lobuddy handles memory management."""
        if not self.settings.memory_block_dream_commands:
            return None
        stripped = prompt.strip().lower()
        for dream_cmd in _DREAM_COMMANDS:
            if stripped == dream_cmd or stripped.startswith(dream_cmd + " "):
                now = datetime.now()
                return AgentResult(
                    success=False,
                    raw_output="",
                    summary=(
                        "Lobuddy 已接管长期记忆管理，nanobot Dream 命令在 Lobuddy 模式下禁用。"
                        "需要整理记忆时，请使用 Lobuddy 的记忆维护或审查入口。"
                    ),
                    error_message="Dream command disabled in Lobuddy mode",
                    started_at=now,
                    finished_at=now,
                )
        return None

    @staticmethod
    def _has_memory_signal(text: str) -> bool:
        lower = text.lower()
        signals = (
            "remember this",
            "remember that",
            "from now on",
            "i prefer",
            "i like",
            "i don't like",
            "i do not like",
            "always",
            "never",
            "my name is",
            "call me",
            "记住",
            "以后",
            "我叫",
            "我的名字",
            "请叫我",
            "我喜欢",
            "我不喜欢",
            "我偏好",
            "总是",
            "永远不要",
        )
        return any(signal in lower for signal in signals)

    @staticmethod
    def _extract_user_name(text: str) -> str | None:
        if NanobotAdapter._looks_like_identity_question(text):
            return None
        patterns = [
            r"(?:my name is|call me)\s+([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})",
            r"(?:我叫|我的名字是|请叫我)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                candidate = m.group(1).strip(" ，。,.!！?？")
                return None if NanobotAdapter._is_invalid_identity_value(candidate) else candidate
        return None

    @staticmethod
    def _extract_pet_name(text: str) -> str | None:
        if NanobotAdapter._looks_like_identity_question(text):
            return None
        patterns = [
            r"(?:your name is|i will call you|from now on you are)\s+([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})",
            r"(?:你叫|你的名字是|以后叫你|以后你叫|叫你)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                candidate = m.group(1).strip(" ，。,.!！?？")
                return None if NanobotAdapter._is_invalid_identity_value(candidate) else candidate
        return None

    @staticmethod
    def _looks_like_identity_question(text: str) -> bool:
        lower = text.lower()
        return any(
            phrase in lower
            for phrase in (
                "who am i",
                "who are you",
                "what is my name",
                "what's my name",
                "我是谁",
                "你是谁",
                "我叫什么",
                "你叫什么",
            )
        )

    @staticmethod
    def _is_invalid_identity_value(value: str) -> bool:
        normalized = value.strip().lower()
        return normalized in {
            "",
            "who",
            "what",
            "unknown",
            "谁",
            "什么",
        }

    async def _run_memory_update(self, session_key: str) -> None:
        if self._memory_service is None or self._memory_gateway is None:
            return
        try:
            from core.storage.chat_repo import ChatRepository
            from core.memory.memory_write_gateway import WriteContext

            chat_repo = ChatRepository()
            session_id = session_key.split(":")[-1] if ":" in session_key else session_key
            max_msgs = self.settings.memory_update_max_recent_messages
            messages = chat_repo.get_messages(session_id, limit=max_msgs)
            recent = [{"role": m.role, "content": m.content} for m in messages]
            if not recent:
                return

            update_prompt = self._memory_service.build_update_prompt(recent)

            config_path = self._create_temp_config(model=self.settings.llm_model)
            try:
                from nanobot import Nanobot

                bot = Nanobot.from_config(
                    config_path=config_path,
                    workspace=self.settings.workspace_path,
                )
                result = await asyncio.wait_for(
                    bot.run(update_prompt, session_key="profile_update"),
                    timeout=self.settings.task_timeout,
                )
                raw = result.content or ""
                if isinstance(raw, list):
                    raw = "\n".join(str(item) for item in raw)
                patch = self._memory_service.parse_ai_response_to_patch(raw)
                if patch is not None:
                    context = WriteContext(
                        source="ai_patch",
                        session_id=session_id,
                        triggered_by="adapter",
                    )
                    write_result = await self._memory_gateway.submit_patch(patch, context)
                    if write_result.accepted:
                        logger.info("Memory updated: accepted=%d", len(write_result.accepted))
                    else:
                        logger.debug("Memory update: all items rejected")
                else:
                    logger.debug("Memory update skipped: no valid patch parsed")
            finally:
                try:
                    if config_path.exists():
                        os.unlink(config_path)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Background memory update failed: {e}")

    def _find_similar_memory(
        self, content: str, memory_type: MemoryType = MemoryType.USER_PROFILE
    ):
        if self._memory_service is None:
            return None
        try:
            from core.memory.memory_schema import MemoryStatus

            items = self._memory_service.list_memories(
                memory_type, MemoryStatus.ACTIVE, limit=50
            )
            for item in items:
                if content in item.content or item.content in content:
                    return item
            return None
        except Exception:
            return None

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
                security_log.warning("Preflight guardrail block — prompt contains: %s", stripped[:80])
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
                gateway, image_path, self.subagent_factory
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
            "cannot read",
            "does not support image",
            "clipboard",
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
            "cannot read" in lowered
            or "does not support image" in lowered
            or "clipboard" in lowered
        ):
            return "当前模型不支持图片输入，请在高级设置里更换支持图片的模型（如 GPT-4o），或移除图片后重试。"
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
            task_log.error("Task API error — session=%s, %.2fs, error=%s", session_key, duration, error_detail[:120])
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
        task_log.info(
            "Task success — session=%s, %.2fs, output=%dB, tools=%s",
            session_key, duration, len(raw_output), tracker.tools_used,
        )
        clear_trace_id()
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
        duration = (finished_at - started_at).total_seconds()
        logger.warning(f"Task timeout for session={session_key}")
        task_log.warning("Task timeout — session=%s, %.2fs/%ds", session_key, duration, self.settings.task_timeout)
        clear_trace_id()
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

        # HumanApprovalDenied: friendly user-facing message
        if isinstance(exc, HumanApprovalDenied):
            clear_trace_id()
            return AgentResult(
                success=False,
                raw_output="",
                summary="已取消执行危险命令。命令没有运行。",
                error_message=safe_error,
                started_at=started_at,
                finished_at=finished_at,
            )

        is_api_error, error_detail = self._looks_like_api_error(safe_error)
        summary = (
            self._friendly_api_error_summary(error_detail)
            if is_api_error
            else "任务执行失败了，请稍后重试；如果持续失败，可以查看详情排查。"
        )
        logger.error(f"Task failed for session={session_key}: {safe_error}")
        task_log.error("Task error — session=%s, error=%s", session_key, safe_error[:200])
        clear_trace_id()
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
        session_search_tool: Any,
        resolver_tool: Any,
        open_tool: Any,
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
            if session_search_tool is not None:
                try:
                    gateway.unregister_tool(session_search_tool.name)
                    logger.debug("session_search tool unregistered for session=%s", session_key)
                except Exception as e:
                    logger.debug("Failed to unregister session_search tool: %s", e)
            if resolver_tool is not None:
                try:
                    gateway.unregister_tool(resolver_tool.name)
                except Exception as e:
                    logger.debug("Failed to unregister resolver tool: %s", e)
            if open_tool is not None:
                try:
                    gateway.unregister_tool(open_tool.name)
                except Exception as e:
                    logger.debug("Failed to unregister open tool: %s", e)

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
