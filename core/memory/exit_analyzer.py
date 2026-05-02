import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from core.config import Settings
from core.memory.memory_schema import MemoryItem, MemoryStatus, MemoryType
from core.memory.memory_service import MemoryService
from core.storage.chat_repo import ChatRepository

logger = logging.getLogger(__name__)

_EXIT_ANALYSIS_PROMPT = """分析以下对话，提取用户和宠物的身份信息以及用户明确表达的偏好。

**只提取以下内容**：
1. 用户的名字或称呼（如"小明"、"大哥"）
2. 宠物的名字（如"哈基宝"）
3. 用户明确说的偏好（如"我喜欢蓝色"、"别叫我亲"）

**忽略**：
- 临时性话题
- 工作任务细节
- 情绪表达
- 已经知道的信息（不要重复）

**输出格式**：JSON，只输出 JSON，不要有其他文字
{{
  "identities": [
    {{"type": "user_name", "value": "...", "confidence": 0.9}},
    {{"type": "pet_name", "value": "...", "confidence": 0.9}}
  ],
  "preferences": [
    {{"content": "...", "confidence": 0.8}}
  ]
}}

如果某类信息不存在，返回空数组。

**对话**：
{conversation}
"""


class ExitAnalyzer:
    def __init__(self, settings: Settings, memory_service: MemoryService) -> None:
        self._settings = settings
        self._memory_service = memory_service
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

        except Exception as e:
            logger.warning("Exit analysis failed: %s", e)
            return {"skipped": True, "reason": f"error: {e}"}

    async def _run_analysis(self, prompt: str) -> dict[str, Any] | None:
        try:
            from nanobot import Nanobot
            from core.agent.config_builder import build_nanobot_config, write_temp_config

            config = build_nanobot_config(
                self._settings,
                model=self._settings.llm_model,
                workspace=self._settings.workspace_path,
            )
            config_path = write_temp_config(config, self._settings.data_dir / "temp", "exit_analysis")

            try:
                bot = Nanobot.from_config(
                    config_path=config_path,
                    workspace=self._settings.workspace_path,
                )
                result = await asyncio.wait_for(
                    bot.run(prompt, session_key="exit_analysis"),
                    timeout=10,
                )
                raw = result.content or ""
                if isinstance(raw, list):
                    raw = "\n".join(str(item) for item in raw)

                return self._extract_json(raw)
            finally:
                try:
                    if config_path.exists():
                        import os
                        os.unlink(config_path)
                except Exception:
                    pass

        except Exception as e:
            logger.debug("Exit AI analysis failed: %s", e)
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
        value = item.get("value", "")
        confidence = item.get("confidence", 0.8)

        if not value or len(value) > 50:
            return None

        if identity_type == "user_name":
            existing = self._memory_service.search_memories(value, MemoryType.USER_PROFILE, limit=5)
            if any(value in m.content for m in existing):
                return None
            mem = MemoryItem(
                id=str(uuid.uuid4()),
                memory_type=MemoryType.USER_PROFILE,
                scope="global",
                title="Basic Notes",
                content=f"The user's name is {value}.",
                source="exit_analysis",
                confidence=confidence,
                importance=0.9,
                priority=90,
                status=MemoryStatus.ACTIVE,
            )
            self._memory_service.save_memory(mem)
            return mem

        if identity_type == "pet_name":
            existing = self._memory_service.search_memories(value, MemoryType.SYSTEM_PROFILE, limit=5)
            if any(value in m.content for m in existing):
                return None
            mem = MemoryItem(
                id=str(uuid.uuid4()),
                memory_type=MemoryType.SYSTEM_PROFILE,
                scope="global",
                title="Identity",
                content=f"My name is {value}. I am an AI desktop pet assistant.",
                source="exit_analysis",
                confidence=confidence,
                importance=0.9,
                priority=90,
                status=MemoryStatus.ACTIVE,
            )
            self._memory_service.save_memory(mem)
            return mem

        return None

    def _persist_preference(self, item: dict[str, Any]) -> MemoryItem | None:
        content = item.get("content", "")
        confidence = item.get("confidence", 0.8)

        if not content or len(content) > 200:
            return None

        existing = self._memory_service.search_memories(content, MemoryType.USER_PROFILE, limit=5)
        if any(content in m.content or m.content in content for m in existing):
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
