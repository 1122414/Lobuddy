import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.config import Settings
from core.agent.config_builder import build_nanobot_config, write_temp_config
from core.agent.subagent_spec import SubagentSpec
from core.events.bus import EventBus
from core.events.events import SubagentCompleted, SubagentSpawned

logger = logging.getLogger("lobuddy.subagent_factory")


class SubagentFactory:
    def __init__(self, settings: Settings, event_bus: EventBus | None = None):
        self.settings = settings
        self.event_bus = event_bus

    def _get_spec(self, subagent_type: str) -> SubagentSpec:
        if subagent_type == "image_analysis":
            return SubagentSpec(
                model=self.settings.llm_multimodal_model,
                base_url=self.settings.llm_multimodal_base_url or None,
                api_key=self.settings.llm_multimodal_api_key or None,
                system_prompt=(
                    "You are an image analysis expert. "
                    "Describe the image accurately and concisely based on the user's request."
                ),
                max_iterations=self.settings.nanobot_max_iterations,
            )
        raise ValueError(f"Unknown subagent type: {subagent_type}")

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
            if spec.system_prompt:
                agent_defaults["systemPrompt"] = spec.system_prompt
            if spec.max_iterations is not None:
                agent_defaults["maxToolIterations"] = spec.max_iterations
            if spec.temperature is not None:
                agent_defaults["temperature"] = spec.temperature
            if spec.extra_config:
                config.update(spec.extra_config)

            config_path = write_temp_config(config, temp_workspace / "config", subagent_type)

            from nanobot import Nanobot
            from nanobot.bus.events import InboundMessage

            bot = Nanobot.from_config(config_path=config_path, workspace=temp_workspace)

            msg = InboundMessage(
                channel="cli",
                sender_id="user",
                chat_id="direct",
                content=prompt,
                media=media_paths or [],
            )

            response = await bot._loop._process_message(msg, session_key=effective_session_key)
            output = (response.content if response else None) or ""

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
