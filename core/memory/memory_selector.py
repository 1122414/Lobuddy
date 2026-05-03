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
        budget_report: dict[str, int] = {}

        # Layered hot memory budgets (tokens → chars: 1 token ≈ 4 chars)
        budget_user = self._settings.memory_hot_user_profile_tokens * 4
        budget_system = self._settings.memory_hot_system_profile_tokens * 4
        budget_project = self._settings.memory_hot_project_context_tokens * 4

        # --- User Profile (hot memory tier 1) ---
        user_items = self._repo.list_by_type(MemoryType.USER_PROFILE, MemoryStatus.ACTIVE, limit=20)
        user_items.sort(key=lambda x: x.priority, reverse=True)
        if user_items:
            lines = []
            used = 0
            for item in user_items:
                line = f"- {item.content}"
                if used + len(line) > budget_user:
                    break
                lines.append(line)
                used += len(line)
            bundle.user_profile = "\n".join(lines)
            budget_report["user_profile"] = used

        # --- System Profile (hot memory tier 2) ---
        system_items = self._repo.list_by_type(MemoryType.SYSTEM_PROFILE, MemoryStatus.ACTIVE, limit=10)
        system_items.sort(key=lambda x: x.priority, reverse=True)
        if system_items:
            lines = []
            used = 0
            for item in system_items:
                line = f"- {item.content}"
                if used + len(line) > budget_system:
                    break
                lines.append(line)
                used += len(line)
            bundle.system_profile = "\n".join(lines)
            budget_report["system_profile"] = used

        # --- Project Context (hot memory tier 3) ---
        project_items = self._repo.list_by_type(MemoryType.PROJECT_MEMORY, MemoryStatus.ACTIVE, limit=20)
        project_items.sort(key=lambda x: x.priority, reverse=True)
        if project_items:
            lines = []
            used = 0
            for item in project_items:
                line = f"- [{item.scope}] {item.content}"
                if used + len(line) > budget_project:
                    break
                lines.append(line)
                used += len(line)
            bundle.project_context = "\n".join(lines)
            budget_report["project_context"] = used

        # --- Session Summary ---
        if session_id:
            latest = self._repo.get_latest_summary(session_id)
            if latest:
                bundle.session_summary = latest.content
                budget_report["session_summary"] = len(latest.content)

        # --- Retrieved / Episodic (remaining recall budget) ---
        fixed_chars = (
            len(bundle.user_profile)
            + len(bundle.system_profile)
            + len(bundle.project_context)
            + len(bundle.session_summary)
        )
        overall_budget = self._budget.get_budget(user_message) if user_message else self._budget.max_chars
        remaining_budget = max(0, overall_budget - fixed_chars)

        if user_message and remaining_budget > 0:
            episodic_results = self._repo.search_by_keyword(
                user_message, MemoryType.EPISODIC_MEMORY,
                limit=self._settings.memory_max_episodic_results,
            )
            if episodic_results:
                lines = []
                used = 0
                for item in episodic_results:
                    line = f"- [{item.memory_type.value}] {item.content}"
                    if used + len(line) > remaining_budget:
                        break
                    lines.append(line)
                    used += len(line)
                bundle.retrieved_memories = "\n".join(lines)
                budget_report["retrieved_memories"] = used

        bundle.total_chars = (
            len(bundle.user_profile)
            + len(bundle.system_profile)
            + len(bundle.project_context)
            + len(bundle.session_summary)
            + len(bundle.retrieved_memories)
        )
        bundle.memory_budget_report = budget_report
        return bundle

    def search_fts(
        self,
        query: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        return self._repo.search_fts(query, memory_type, limit)
