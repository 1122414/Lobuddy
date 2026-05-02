"""Structured memory service for Lobuddy."""

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Optional

from core.config import Settings
from core.memory.memory_projection import MemoryProjection
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    MemoryItem,
    MemoryPatch,
    MemoryPatchAction,
    MemoryPatchItem,
    MemoryStatus,
    MemoryType,
    PromptContextBundle,
)
from core.memory.memory_selector import MemorySelector

logger = logging.getLogger(__name__)

MEMORY_UPDATE_PROMPT = """Analyze the recent conversation and extract durable Lobuddy memory.

Return only JSON. The JSON must be either an object or an array of objects with:
- memory_type: one of user_profile, system_profile, project_memory, episodic_memory, procedural_memory
- action: add, update, remove, deprecate, merge, or uncertain
- title: short category title
- content: one concise memory sentence
- scope: global unless the memory is project-specific
- confidence: 0.0-1.0
- importance: 0.0-1.0
- reason: brief reason

Save only stable, useful facts that prevent the user from repeating themselves:
identity, preferences, communication style, current projects, durable decisions,
workflow habits, and important completed events. Do not save secrets, API keys,
ordinary chit-chat, or guesses. Mark uncertain items as action=uncertain.

Current structured memory:
{current_memory}

Recent conversation:
{conversation}
"""

_SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$")
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"xoxb-[a-zA-Z0-9-]+"),
    re.compile(r"Bearer\s+[a-zA-Z0-9._-]+"),
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
]


def _sanitize_memory_text(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text.strip()


def _extract_json(text: str) -> str | None:
    block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if block:
        return block.group(1).strip()

    start = text.find("[")
    if start != -1:
        end = text.rfind("]")
        if end > start:
            return text[start : end + 1]

    start = text.find("{")
    if start != -1:
        end = text.rfind("}")
        if end > start:
            return text[start : end + 1]
    return None


def _parse_legacy_user_md(text: str) -> list[tuple[str, str]]:
    """Parse the old USER.md projection into (section, item) pairs."""
    result: list[tuple[str, str]] = []
    current = "Basic Notes"
    for line in text.splitlines():
        header = _SECTION_HEADER_RE.match(line)
        if header:
            current = header.group(1).strip() or "Basic Notes"
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            item = stripped[2:].strip()
            if item:
                result.append((current, item))
    return result


class MemoryService:
    """Orchestrates structured memory storage, projection, and prompt context injection."""

    def __init__(self, settings: Settings, repo: MemoryRepository | None = None) -> None:
        self._settings = settings
        self._repo = repo or MemoryRepository()
        self._projection = MemoryProjection(settings.data_dir, settings.workspace_path)
        self._selector = MemorySelector(settings, self._repo)
        if settings.memory_enable_migration:
            self._maybe_migrate_from_legacy()
        self._deprecate_invalid_identity_memories()
        self._ensure_bootstrap_memories()

    def save_memory(self, item: MemoryItem) -> MemoryItem:
        item.content = _sanitize_memory_text(item.content)
        item.updated_at = datetime.now()
        saved = self._repo.save(item)
        self._refresh_projections()
        return saved

    def save_memories(self, items: list[MemoryItem]) -> list[MemoryItem]:
        saved = []
        for item in items:
            item.content = _sanitize_memory_text(item.content)
            item.updated_at = datetime.now()
            saved.append(self._repo.save(item))
        self._refresh_projections()
        return saved

    def get_memory(self, item_id: str) -> Optional[MemoryItem]:
        return self._repo.get(item_id)

    def list_memories(
        self,
        memory_type: MemoryType,
        status: Optional[MemoryStatus] = None,
        scope: Optional[str] = None,
        limit: int = 100,
    ) -> list[MemoryItem]:
        return self._repo.list_by_type(memory_type, status, scope, limit)

    def search_memories(
        self,
        keyword: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        return self._repo.search_by_keyword(keyword, memory_type, limit)

    def deprecate_memory(self, item_id: str) -> bool:
        ok = self._repo.update_status(item_id, MemoryStatus.DEPRECATED)
        if ok:
            self._refresh_projections()
        return ok

    def delete_memory(self, item_id: str) -> bool:
        ok = self._repo.delete(item_id)
        if ok:
            self._refresh_projections()
        return ok

    def apply_patch(self, patch: MemoryPatch) -> tuple[list[MemoryItem], list[MemoryPatchItem]]:
        accepted: list[MemoryItem] = []
        rejected: list[MemoryPatchItem] = []
        min_confidence = getattr(self._settings, "memory_min_confidence", 0.75)

        for item in patch.items:
            if item.action == MemoryPatchAction.UNCERTAIN:
                rejected.append(item)
                continue
            if item.confidence < min_confidence:
                rejected.append(item)
                continue

            content = _sanitize_memory_text(item.content)
            if not content:
                rejected.append(item)
                continue

            existing = self._find_similar(item.memory_type, content)
            if item.action in {MemoryPatchAction.ADD, MemoryPatchAction.UPDATE, MemoryPatchAction.MERGE}:
                if existing:
                    existing.content = content
                    existing.title = item.title or existing.title
                    existing.scope = item.scope or existing.scope
                    existing.confidence = max(existing.confidence, item.confidence)
                    existing.importance = max(existing.importance, item.importance)
                    existing.priority = self._priority_for(item.importance, item.memory_type)
                    existing.status = MemoryStatus.ACTIVE
                    accepted.append(self._repo.save(existing))
                else:
                    accepted.append(
                        self._repo.save(
                            MemoryItem(
                                id=str(uuid.uuid4()),
                                memory_type=item.memory_type,
                                scope=item.scope,
                                title=item.title,
                                content=content,
                                source="ai",
                                confidence=item.confidence,
                                importance=item.importance,
                                priority=self._priority_for(item.importance, item.memory_type),
                            )
                        )
                    )
            elif item.action in {MemoryPatchAction.REMOVE, MemoryPatchAction.DEPRECATE}:
                if existing:
                    self._repo.update_status(existing.id, MemoryStatus.DEPRECATED)
                    accepted.append(existing)
                else:
                    rejected.append(item)

        if accepted:
            self._refresh_projections()
        return accepted, rejected

    def apply_ai_response(self, ai_response: str) -> tuple[bool, str]:
        try:
            json_str = _extract_json(ai_response)
            if not json_str:
                return False, "No JSON found in response"

            data = json.loads(json_str)
            raw_items = [data] if isinstance(data, dict) else data
            if not isinstance(raw_items, list):
                return False, "Invalid JSON format"

            max_items = getattr(self._settings, "memory_update_max_patch_items", 8)
            patch_items: list[MemoryPatchItem] = []
            for raw in raw_items[:max_items]:
                try:
                    patch_items.append(MemoryPatchItem(**raw))
                except Exception as exc:
                    logger.warning("Skipping invalid memory patch item: %s", exc)

            if not patch_items:
                return False, "No valid patch items"

            accepted, rejected = self.apply_patch(MemoryPatch(items=patch_items))
            if not accepted:
                return False, f"All {len(rejected)} items rejected"
            message = f"Updated {len(accepted)} memory items"
            if rejected:
                message += f", rejected {len(rejected)}"
            return True, message
        except json.JSONDecodeError as exc:
            return False, f"Invalid JSON: {exc}"
        except Exception as exc:
            logger.warning("Memory AI response failed: %s", exc)
            return False, f"Error: {exc}"

    def build_update_prompt(self, recent_messages: list[dict[str, str]]) -> str:
        current = self.build_prompt_context().build_injection_text() or "(empty)"
        conversation = "\n".join(
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
            for msg in recent_messages
        )
        return MEMORY_UPDATE_PROMPT.format(current_memory=current, conversation=conversation)

    def build_prompt_context(
        self, user_message: str = "", session_id: str = ""
    ) -> PromptContextBundle:
        return self._selector.select_for_prompt(user_message, session_id)

    def upsert_identity_memory(
        self,
        *,
        memory_type: MemoryType,
        title: str,
        content: str,
        source: str,
        confidence: float = 0.95,
        importance: float = 0.9,
    ) -> MemoryItem:
        content = _sanitize_memory_text(content)
        if self._is_invalid_identity_memory(content):
            raise ValueError(f"Refusing invalid identity memory: {content}")
        existing = self._find_similar(memory_type, content)
        if existing:
            return existing

        if memory_type in {MemoryType.USER_PROFILE, MemoryType.SYSTEM_PROFILE}:
            for item in self._repo.list_by_type(memory_type, MemoryStatus.ACTIVE, limit=100):
                if item.title == title and item.source == source and item.content != content:
                    self._repo.update_status(item.id, MemoryStatus.DEPRECATED)

        item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=memory_type,
            scope="global",
            title=title,
            content=content,
            source=source,
            confidence=confidence,
            importance=importance,
            priority=self._priority_for(importance, memory_type),
        )
        saved = self._repo.save(item)
        self._refresh_projections()
        return saved

    def _find_similar(self, memory_type: MemoryType, content: str) -> Optional[MemoryItem]:
        items = self._repo.list_by_type(memory_type, MemoryStatus.ACTIVE, limit=100)
        for item in items:
            if content in item.content or item.content in content:
                return item
        return None

    def _refresh_projections(self) -> None:
        try:
            all_items: list[MemoryItem] = []
            for mt in MemoryType:
                all_items.extend(self._repo.list_by_type(mt, limit=1000))
            self._projection.project_all(all_items)
        except Exception as exc:
            logger.warning("Projection refresh failed: %s", exc)

    def _maybe_migrate_from_legacy(self) -> None:
        profile_path = self._settings.memory_profile_file
        if not profile_path.exists():
            return
        try:
            if self._repo.list_by_type(MemoryType.USER_PROFILE, limit=1):
                return
            legacy_items = _parse_legacy_user_md(profile_path.read_text(encoding="utf-8"))
            migrated = 0
            for section, content in legacy_items:
                clean = _sanitize_memory_text(content)
                if not clean:
                    continue
                self._repo.save(
                    MemoryItem(
                        id=str(uuid.uuid4()),
                        memory_type=MemoryType.USER_PROFILE,
                        scope="global",
                        title=section,
                        content=clean,
                        source="migration",
                        confidence=0.9,
                        importance=0.7,
                        priority=70,
                    )
                )
                migrated += 1
            if migrated > 0:
                logger.info("Migrated %d items from legacy USER.md", migrated)
                backup = profile_path.with_suffix(".md.bak")
                try:
                    profile_path.rename(backup)
                except OSError:
                    pass
                self._refresh_projections()
        except Exception as exc:
            logger.warning("Legacy migration failed: %s", exc)

    def _ensure_bootstrap_memories(self) -> None:
        try:
            pet_name = self._settings.pet_name or "Lobuddy"
            expected_system = f"My name is {pet_name}. I am an AI desktop pet assistant."
            system_items = self._repo.list_by_type(MemoryType.SYSTEM_PROFILE, MemoryStatus.ACTIVE, limit=100)
            bootstrap_system = [item for item in system_items if item.source == "bootstrap"]
            if bootstrap_system:
                for item in bootstrap_system:
                    if item.content != expected_system:
                        item.content = expected_system
                        item.updated_at = datetime.now()
                        self._repo.save(item)
            else:
                self._repo.save(
                    MemoryItem(
                        id=str(uuid.uuid4()),
                        memory_type=MemoryType.SYSTEM_PROFILE,
                        scope="global",
                        title="Identity",
                        content=expected_system,
                        source="bootstrap",
                        confidence=1.0,
                        importance=0.9,
                        priority=90,
                    )
                )

            user_name = self._settings.user_name.strip()
            user_items = self._repo.list_by_type(MemoryType.USER_PROFILE, MemoryStatus.ACTIVE, limit=100)
            bootstrap_user = [item for item in user_items if item.source == "bootstrap"]
            if user_name:
                expected_user = f"The user's name is {user_name}."
                if bootstrap_user:
                    for item in bootstrap_user:
                        if item.content != expected_user:
                            item.content = expected_user
                            item.updated_at = datetime.now()
                            self._repo.save(item)
                else:
                    self._repo.save(
                        MemoryItem(
                            id=str(uuid.uuid4()),
                            memory_type=MemoryType.USER_PROFILE,
                            scope="global",
                            title="Basic Notes",
                            content=expected_user,
                            source="bootstrap",
                            confidence=1.0,
                            importance=0.9,
                            priority=90,
                        )
                    )
            else:
                for item in bootstrap_user:
                    self._repo.update_status(item.id, MemoryStatus.DEPRECATED)

            self._refresh_projections()
        except Exception as exc:
            logger.warning("Bootstrap memories failed: %s", exc)

    def refresh_bootstrap_memories(self) -> None:
        self._deprecate_invalid_identity_memories()
        self._ensure_bootstrap_memories()

    def resolve_conflicts(self, memory_type: MemoryType, scope: str = "global") -> int:
        resolved = 0
        try:
            items = self._repo.list_by_type(memory_type, MemoryStatus.ACTIVE, scope, limit=100)
            by_content: dict[str, list[MemoryItem]] = {}
            for item in items:
                key = f"{item.title}:{item.content[:80]}"
                by_content.setdefault(key, []).append(item)

            for group in by_content.values():
                if len(group) < 2:
                    continue
                group.sort(key=lambda x: x.confidence, reverse=True)
                winner = group[0]
                for item in group[1:]:
                    if item.confidence >= winner.confidence:
                        self._repo.update_status(item.id, MemoryStatus.NEEDS_REVIEW)
                    else:
                        self._repo.update_status(item.id, MemoryStatus.DEPRECATED)
                    resolved += 1
            if resolved > 0:
                self._refresh_projections()
        except Exception as exc:
            logger.warning("Conflict resolution failed: %s", exc)
        return resolved

    def cleanup_expired(self) -> int:
        cleaned = 0
        try:
            for mt in MemoryType:
                items = self._repo.list_by_type(mt, MemoryStatus.ACTIVE, limit=1000)
                for item in items:
                    if item.is_expired():
                        self._repo.update_status(item.id, MemoryStatus.DEPRECATED)
                        cleaned += 1
            if cleaned > 0:
                self._refresh_projections()
        except Exception as exc:
            logger.warning("Expired cleanup failed: %s", exc)
        return cleaned

    def _deprecate_invalid_identity_memories(self) -> int:
        deprecated = 0
        try:
            for memory_type in (MemoryType.USER_PROFILE, MemoryType.SYSTEM_PROFILE):
                items = self._repo.list_by_type(memory_type, MemoryStatus.ACTIVE, limit=1000)
                for item in items:
                    if self._is_invalid_identity_memory(item.content):
                        self._repo.update_status(item.id, MemoryStatus.DEPRECATED)
                        deprecated += 1
            if deprecated:
                self._refresh_projections()
        except Exception as exc:
            logger.warning("Invalid identity cleanup failed: %s", exc)
        return deprecated

    @staticmethod
    def _priority_for(importance: float, memory_type: MemoryType) -> int:
        base = 50 + int(max(0.0, min(1.0, importance)) * 40)
        if memory_type in {MemoryType.USER_PROFILE, MemoryType.SYSTEM_PROFILE}:
            base += 10
        return max(1, min(100, base))

    @staticmethod
    def _is_invalid_identity_memory(content: str) -> bool:
        normalized = content.strip().lower().rstrip(".。!！?？")
        invalid_values = {"who", "what", "unknown", "谁", "什么"}
        if normalized in invalid_values:
            return True
        for prefix in ("the user's name is ", "my name is "):
            if normalized.startswith(prefix):
                value = normalized[len(prefix):].split(".", 1)[0].strip()
                return value in invalid_values
        return False
