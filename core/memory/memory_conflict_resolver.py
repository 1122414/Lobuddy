"""Memory conflict detection and resolution for Lobuddy structured memory system.

Detects conflicts where two memory items share the same identity key (memory_type + title)
but have different content values, creating conflict_candidate records for user review.
"""

import hashlib
import logging
import uuid
from typing import Optional

from core.config import Settings
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    ConflictCandidate,
    ConflictStatus,
    ConflictType,
    MemoryItem,
    MemoryRevision,
    MemoryRevisionType,
    MemoryStatus,
    MemoryType,
)

logger = logging.getLogger(__name__)


class MemoryConflictResolver:
    """Detects and resolves conflicts between memory items.

    An identity key is (memory_type, title). When two items share the same identity
    key but have semantically different content, a conflict is detected.
    """

    def __init__(self, repo: MemoryRepository, settings: Optional[Settings] = None) -> None:
        self._repo = repo
        self._settings = settings

    def _is_enabled(self) -> bool:
        if self._settings is None:
            return True
        return getattr(self._settings, "memory_conflict_detection_enabled", True)

    def _auto_resolve_threshold(self) -> float:
        if self._settings is None:
            return 0.95
        return getattr(self._settings, "memory_conflict_auto_resolve_threshold", 0.95)

    def _identity_keys(self) -> set[str]:
        if self._settings is None:
            return set()
        keys_str = getattr(
            self._settings,
            "memory_conflict_identity_keys",
            "user_name,pet_name,project_path,preferred_language",
        )
        return set(k.strip() for k in keys_str.split(",") if k.strip())

    def _should_check_title(self, title: str) -> bool:
        if self._settings is None:
            return True
        identity_keys = self._identity_keys()
        if not identity_keys or "*" in identity_keys:
            return True
        title_lower = title.strip().lower() if title else ""
        for key in identity_keys:
            if key.lower() in title_lower:
                return True
        return False

    def detect_conflicts(
        self,
        memory_type: MemoryType,
        scope: str = "global",
    ) -> list[ConflictCandidate]:
        """Detect conflicts among active items of a given memory_type.

        Groups items by identity key (title), then finds pairs with different
        content that are not simple substring extensions. Each conflicting pair
        produces a conflict_candidate record.

        Returns list of newly created ConflictCandidate records.
        """
        if not self._is_enabled():
            return []
        candidates: list[ConflictCandidate] = []
        items = self._repo.list_by_type(memory_type, MemoryStatus.ACTIVE, scope, limit=500)
        title_groups: dict[str, list[MemoryItem]] = {}
        for item in items:
            if not self._should_check_title(item.title):
                continue
            key = item.title.strip().lower() if item.title else "_unnamed_"
            title_groups.setdefault(key, []).append(item)

        threshold = self._auto_resolve_threshold()
        for group in title_groups.values():
            if len(group) < 2:
                continue
            sorted_group = sorted(group, key=lambda x: x.confidence, reverse=True)
            for i in range(len(sorted_group)):
                for j in range(i + 1, len(sorted_group)):
                    a, b = sorted_group[i], sorted_group[j]
                    if self._is_content_conflict(a.content, b.content):
                        exists = self._check_existing_candidate(a.id, b.id)
                        if not exists:
                            if (
                                a.confidence >= threshold
                                and a.confidence > b.confidence
                                and self._auto_resolve(a, b)
                            ):
                                continue
                            candidate = self._repo.save_conflict_candidate(
                                ConflictCandidate(
                                    id=str(uuid.uuid4()),
                                    existing_item_id=a.id,
                                    new_item_id=b.id,
                                    conflict_type=ConflictType.DIFFERENT_VALUE,
                                )
                            )
                            candidates.append(candidate)
                            self._repo.update_status(b.id, MemoryStatus.NEEDS_REVIEW)
        return candidates

    def detect_conflicts_for_new_item(self, new_item: MemoryItem) -> list[ConflictCandidate]:
        """Detect conflicts between a new item and existing active items.

        Checks if any existing active item shares the same identity key
        (memory_type + title) but has different content.

        Returns list of newly created ConflictCandidate records.
        """
        if not self._is_enabled():
            return []
        if not self._should_check_title(new_item.title):
            return []
        candidates: list[ConflictCandidate] = []
        existing_items = self._repo.list_by_type(
            new_item.memory_type, MemoryStatus.ACTIVE, new_item.scope, limit=500
        )
        threshold = self._auto_resolve_threshold()
        for existing in existing_items:
            if existing.id == new_item.id:
                continue
            if not existing.title and not new_item.title:
                continue
            key_new = new_item.title.strip().lower() if new_item.title else ""
            key_existing = existing.title.strip().lower() if existing.title else ""
            if not key_new or not key_existing or key_new != key_existing:
                continue
            if self._is_content_conflict(existing.content, new_item.content):
                exists = self._check_existing_candidate(existing.id, new_item.id)
                if not exists:
                    if (
                        new_item.confidence >= threshold
                        and new_item.confidence > existing.confidence
                        and self._auto_resolve(new_item, existing)
                    ):
                        continue
                    candidate = self._repo.save_conflict_candidate(
                        ConflictCandidate(
                            id=str(uuid.uuid4()),
                            existing_item_id=existing.id,
                            new_item_id=new_item.id,
                            conflict_type=ConflictType.DIFFERENT_VALUE,
                        )
                    )
                    candidates.append(candidate)
                    self._repo.update_status(new_item.id, MemoryStatus.NEEDS_REVIEW)
        return candidates

    def resolve_conflict(
        self,
        candidate_id: str,
        accept_new: bool,
        *,
        actor: str = "user",
        reason: str = "用户裁决了记忆冲突",
    ) -> Optional[ConflictCandidate]:
        """Resolve a pending conflict.

        If accept_new is True: deprecates the existing item, activates the new item.
        If accept_new is False: deprecates the new item, keeps existing item.
        """
        candidate = self._repo.get_conflict_candidate(candidate_id)
        if candidate is None:
            return None
        if candidate.status != ConflictStatus.PENDING:
            return None

        existing = self._repo.get(candidate.existing_item_id)
        new_item = self._repo.get(candidate.new_item_id)
        if existing is None or new_item is None:
            return None
        winner = new_item if accept_new else existing
        loser = existing if accept_new else new_item
        clean_reason = reason.strip()[:500]
        revisions = [
            self._conflict_revision(
                winner,
                loser,
                actor,
                clean_reason or "保留了这条记忆",
            ),
            self._conflict_revision(
                loser,
                winner,
                actor,
                clean_reason or "停用了冲突记忆",
            ),
        ]
        return self._repo.resolve_conflict_atomic(
            candidate_id,
            accept_new,
            revisions,
        )

    def list_pending(self) -> list[ConflictCandidate]:
        """List all pending (unresolved) conflict candidates."""
        return self._repo.list_conflict_candidates(ConflictStatus.PENDING)

    def list_all(self) -> list[ConflictCandidate]:
        """List all conflict candidates regardless of status."""
        return self._repo.list_conflict_candidates()

    @staticmethod
    def _is_content_conflict(content_a: str, content_b: str) -> bool:
        """Check if two content strings represent a semantic conflict.

        Not a conflict if one is a substring of the other (extension).
        Conflict when both are materially different statements.
        """
        a = content_a.strip()
        b = content_b.strip()
        if a == b:
            return False
        if a in b or b in a:
            return False
        return True

    def _check_existing_candidate(self, item_id_a: str, item_id_b: str) -> bool:
        existing = self._repo.list_conflict_candidates()
        for c in existing:
            pair = {c.existing_item_id, c.new_item_id}
            if pair == {item_id_a, item_id_b}:
                return True
        return False

    def _auto_resolve(self, winner: MemoryItem, loser: MemoryItem) -> bool:
        reason = "系统依据明显更高的置信度自动保留了这条记忆"
        revisions = [
            self._conflict_revision(winner, loser, "system", reason),
            self._conflict_revision(loser, winner, "system", reason),
        ]
        return self._repo.update_statuses_with_revisions(
            [
                (loser.id, MemoryStatus.DEPRECATED),
                (winner.id, MemoryStatus.ACTIVE),
            ],
            revisions,
        )

    @staticmethod
    def _conflict_revision(
        item: MemoryItem,
        related: MemoryItem,
        actor: str,
        reason: str,
    ) -> MemoryRevision:
        content_hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
        return MemoryRevision(
            id=str(uuid.uuid4()),
            memory_id=item.id,
            revision_type=MemoryRevisionType.CONFLICT_RESOLVED,
            actor=(actor or "user").strip()[:80] or "user",
            reason=reason,
            related_memory_id=related.id,
            previous_content_hash=content_hash,
            new_content_hash=content_hash,
        )
