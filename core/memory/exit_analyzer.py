"""Session-end memory extraction."""

import asyncio
import json
import logging
import os
import uuid
from typing import Any

from core.config import Settings
from core.memory.memory_schema import MemoryItem, MemoryStatus, MemoryType
from core.memory.memory_service import MemoryService
from core.memory.memory_write_gateway import MemoryWriteGateway, WriteContext
from core.storage.chat_repo import ChatRepository

logger = logging.getLogger(__name__)

_EXIT_ANALYSIS_PROMPT = """Analyze the final part of this Lobuddy conversation.

Return only JSON in this shape:
{
  "identities": [
    {"type": "user_name", "value": "...", "confidence": 0.9},
    {"type": "pet_name", "value": "...", "confidence": 0.9}
  ],
  "preferences": [
    {"content": "The user prefers concise Chinese explanations.", "confidence": 0.8}
  ]
}

Only include durable, explicit facts. Skip guesses, secrets, API keys, passwords,
temporary requests, and ordinary chit-chat.

Conversation:
{conversation}
"""


class ExitAnalyzer:
    def __init__(
        self,
        settings: Settings,
        memory_service: MemoryService,
        gateway: MemoryWriteGateway | None = None,
    ) -> None:
        self._settings = settings
        self._memory_service = memory_service
        self._gateway = gateway  # 5.3: All writes go through gateway
        self._chat_repo = ChatRepository()

    def analyze_and_persist(self, session_id: str) -> dict[str, Any]:
        try:
            messages = self._chat_repo.get_messages(session_id, limit=50)
            if len(messages) < self._settings.exit_analysis_min_messages:
                logger.debug("Too few messages (%d) for exit analysis", len(messages))
                return {"skipped": True, "reason": "too_few_messages"}

            conversation = "\n".join(
                f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}"
                for m in messages[-20:]
            )

            prompt = _EXIT_ANALYSIS_PROMPT.format(conversation=conversation)
            result = asyncio.run(self._run_analysis(prompt))
            if not result:
                return {"skipped": True, "reason": "analysis_failed"}

            persisted = self._persist_result(result)
            logger.info("Exit analysis persisted %d items", len(persisted))
            return {"skipped": False, "persisted": len(persisted)}

        except Exception as exc:
            logger.warning("Exit analysis failed: %s", exc)
            return {"skipped": True, "reason": f"error: {exc}"}

    async def _run_analysis(self, prompt: str) -> dict[str, Any] | None:
        try:
            from nanobot import Nanobot
            from core.agent.config_builder import build_nanobot_config, write_temp_config

            config = build_nanobot_config(
                self._settings,
                model=self._settings.llm_model,
                workspace=self._settings.workspace_path,
            )
            config_path = write_temp_config(
                config, self._settings.data_dir / "temp", "exit_analysis"
            )

            try:
                bot = Nanobot.from_config(
                    config_path=config_path,
                    workspace=self._settings.workspace_path,
                )
                result = await asyncio.wait_for(
                    bot.run(prompt, session_key="exit_analysis"),
                    timeout=2.5,
                )
                raw = result.content or ""
                if isinstance(raw, list):
                    raw = "\n".join(str(item) for item in raw)
                return self._extract_json(raw)
            finally:
                try:
                    if config_path.exists():
                        os.unlink(config_path)
                except OSError:
                    pass

        except Exception as exc:
            logger.debug("Exit AI analysis failed: %s", exc)
            return None

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        start = text.find("{")
        if start == -1:
            return None
        end = text.rfind("}")
        if end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None

    def _persist_result(self, result: dict[str, Any]) -> list[MemoryItem]:
        persisted: list[MemoryItem] = []

        for item in result.get("identities", []):
            mem = self._persist_identity(item)
            if mem:
                persisted.append(mem)

        for item in result.get("preferences", []):
            mem = self._persist_preference(item)
            if mem:
                persisted.append(mem)

        return persisted

    def _persist_identity(self, item: dict[str, Any]) -> MemoryItem | None:
        identity_type = item.get("type", "")
        value = str(item.get("value", "")).strip()
        confidence = float(item.get("confidence", 0.8))

        if not value or len(value) > 50:
            return None

        context = WriteContext(
            source="exit_analysis",
            triggered_by="exit_analysis",
        )

        if identity_type == "user_name":
            if self._gateway is not None:
                return self._gateway.submit_identity_memory(
                    memory_type=MemoryType.USER_PROFILE,
                    title="Basic Notes",
                    content=f"The user's name is {value}.",
                    context=context,
                    confidence=confidence,
                )
            return self._memory_service.upsert_identity_memory(
                memory_type=MemoryType.USER_PROFILE,
                title="Basic Notes",
                content=f"The user's name is {value}.",
                source="exit_analysis",
                confidence=confidence,
            )

        if identity_type == "pet_name":
            if self._gateway is not None:
                return self._gateway.submit_identity_memory(
                    memory_type=MemoryType.SYSTEM_PROFILE,
                    title="Identity",
                    content=f"My name is {value}. I am an AI desktop pet assistant.",
                    context=context,
                    confidence=confidence,
                )
            return self._memory_service.upsert_identity_memory(
                memory_type=MemoryType.SYSTEM_PROFILE,
                title="Identity",
                content=f"My name is {value}. I am an AI desktop pet assistant.",
                source="exit_analysis",
                confidence=confidence,
            )

        return None

    def _persist_preference(self, item: dict[str, Any]) -> MemoryItem | None:
        content = str(item.get("content", "")).strip()
        confidence = float(item.get("confidence", 0.8))

        if not content or len(content) > 200:
            return None

        existing = self._memory_service.search_memories(
            content, MemoryType.USER_PROFILE, limit=5
        )
        if any(content in mem.content or mem.content in content for mem in existing):
            return None

        if self._gateway is not None:
            from core.memory.memory_schema import MemoryPatch, MemoryPatchItem, MemoryPatchAction

            context = WriteContext(
                source="exit_analysis",
                triggered_by="exit_analysis",
            )
            patch = MemoryPatch(items=[
                MemoryPatchItem(
                    memory_type=MemoryType.USER_PROFILE,
                    action=MemoryPatchAction.ADD,
                    content=content,
                    confidence=confidence,
                    importance=0.7,
                    title="Preferences",
                )
            ])
            result = asyncio.run(self._gateway.submit_patch(patch, context))
            if result.accepted:
                return result.accepted[0]
            return None

        mem = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            scope="global",
            title="Preferences",
            content=content,
            source="exit_analysis",
            confidence=confidence,
            importance=0.7,
            priority=70,
            status=MemoryStatus.ACTIVE,
        )
        self._memory_service.save_memory(mem)
        return mem
