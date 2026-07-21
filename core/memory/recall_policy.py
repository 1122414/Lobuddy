"""Policy models for lightweight, grounded structured-memory recall."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.memory.memory_schema import MemoryItem


@dataclass
class RecallBudget:
    """Budget constraint for cold recall within a single prompt context.

    Cold recall is subject to the same prompt budget constraints as hot memory.
    This dataclass tracks how much budget remains after hot memory injection.
    """

    total_chars: int = 0
    remaining_chars: int = 0
    used_chars: int = 0

    def allocate(self, chars: int) -> int:
        """Allocate up to `chars` from remaining budget. Returns actual allocated."""
        allocated = min(chars, self.remaining_chars)
        self.used_chars += allocated
        self.remaining_chars -= allocated
        return allocated

    @property
    def is_exhausted(self) -> bool:
        return self.remaining_chars <= 0


@dataclass
class SessionRecallCandidate:
    """A candidate memory item for cold recall into the current session.

    Cold recall candidates are selected via lightweight keyword/FTS search
    (not full vector RAG). They are ranked by relevance and injected only
    if budget remains after hot memory layers.
    """

    item: MemoryItem
    relevance_score: float = 0.0
    source_session_id: Optional[str] = None
    reason: str = ""

    @property
    def is_high_relevance(self) -> bool:
        return self.relevance_score >= 0.7


@dataclass
class RecallPolicy:
    """Policy governing when and how cold structured memory is recalled."""

    enabled: bool = False
    max_candidates_per_turn: int = 3
    min_relevance_threshold: float = 0.5
    require_user_message_match: bool = True

    def should_recall(
        self, candidates: list[SessionRecallCandidate]
    ) -> list[SessionRecallCandidate]:
        """Filter candidates according to policy constraints.

        Returns the subset of candidates that should be recalled.
        """
        if not self.enabled:
            return []

        filtered = sorted(
            (
                candidate
                for candidate in candidates
                if candidate.relevance_score >= self.min_relevance_threshold
            ),
            key=lambda candidate: (
                candidate.relevance_score,
                candidate.item.importance,
                candidate.item.confidence,
                candidate.item.updated_at,
            ),
            reverse=True,
        )
        return filtered[: self.max_candidates_per_turn]

    def create_budget(self, hot_memory_used_chars: int, total_budget_chars: int) -> RecallBudget:
        """Create a recall budget from remaining prompt space."""
        remaining = max(0, total_budget_chars - hot_memory_used_chars)
        return RecallBudget(
            total_chars=total_budget_chars,
            remaining_chars=remaining,
            used_chars=0,
        )
