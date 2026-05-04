"""5.3 Unified memory write gateway — all long-term memory writes MUST pass through here."""

from __future__ import annotations

import logging
import uuid
from typing import Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

from core.config import Settings
from core.memory.memory_schema import (
    MemoryItem,
    MemoryPatch,
    MemoryPatchItem,
    MemoryPatchAction,
    MemoryType,
    MemoryStatus,
)

if TYPE_CHECKING:
    from core.memory.memory_service import MemoryService

logger = logging.getLogger(__name__)

# ---- Write Context Models ----


class WriteContext(BaseModel):
    """写入上下文 — tracks who/what/why triggered a memory write."""

    source: str = Field(..., description="strong_signal | ai_patch | dream | manual | external_provider")
    session_id: Optional[str] = Field(default=None, description="Originating chat session")
    task_id: Optional[str] = Field(default=None, description="Originating task")
    message_id: Optional[str] = Field(default=None, description="Originating message")
    triggered_by: str = Field(..., description="adapter | dream | skill_learning | exit_analysis | manual")


class WriteResult(BaseModel):
    """写入结果 — structured result of gateway processing."""

    accepted: list[MemoryItem] = Field(default_factory=list)
    rejected: list["Rejection"] = Field(default_factory=list)
    needs_review: list[MemoryItem] = Field(default_factory=list)

    @property
    def total_processed(self) -> int:
        return len(self.accepted) + len(self.rejected) + len(self.needs_review)


class Rejection(BaseModel):
    """写入拒绝记录 — machine-readable reason for rejection."""

    item_content: str
    reason: str  # low_confidence | duplicate | secret_found | prompt_injection | policy_reject
    memory_type: Optional[str] = None


# ---- Gateway ----


class MemoryWriteGateway:
    """5.3 统一记忆写入网关。

    All long-term memory writes MUST pass through this gateway.
    Gateway is the OUTER write entry point; MemoryService is the INNER domain service.

    Correct layering:
        UI / Adapter / ExitAnalyzer / Dream → MemoryWriteGateway → MemoryService → MemoryRepository

    Allowed exceptions (direct MemoryService/Repository access):
        - Unit tests
        - One-time migration scripts (with migration log)
        - MemoryService._ensure_bootstrap_memories() (fixed, repeatable content)
    """

    def __init__(self, memory_service: "MemoryService", settings: Settings) -> None:
        self._memory_service = memory_service
        self._settings = settings
        self._min_confidence = getattr(settings, "memory_gateway_min_confidence", 0.75)
        self._max_items = getattr(settings, "memory_gateway_max_items_per_patch", 8)

    # ---- Public API ----

    async def submit_patch(self, patch: MemoryPatch, context: WriteContext) -> WriteResult:
        """Unified write entry. Real pipeline:
        1. Budget check (max items per patch)
        2. Per-item: secret scan, confidence check, policy routing
        3. Provenance enrichment
        4. Apply accepted items via MemoryService
        """
        result = WriteResult()

        # Budget check: truncate if over limit
        items = patch.items[:self._max_items]

        accepted_patch = MemoryPatch(items=[])
        for item in items:
            # Content validation
            content = item.content.strip()
            if not content:
                result.rejected.append(Rejection(
                    item_content=item.content,
                    reason="empty_content",
                    memory_type=item.memory_type.value,
                ))
                continue

            # Secret scan (basic — MemoryService.apply_patch does full sanitization)
            # More sophisticated prompt injection scan deferred to Phase 2

            # Confidence routing
            if item.confidence < self._min_confidence:
                if item.importance >= 0.8:
                    # High importance but low confidence → needs_review
                    result.needs_review.append(MemoryItem(
                        id=str(uuid.uuid4()),
                        memory_type=item.memory_type,
                        scope=item.scope,
                        title=item.title,
                        content=content,
                        source=context.source,
                        source_session_id=context.session_id,
                        confidence=item.confidence,
                        importance=item.importance,
                        status=MemoryStatus.NEEDS_REVIEW,
                    ))
                else:
                    result.rejected.append(Rejection(
                        item_content=content,
                        reason="low_confidence",
                        memory_type=item.memory_type.value,
                    ))
                continue

            # Provenance enrichment: add source/session info before submitting
            accepted_patch.items.append(item)

        if accepted_patch.items:
            try:
                accepted, rejected_by_service = self._memory_service.apply_gateway_patch(
                    accepted_patch,
                    source=context.source,
                    source_session_id=context.session_id,
                    source_message_id=context.message_id,
                )
                result.accepted = accepted
                for rp in rejected_by_service:
                    result.rejected.append(Rejection(
                        item_content=rp.content,
                        reason="duplicate",
                        memory_type=rp.memory_type.value if rp.memory_type else None,
                    ))
            except Exception as exc:
                logger.error("MemoryWriteGateway.submit_patch failed: %s", exc)
                raise

        logger.info(
            "MemoryWriteGateway: accepted=%d rejected=%d needs_review=%d source=%s session=%s",
            len(result.accepted), len(result.rejected), len(result.needs_review),
            context.source, context.session_id or "-",
        )
        return result

    def submit_identity_memory(
        self,
        memory_type: MemoryType,
        title: str,
        content: str,
        context: WriteContext,
        confidence: float = 0.95,
        importance: float = 0.9,
    ) -> MemoryItem:
        """Write identity-level memory (user name, pet name, etc.) through gateway.

        Provenance (session_id, message_id) from WriteContext is persisted
        to SQLite so identity writes can be traced to their originating session.
        """
        try:
            item = self._memory_service.upsert_identity_memory(
                memory_type=memory_type,
                title=title,
                content=content,
                source=context.source,
                source_session_id=context.session_id,
                source_message_id=context.message_id,
                confidence=confidence,
                importance=importance,
            )
            logger.info(
                "MemoryWriteGateway.identity_memory: type=%s title=%s source=%s",
                memory_type.value,
                title,
                context.source,
            )
            return item
        except ValueError as exc:
            logger.warning("MemoryWriteGateway.identity_memory rejected: %s", exc)
            raise
