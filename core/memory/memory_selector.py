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
        bundles: list[MemoryBundle] = []

        user_items = self._repo.list_by_type(MemoryType.USER_PROFILE, MemoryStatus.ACTIVE, limit=20)
        if user_items:
            content = "\n".join(f"- {i.content}" for i in user_items)
            bundles.append(MemoryBundle(content, priority=100, source="user_profile"))

        system_items = self._repo.list_by_type(MemoryType.SYSTEM_PROFILE, MemoryStatus.ACTIVE, limit=10)
        if system_items:
            content = "\n".join(f"- {i.content}" for i in system_items)
            bundles.append(MemoryBundle(content, priority=90, source="system_profile"))

        if user_message:
            project_results = self._repo.search_by_keyword(user_message, MemoryType.PROJECT_MEMORY, limit=3)
            episodic_results = self._repo.search_by_keyword(user_message, MemoryType.EPISODIC_MEMORY, limit=3)
            retrieved = project_results + episodic_results
            if retrieved:
                content = "\n".join(f"- [{i.memory_type.value}] {i.content}" for i in retrieved)
                bundles.append(MemoryBundle(content, priority=70, source="retrieved"))

        if session_id:
            latest = self._repo.get_latest_summary(session_id)
            if latest:
                bundles.append(MemoryBundle(latest.content, priority=80, source="session_summary"))

        selected = self._budget.allocate(user_message, bundles)
        for sb in selected:
            if sb.source == "user_profile":
                bundle.user_profile = sb.content
            elif sb.source == "system_profile":
                bundle.system_profile = sb.content
            elif sb.source == "retrieved":
                bundle.retrieved_memories = sb.content
            elif sb.source == "session_summary":
                bundle.session_summary = sb.content

        bundle.total_chars = sum(len(b.content) for b in selected)
        return bundle

    def search_fts(
        self,
        query: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        return self._repo.search_fts(query, memory_type, limit)
