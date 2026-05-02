"""Memory selector for retrieving and ranking memories for prompt injection."""

import logging
from typing import Optional

from core.config import Settings
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import MemoryItem, MemoryStatus, MemoryType, PromptContextBundle
from core.memory.prompt_budget import MemoryBundle, PromptBudget

logger = logging.getLogger(__name__)


class MemorySelector:
    """Selects memories for prompt injection based on relevance and budget."""

    def __init__(self, settings: Settings, repo: Optional[MemoryRepository] = None) -> None:
        self._settings = settings
        self._repo = repo or MemoryRepository()
        self._budget = PromptBudget(
            settings.memory_prompt_budget_chars,
            settings.memory_prompt_budget_percent,
        )

    def select_for_prompt(
        self,
        user_message: str,
        session_id: str = "",
    ) -> PromptContextBundle:
        bundle = PromptContextBundle()

        user_items = self._repo.list_by_type(MemoryType.USER_PROFILE, MemoryStatus.ACTIVE, limit=20)
        user_items.sort(key=lambda x: x.priority, reverse=True)
        if user_items:
            bundle.user_profile = "\n".join(f"- {i.content}" for i in user_items)

        system_items = self._repo.list_by_type(MemoryType.SYSTEM_PROFILE, MemoryStatus.ACTIVE, limit=10)
        system_items.sort(key=lambda x: x.priority, reverse=True)
        if system_items:
            bundle.system_profile = "\n".join(f"- {i.content}" for i in system_items)

        if session_id:
            latest = self._repo.get_latest_summary(session_id)
            if latest:
                bundle.session_summary = latest.content

        retrieved_bundles: list[MemoryBundle] = []
        if user_message:
            project_results = self._repo.search_by_keyword(user_message, MemoryType.PROJECT_MEMORY, limit=self._settings.memory_max_episodic_results)
            episodic_results = self._repo.search_by_keyword(user_message, MemoryType.EPISODIC_MEMORY, limit=self._settings.memory_max_episodic_results)
            retrieved = project_results + episodic_results
            if retrieved:
                content = "\n".join(f"- [{i.memory_type.value}] {i.content}" for i in retrieved)
                retrieved_bundles.append(MemoryBundle(content, priority=70, source="retrieved"))

        fixed_chars = len(bundle.user_profile) + len(bundle.system_profile) + len(bundle.session_summary)
        remaining_budget = max(0, self._budget.max_chars - fixed_chars)
        if remaining_budget > 0 and retrieved_bundles:
            selected = self._budget.allocate(user_message, retrieved_bundles)
            for sb in selected:
                if sb.source == "retrieved":
                    bundle.retrieved_memories = sb.content

        bundle.total_chars = len(bundle.user_profile) + len(bundle.system_profile) + len(bundle.session_summary) + len(bundle.retrieved_memories)
        return bundle

    def search_fts(
        self,
        query: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        return self._repo.search_fts(query, memory_type, limit)
