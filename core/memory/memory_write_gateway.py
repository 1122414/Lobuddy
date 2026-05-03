"""5.3 Unified memory write gateway — all long-term memory writes MUST pass through here."""

from __future__ import annotations

import logging
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
        self._min_confidence = getattr(settings, "memory_min_confidence", 0.75)

    # ---- Public API ----

    async def submit_patch(self, patch: MemoryPatch, context: WriteContext) -> WriteResult:
        """Unified write entry. All memory writes go through here.

        Pipeline:
        1. schema validation (Pydantic — MemoryPatch is validated at construction)
        2. secret scan (_sanitize_memory_text via MemoryService)
        3. prompt injection scan (TBD Phase 2)
        4. duplicate/conflict detection (delegated to MemoryService._find_similar)
        5. provenance enrichment (fills source_session_id etc.)
        6. policy check (should_save / target_type / reject_reason)
        7. budget check (max items per patch)
        8. review routing (high importance → needs_review, low confidence → rejected)
        9. apply via MemoryService.apply_patch()
        """
        result = WriteResult()
        # TODO Phase 2: implement full pipeline
        # For Phase 1: delegate to MemoryService.apply_patch() directly
        # Future: add injection scan, policy check, budget check, review routing
        try:
            accepted, rejected_patch_items = self._memory_service.apply_patch(patch)
            result.accepted = accepted
            for rp in rejected_patch_items:
                result.rejected.append(
                    Rejection(
                        item_content=rp.content,
                        reason="low_confidence",
                        memory_type=rp.memory_type.value if rp.memory_type else None,
                    )
                )
            logger.info(
                "MemoryWriteGateway: accepted=%d rejected=%d source=%s session=%s",
                len(accepted),
                len(rejected_patch_items),
                context.source,
                context.session_id or "-",
            )
        except Exception as exc:
            logger.error("MemoryWriteGateway.submit_patch failed: %s", exc)
            raise
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
        """Write identity-level memory (user name, pet name, etc.) through gateway."""
        try:
            item = self._memory_service.upsert_identity_memory(
                memory_type=memory_type,
                title=title,
                content=content,
                source=context.source,
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
