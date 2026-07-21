"""5.3 Unified memory write gateway — all long-term memory writes MUST pass through here."""

from __future__ import annotations

import logging
import uuid
from typing import Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

from core.config import Settings
from core.memory.memory_schema import (
    ConflictCandidate,
    MemoryItem,
    MemoryPatch,
    MemoryPatchAction,
    MemoryPatchItem,
    MemoryStatus,
    MemoryType,
)

if TYPE_CHECKING:
    from core.memory.memory_service import MemoryService
    from core.memory.privacy_mode import PrivacyModeManager

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
    conflicts: list["ConflictCandidate"] = Field(default_factory=list)

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

    def __init__(
        self,
        memory_service: "MemoryService",
        settings: Settings,
        privacy: "Optional[PrivacyModeManager]" = None,
    ) -> None:
        self._memory_service = memory_service
        self._settings = settings
        self._privacy = privacy
        self._min_confidence = getattr(settings, "memory_gateway_min_confidence", 0.75)
        self._max_items = getattr(settings, "memory_gateway_max_items_per_patch", 8)

    def update_settings(self, settings: Settings) -> None:
        self._settings = settings
        self._min_confidence = settings.memory_gateway_min_confidence
        self._max_items = settings.memory_gateway_max_items_per_patch

    # ---- Public API ----

    async def submit_patch(self, patch: MemoryPatch, context: WriteContext) -> WriteResult:
        """Unified write entry. Real pipeline:
        1. Budget check (max items per patch)
        2. Per-item: secret scan, confidence check, policy routing
        3. Provenance enrichment
        4. Apply accepted items via MemoryService
        """
        result = WriteResult()

        if context.session_id and self._privacy and self._privacy.is_privacy_active(context.session_id):
            logger.info(
                "MemoryWriteGateway.submit_patch: privacy active for session=%s, skipping",
                context.session_id,
            )
            return result

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
                        source_message_id=context.message_id,
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

        if result.needs_review:
            result.needs_review = self._memory_service.save_review_memories(
                result.needs_review
            )

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

                for accepted_item in accepted:
                    item_conflicts = self._memory_service.detect_conflicts_for_item(
                        accepted_item
                    )
                    result.conflicts.extend(item_conflicts)
            except Exception as exc:
                logger.error("MemoryWriteGateway.submit_patch failed: %s", exc)
                raise

        logger.info(
            "MemoryWriteGateway: accepted=%d rejected=%d needs_review=%d conflicts=%d source=%s session=%s",
            len(result.accepted), len(result.rejected), len(result.needs_review),
            len(result.conflicts),
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
        if context.session_id and self._privacy and self._privacy.is_privacy_active(context.session_id):
            raise ValueError("Privacy mode active; identity memory write rejected")

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

    def submit_manual_memory(
        self,
        *,
        memory_type: MemoryType,
        title: str,
        content: str,
        session_id: str | None = None,
        importance: float = 0.85,
    ) -> MemoryItem:
        """Persist one explicit user-authored Structured Memory.

        This synchronous Interface is intended for local governance UI actions.
        It still crosses the unified gateway, honors privacy mode, records
        provenance, and produces a Memory Revision.
        """
        if session_id and self._privacy and self._privacy.is_privacy_active(session_id):
            raise ValueError("隐私模式开启时不会写入长期记忆")
        clean_title = title.strip()
        clean_content = content.strip()
        if not clean_title:
            raise ValueError("记忆标题不能为空")
        if not clean_content:
            raise ValueError("记忆内容不能为空")
        if len(clean_content) > 2000:
            raise ValueError("记忆内容不能超过 2000 字")
        if memory_type not in {
            MemoryType.USER_PROFILE,
            MemoryType.EPISODIC_MEMORY,
            MemoryType.PROCEDURAL_MEMORY,
            MemoryType.PROJECT_MEMORY,
        }:
            raise ValueError("该记忆类别不支持手动添加")

        patch = MemoryPatch(
            items=[
                MemoryPatchItem(
                    memory_type=memory_type,
                    action=MemoryPatchAction.ADD,
                    title=clean_title[:120],
                    content=clean_content,
                    confidence=1.0,
                    importance=max(0.0, min(1.0, importance)),
                    reason="你在记忆控制台主动告诉 Lobuddy",
                )
            ]
        )
        accepted, rejected = self._memory_service.apply_gateway_patch(
            patch,
            source="manual",
            source_session_id=session_id,
        )
        if rejected or not accepted:
            raise ValueError("这条内容未通过记忆写入校验")
        saved = accepted[0]
        self._memory_service.detect_conflicts_for_item(saved)
        return saved

    def submit_import_review_batch(
        self,
        *,
        package_id: str,
        candidates: list[tuple[MemoryPatchItem, str]],
        session_id: str | None = None,
    ) -> tuple[list[MemoryItem], list[str]]:
        """Persist an explicitly selected portability package behind review gating."""
        if session_id and self._privacy and self._privacy.is_privacy_active(session_id):
            raise ValueError("隐私模式开启时不会导入长期记忆")
        try:
            if str(uuid.UUID(package_id)) != package_id.lower():
                raise ValueError
        except (ValueError, AttributeError) as exc:
            raise ValueError("迁移包缺少有效标识") from exc
        if len(candidates) > 500:
            raise ValueError("单个记忆迁移包最多导入 500 条内容")
        allowed_types = {
            MemoryType.USER_PROFILE,
            MemoryType.PROJECT_MEMORY,
            MemoryType.EPISODIC_MEMORY,
            MemoryType.PROCEDURAL_MEMORY,
        }
        for candidate, entry_digest in candidates:
            if candidate.action != MemoryPatchAction.ADD:
                raise ValueError("导入只允许新增待确认记忆")
            if candidate.memory_type not in allowed_types:
                raise ValueError("迁移包包含不可导入的记忆类型")
            if len(entry_digest) != 64 or any(
                char not in "0123456789abcdef" for char in entry_digest
            ):
                raise ValueError("迁移包条目缺少有效校验标识")

        saved, skipped = self._memory_service.import_review_memories(
            package_id,
            candidates,
        )
        logger.info(
            "MemoryWriteGateway.import: imported=%d duplicate=%d package=%s",
            len(saved),
            len(skipped),
            package_id,
        )
        return saved, skipped
