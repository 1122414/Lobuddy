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
        bundle = PromptContextBundle()
        user_items = self._repo.list_by_type(MemoryType.USER_PROFILE, MemoryStatus.ACTIVE, limit=20)
        if user_items:
            bundle.user_profile = "\n".join(f"- {i.content}" for i in user_items)
        system_items = self._repo.list_by_type(MemoryType.SYSTEM_PROFILE, MemoryStatus.ACTIVE, limit=10)
        if system_items:
            bundle.system_profile = "\n".join(f"- {i.content}" for i in system_items)
        if user_message:
            project_results = self._repo.search_by_keyword(user_message, MemoryType.PROJECT_MEMORY, limit=3)
            episodic_results = self._repo.search_by_keyword(user_message, MemoryType.EPISODIC_MEMORY, limit=3)
            retrieved = project_results + episodic_results
            if retrieved:
                bundle.retrieved_memories = "\n".join(f"- [{i.memory_type.value}] {i.content}" for i in retrieved)
        bundle.total_chars = len(bundle.user_profile) + len(bundle.system_profile) + len(bundle.session_summary) + len(bundle.retrieved_memories) + len(bundle.active_skills)
        return bundle

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
