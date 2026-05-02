"""Memory service facade — orchestrates repository, projection, and prompt context."""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.config import Settings
from core.memory.memory_projection import MemoryProjection
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    MemoryItem,
    MemoryPatch,
    MemoryPatchAction,
    MemoryStatus,
    MemoryType,
    PromptContextBundle,
)
from core.memory.memory_selector import MemorySelector
from core.memory.user_profile_manager import UserProfileManager
from core.memory.user_profile_schema import ProfilePatch, ProfileSection

logger = logging.getLogger(__name__)


class MemoryService:
    """Orchestrates memory storage, projection, and prompt context injection."""

    def __init__(self, settings: Settings, repo: MemoryRepository | None = None) -> None:
        self._settings = settings
        self._repo = repo or MemoryRepository()
        self._projection = MemoryProjection(settings.data_dir, settings.workspace_path)
        self._profile_manager = UserProfileManager(settings.memory_profile_file)
        self._selector = MemorySelector(settings, self._repo)
        self._ensure_bootstrap_memories()
        if settings.memory_enable_migration:
            self._maybe_migrate_from_legacy()

    def save_memory(self, item: MemoryItem) -> MemoryItem:
        item.updated_at = datetime.now()
        saved = self._repo.save(item)
        self._refresh_projections()
        return saved

    def save_memories(self, items: list[MemoryItem]) -> list[MemoryItem]:
        saved = []
        for item in items:
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
        return self._repo.update_status(item_id, MemoryStatus.DEPRECATED)

    def delete_memory(self, item_id: str) -> bool:
        return self._repo.delete(item_id)

    def apply_patch(self, patch: MemoryPatch) -> tuple[list[MemoryItem], list[MemoryPatch]]:
        accepted: list[MemoryItem] = []
        rejected: list[MemoryPatch] = []
        for item in patch.items:
            if item.action == MemoryPatchAction.UNCERTAIN:
                rejected.append(item)
                continue
            if item.confidence < self._settings.memory_profile_min_confidence:
                rejected.append(item)
                continue
            if item.action == MemoryPatchAction.ADD:
                mem = MemoryItem(
                    id=str(uuid.uuid4()),
                    memory_type=item.memory_type,
                    scope=item.scope,
                    title=item.title,
                    content=item.content,
                    confidence=item.confidence,
                    importance=item.importance,
                )
                accepted.append(self._repo.save(mem))
            elif item.action == MemoryPatchAction.REMOVE:
                existing = self._find_similar(item.memory_type, item.content)
                if existing:
                    self._repo.update_status(existing.id, MemoryStatus.DEPRECATED)
                    accepted.append(existing)
        self._refresh_projections()
        return accepted, rejected

    def build_prompt_context(self, user_message: str = "", session_id: str = "") -> PromptContextBundle:
        return self._selector.select_for_prompt(user_message, session_id)

    def _find_similar(self, memory_type: MemoryType, content: str) -> Optional[MemoryItem]:
        items = self._repo.list_by_type(memory_type, MemoryStatus.ACTIVE, limit=50)
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
        except Exception as e:
            logger.warning("Projection refresh failed: %s", e)

    def _maybe_migrate_from_legacy(self) -> None:
        profile_path = self._settings.memory_profile_file
        if not profile_path.exists():
            return
        try:
            existing = self._repo.list_by_type(MemoryType.USER_PROFILE, limit=1)
            if existing:
                return
        except Exception:
            pass
        try:
            profile = self._profile_manager.load_profile()
            migrated = 0
            for section, items in profile.sections.items():
                for content in items:
                    if not content.strip():
                        continue
                    mem = MemoryItem(
                        id=str(uuid.uuid4()),
                        memory_type=MemoryType.USER_PROFILE,
                        scope="global",
                        title=section.value,
                        content=content,
                        source="migration",
                        confidence=0.9,
                        importance=0.7,
                    )
                    self._repo.save(mem)
                    migrated += 1
            if migrated > 0:
                logger.info("Migrated %d items from legacy USER.md", migrated)
                backup = profile_path.with_suffix(".md.bak")
                try:
                    profile_path.rename(backup)
                except OSError:
                    pass
                self._refresh_projections()
        except Exception as e:
            logger.warning("Legacy migration failed: %s", e)

    def _ensure_bootstrap_memories(self) -> None:
        try:
            existing_system = self._repo.list_by_type(MemoryType.SYSTEM_PROFILE, MemoryStatus.ACTIVE, limit=1)
            if not existing_system:
                pet_name = self._settings.pet_name or "Lobuddy"
                mem = MemoryItem(
                    id=str(uuid.uuid4()),
                    memory_type=MemoryType.SYSTEM_PROFILE,
                    scope="global",
                    title="Identity",
                    content=f"My name is {pet_name}. I am an AI desktop pet assistant.",
                    source="bootstrap",
                    confidence=1.0,
                    importance=0.9,
                    priority=90,
                )
                self._repo.save(mem)
                logger.info("Bootstrapped system memory with pet name: %s", pet_name)
            user_name = self._settings.user_name
            if user_name and user_name.strip():
                existing_user = self._repo.search_by_keyword(user_name, MemoryType.USER_PROFILE, limit=5)
                has_exact = any(user_name in item.content for item in existing_user)
                if not has_exact:
                    mem = MemoryItem(
                        id=str(uuid.uuid4()),
                        memory_type=MemoryType.USER_PROFILE,
                        scope="global",
                        title="Basic Notes",
                        content=f"The user's name is {user_name}.",
                        source="bootstrap",
                        confidence=1.0,
                        importance=0.9,
                        priority=90,
                    )
                    self._repo.save(mem)
                    logger.info("Bootstrapped user profile with name: %s", user_name)
            self._refresh_projections()
        except Exception as e:
            logger.warning("Bootstrap memories failed: %s", e)

    def refresh_bootstrap_memories(self) -> None:
        try:
            pet_name = self._settings.pet_name or "Lobuddy"
            system_items = self._repo.list_by_type(MemoryType.SYSTEM_PROFILE, MemoryStatus.ACTIVE, limit=10)
            bootstrap_system = [i for i in system_items if i.source == "bootstrap"]
            if bootstrap_system:
                expected = f"My name is {pet_name}. I am an AI desktop pet assistant."
                for item in bootstrap_system:
                    if item.content != expected:
                        item.content = expected
                        item.updated_at = datetime.now()
                        self._repo.save(item)
                        logger.info("Updated system memory with new pet name: %s", pet_name)
            user_name = self._settings.user_name
            user_items = self._repo.list_by_type(MemoryType.USER_PROFILE, MemoryStatus.ACTIVE, limit=10)
            bootstrap_user = [i for i in user_items if i.source == "bootstrap"]
            if user_name and user_name.strip():
                expected = f"The user's name is {user_name}."
                found = False
                for item in bootstrap_user:
                    if item.content != expected:
                        item.content = expected
                        item.updated_at = datetime.now()
                        self._repo.save(item)
                        logger.info("Updated user memory with new name: %s", user_name)
                    found = True
                if not found:
                    mem = MemoryItem(
                        id=str(uuid.uuid4()),
                        memory_type=MemoryType.USER_PROFILE,
                        scope="global",
                        title="Basic Notes",
                        content=expected,
                        source="bootstrap",
                        confidence=1.0,
                        importance=0.9,
                    )
                    self._repo.save(mem)
                    logger.info("Bootstrapped user profile with name: %s", user_name)
            else:
                for item in bootstrap_user:
                    self._repo.update_status(item.id, MemoryStatus.DEPRECATED)
                    logger.info("Deprecated bootstrap user memory: %s", item.content)
            self._refresh_projections()
        except Exception as e:
            logger.warning("Refresh bootstrap memories failed: %s", e)

    def resolve_conflicts(self, memory_type: MemoryType, scope: str = "global") -> int:
        resolved = 0
        try:
            items = self._repo.list_by_type(memory_type, MemoryStatus.ACTIVE, scope, limit=100)
            by_content: dict[str, list[MemoryItem]] = {}
            for item in items:
                key = f"{item.title}:{item.content[:80]}"
                by_content.setdefault(key, []).append(item)

            for key, group in by_content.items():
                if len(group) < 2:
                    continue
                group.sort(key=lambda x: x.confidence, reverse=True)
                winner = group[0]
                for item in group[1:]:
                    if item.confidence >= winner.confidence:
                        self._repo.update_status(item.id, MemoryStatus.NEEDS_REVIEW)
                        logger.info("Conflict detected: %s marked for review", item.content[:40])
                    else:
                        self._repo.update_status(item.id, MemoryStatus.DEPRECATED)
                        logger.info("Conflict resolved: deprecated lower-confidence memory")
                    resolved += 1
            if resolved > 0:
                self._refresh_projections()
        except Exception as e:
            logger.warning("Conflict resolution failed: %s", e)
        return resolved

    def cleanup_expired(self) -> int:
        cleaned = 0
        try:
            for mt in MemoryType:
                items = self._repo.list_by_type(mt, MemoryStatus.ACTIVE, limit=1000)
                for item in items:
                    if item.is_expired():
                        self._repo.update_status(item.id, MemoryStatus.DEPRECATED)
                        logger.info("Expired memory deprecated: %s", item.content[:40])
                        cleaned += 1
            if cleaned > 0:
                self._refresh_projections()
        except Exception as e:
            logger.warning("Expired cleanup failed: %s", e)
        return cleaned
