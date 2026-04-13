import asyncio
import json
import logging
import multiprocessing as mp
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

from app.config import Settings
from core.agent.config_builder import build_nanobot_config, write_temp_config
from core.agent.subagent_spec import SubagentSpec
from core.events.bus import EventBus
from core.events.events import SubagentCompleted, SubagentSpawned

logger = logging.getLogger("lobuddy.subagent_factory")


def _run_subagent_worker_process(
    config_path: Path,
    workspace: Path,
    session_key: str,
    prompt: str,
    media_paths: list[str] | None,
    system_prompt: str | None,
    result_path: str,
) -> None:
    test_script_path = os.environ.get("LOBUDDY_SUBAGENT_TEST_SCRIPT")
    if test_script_path:
        with open(test_script_path, "r", encoding="utf-8") as f:
            test_script = json.load(f)
            test_responses = test_script.get("responses", [])

        from nanobot.agent.runner import AgentRunner

        async def _scripted_request_model(self, spec, messages, hook, context):
            from nanobot.providers.base import LLMResponse, ToolCallRequest

            if not test_responses:
                raise RuntimeError("Test script exhausted")
            resp = test_responses.pop(0)
            if resp.get("__raise"):
                raise RuntimeError(resp["__raise"])
            tool_calls = [ToolCallRequest(**tc) for tc in resp.get("tool_calls", [])]
            return LLMResponse(
                content=resp.get("content"),
                tool_calls=tool_calls,
                finish_reason=resp.get("finish_reason", "stop"),
            )

        AgentRunner._request_model = _scripted_request_model

    async def _async_run() -> str:
        from nanobot import Nanobot
        from nanobot.bus.events import InboundMessage

        bot = Nanobot.from_config(config_path=config_path, workspace=workspace)

        temp_system_msg = None
        if system_prompt:
            session = bot._loop.sessions.get_or_create(session_key)
            temp_system_msg = {"role": "system", "content": system_prompt}
            session.messages.append(temp_system_msg)
            bot._loop.sessions.save(session)

        msg = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content=prompt,
            media=media_paths or [],
        )

        try:
            response = await bot._loop._process_message(msg, session_key=session_key)
            output = (response.content if response else None) or ""
        finally:
            if temp_system_msg:
                session = bot._loop.sessions.get_or_create(session_key)
                session.messages = [
                    m
                    for m in session.messages
                    if not (
                        isinstance(m, dict)
                        and m.get("role") == "system"
                        and m.get("content") == temp_system_msg["content"]
                    )
                ]
                bot._loop.sessions.save(session)
        return output

    try:
        output = asyncio.run(_async_run())
        result: dict[str, Any] = {"success": True, "output": output}
    except Exception as exc:
        result = {"success": False, "error": str(exc)}

    if os.environ.get("LOBUDDY_SUBAGENT_RETURN_META"):
        result["_meta"] = {"pid": os.getpid()}

    if os.environ.get("LOBUDDY_SUBAGENT_CAPTURE_DETAILS"):
        result["_details"] = {
            "session_key": session_key,
            "media_paths": media_paths or [],
            "system_prompt_injected": bool(system_prompt),
            "system_prompt_content": system_prompt,
        }

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f)


class SubagentFactory:
    DEFAULT_REGISTRY: dict[str, Callable[[Settings], SubagentSpec]] = {
        "image_analysis": lambda s: SubagentSpec(
            model=s.llm_multimodal_model,
            base_url=s.llm_multimodal_base_url or None,
            api_key=s.llm_multimodal_api_key or None,
            system_prompt=(
                "You are an image analysis expert. "
                "Describe the image accurately and concisely based on the user's request."
            ),
            max_iterations=s.nanobot_max_iterations,
        ),
    }

    def __init__(
        self,
        settings: Settings,
        event_bus: EventBus | None = None,
        registry: dict[str, Callable[[Settings], SubagentSpec]] | None = None,
    ):
        self.settings = settings
        self.event_bus = event_bus
        self._registry = registry if registry is not None else dict(self.DEFAULT_REGISTRY)
        self._last_raw_result: dict[str, Any] | None = None

    def _get_spec(self, subagent_type: str) -> SubagentSpec:
        if subagent_type not in self._registry:
            raise ValueError(f"Unknown subagent type: {subagent_type}")
        return self._registry[subagent_type](self.settings)

    async def run_subagent(
        self,
        subagent_type: str,
        prompt: str,
        session_key: str | None = None,
        media_paths: list[str] | None = None,
    ) -> str:
        spec = self._get_spec(subagent_type)
        if not spec.model:
            raise ValueError(f"Sub-agent '{subagent_type}' is not configured: missing model name")

        task_id = str(uuid.uuid4())
        temp_workspace = Path(tempfile.mkdtemp(prefix=f"lobuddy_{subagent_type}_"))
        effective_session_key = session_key or f"subagent:{subagent_type}:{task_id}"
        result_path = temp_workspace / "result.json"

        if self.event_bus:
            self.event_bus.publish(SubagentSpawned(subagent_type, task_id, temp_workspace))

        try:
            effective_settings = self.settings.model_copy()
            effective_settings.llm_model = spec.model
            if spec.base_url is not None:
                effective_settings.llm_base_url = spec.base_url
            if spec.api_key is not None:
                effective_settings.llm_api_key = spec.api_key

            config = build_nanobot_config(effective_settings, spec.model, temp_workspace)

            agent_defaults = config.setdefault("agents", {}).setdefault("defaults", {})
            if spec.max_iterations is not None:
                agent_defaults["maxToolIterations"] = spec.max_iterations
            if spec.temperature is not None:
                agent_defaults["temperature"] = spec.temperature
            if spec.extra_config:
                config.update(spec.extra_config)

            config_path = write_temp_config(config, temp_workspace / "config", subagent_type)

            process = mp.Process(
                target=_run_subagent_worker_process,
                kwargs={
                    "config_path": config_path,
                    "workspace": temp_workspace,
                    "session_key": effective_session_key,
                    "prompt": prompt,
                    "media_paths": media_paths,
                    "system_prompt": spec.system_prompt,
                    "result_path": str(result_path),
                },
                daemon=True,
            )
            process.start()

            timeout = self.settings.task_timeout or 120
            elapsed = 0.0
            poll_interval = 0.05
            while elapsed < timeout:
                if result_path.exists():
                    break
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

            if not result_path.exists():
                process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)
                raise TimeoutError(f"Sub-agent '{subagent_type}' timed out after {timeout}s")

            with open(result_path, "r", encoding="utf-8") as f:
                raw = json.load(f)

            self._last_raw_result = raw

            if not raw.get("success"):
                raise RuntimeError(raw.get("error", "Unknown subagent failure"))
            output = raw.get("output", "")

            if self.event_bus:
                self.event_bus.publish(SubagentCompleted(subagent_type, task_id, True, output))
            return output

        except Exception as exc:
            logger.exception("Sub-agent %s failed", subagent_type)
            if self.event_bus:
                self.event_bus.publish(SubagentCompleted(subagent_type, task_id, False, str(exc)))
            raise
        finally:
            shutil.rmtree(temp_workspace, ignore_errors=True)

    async def run_image_analysis(self, prompt: str, image_path: str) -> str:
        return await self.run_subagent(
            "image_analysis",
            prompt,
            media_paths=[image_path],
        )
