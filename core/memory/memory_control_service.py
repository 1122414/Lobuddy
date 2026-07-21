"""Memory control service for user-facing memory management.

All write operations go through MemoryService or MemoryWriteGateway.
This service provides the read/query layer for the memory console UI.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.config import Settings
from core.memory.memory_conflict_resolver import MemoryConflictResolver
from core.memory.memory_portability import (
    MemoryExportResult,
    MemoryImportPreview,
    MemoryImportResult,
    MemoryPortability,
)
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    MemoryItem,
    MemoryRecallFeedback,
    MemoryRevision,
    MemoryRevisionType,
    MemoryStatus,
    MemoryType,
)
from core.memory.memory_service import MemoryService
from core.memory.memory_write_gateway import MemoryWriteGateway

logger = logging.getLogger(__name__)


@dataclass
class ProvenanceInfo:
    """Structured provenance info for UI display."""

    source: str
    source_session_id: str
    source_message_id: str
    created_at: datetime
    updated_at: datetime
    confidence: float
    importance: float
    has_precise_source: bool


@dataclass(frozen=True)
class MemoryExplanation:
    """Plain-language explanation of why Lobuddy trusts and uses a memory."""

    source_label: str
    why_remembered: str
    trust_label: str
    usage_label: str
    provenance: ProvenanceInfo
    recall_count: int
    helpful_count: int
    not_relevant_count: int
    inaccurate_count: int


@dataclass(frozen=True)
class MemoryRecallReview:
    """User-facing projection of one memory selected by one Task Run."""

    task_id: str
    memory_id: str
    title: str
    type_label: str
    content_preview: str
    reason: str
    feedback: MemoryRecallFeedback
    status: MemoryStatus
    feedback_at: datetime | None
    is_current: bool


@dataclass(frozen=True)
class MemoryTimelineEntry:
    """User-facing projection of one Memory Revision."""

    revision_id: str
    memory_id: str
    event_type: str
    event_label: str
    title: str
    content_preview: str
    actor_label: str
    reason: str
    occurred_at: datetime
    status: str
    forgotten: bool = False


class MemoryControlService:
    """User-facing memory management service.

    Provides listing, viewing, editing, deprecation, and deletion
    of memory items with proper access controls.
    """

    def __init__(
        self,
        settings: Settings,
        memory_service: Optional[MemoryService] = None,
        repo: Optional[MemoryRepository] = None,
        gateway: Optional[MemoryWriteGateway] = None,
    ) -> None:
        self._settings = settings
        self._memory_service = memory_service
        self._repo = repo or getattr(memory_service, "_repo", None) or MemoryRepository()
        self._gateway = gateway
        self._portability = MemoryPortability(self._repo, gateway)

    def list_memories(
        self,
        memory_type: Optional[MemoryType] = None,
        status: Optional[MemoryStatus] = None,
        scope: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryItem]:
        """List memories with filtering and pagination."""
        if memory_type:
            return self._repo.list_by_type(memory_type, status, scope, limit)
        return self._repo.list_all(status, scope, limit, offset)

    def get_memory(self, item_id: str) -> Optional[MemoryItem]:
        """Get a single memory item by ID."""
        return self._repo.get(item_id)

    def remember_manual(
        self,
        *,
        memory_type: MemoryType,
        title: str,
        content: str,
        session_id: str | None = None,
        importance: float = 0.85,
    ) -> MemoryItem:
        """Create or update one explicit user-authored Structured Memory."""
        if self._gateway is None:
            raise RuntimeError("Manual memory writes require MemoryWriteGateway")
        return self._gateway.submit_manual_memory(
            memory_type=memory_type,
            title=title,
            content=content,
            session_id=session_id,
            importance=importance,
        )

    def export_memory_package(self, path: str | Path) -> MemoryExportResult:
        """Export user-governed Structured Memory to a local package."""
        return self._portability.export_package(path)

    def inspect_memory_package(self, path: str | Path) -> MemoryImportPreview:
        """Validate and summarize a package without writing memory."""
        return self._portability.inspect_package(path)

    def import_memory_package(
        self,
        path: str | Path,
        *,
        expected_file_digest: str,
        session_id: str | None = None,
    ) -> MemoryImportResult:
        """Import an inspected package as review-only Structured Memory."""
        return self._portability.import_package(
            path,
            expected_file_digest=expected_file_digest,
            session_id=session_id,
        )

    def get_provenance(self, item: MemoryItem) -> ProvenanceInfo:
        """Get provenance info for display.

        Returns source, timestamps, confidence, importance.
        Falls back to '历史数据，无精确来源' for missing provenance.
        """
        return ProvenanceInfo(
            source=item.source or "unknown",
            source_session_id=item.source_session_id or "",
            source_message_id=item.source_message_id or "",
            created_at=item.created_at or datetime.now(),
            updated_at=item.updated_at or datetime.now(),
            confidence=item.confidence,
            importance=item.importance,
            has_precise_source=bool(item.source_session_id or item.source_message_id),
        )

    def revise_memory(
        self,
        item_id: str,
        content: str,
        reason: str,
    ) -> Optional[MemoryItem]:
        """Correct content and make explicit user confirmation authoritative."""
        service = self._require_memory_service()
        return service.revise_memory(item_id, content, reason, actor="user")

    def confirm_memory(
        self,
        item_id: str,
        reason: str = "我确认这条记忆仍然准确",
    ) -> Optional[MemoryItem]:
        """Confirm an existing memory without changing its content."""
        service = self._require_memory_service()
        return service.confirm_memory(item_id, reason, actor="user")

    def retire_memory(self, item_id: str, reason: str) -> bool:
        """Stop injecting a memory while preserving it and its reason."""
        service = self._require_memory_service()
        return service.deprecate_memory(item_id, reason, actor="user")

    def restore_memory(self, item_id: str, reason: str) -> bool:
        """Return a retired memory to active prompt use."""
        service = self._require_memory_service()
        return service.restore_memory(item_id, reason, actor="user")

    def forget_memory(self, item_id: str, reason: str) -> bool:
        """Permanently remove memory content while preserving a minimal reason."""
        service = self._require_memory_service()
        return service.delete_memory(item_id, reason, actor="user")

    def deprecate_memory(self, item_id: str) -> bool:
        """Backward-compatible wrapper for retiring a memory."""
        return self.retire_memory(item_id, "用户选择暂时不再使用这条记忆")

    def delete_memory(self, item_id: str) -> bool:
        """Backward-compatible wrapper for permanent forgetting."""
        return self.forget_memory(item_id, "用户要求永久忘记这条记忆")

    def edit_memory(self, item_id: str, content: str) -> bool:
        """Backward-compatible wrapper for a user correction."""
        return (
            self.revise_memory(
                item_id,
                content,
                "用户在记忆控制台修正内容",
            )
            is not None
        )

    def search_memories(
        self,
        keyword: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 10,
        status: Optional[MemoryStatus] = None,
    ) -> list[MemoryItem]:
        """Search memories by keyword."""
        return self._repo.search_by_keyword(keyword, memory_type, limit, status)

    def count_memories(
        self,
        status: Optional[MemoryStatus] = None,
    ) -> int:
        """Count total memories matching criteria."""
        return self._repo.count(status)

    def list_conflicts(
        self,
        memory_type: Optional[MemoryType] = None,
    ) -> list[dict]:
        """List potential memory conflicts.

        Returns items with NEEDS_REVIEW status and pending conflict_candidate
        records with associated memory item details.
        """
        conflicts = []
        for mt in (memory_type,) if memory_type else MemoryType:
            items = self._repo.list_by_type(mt, MemoryStatus.NEEDS_REVIEW, limit=100)
            conflicts.extend(
                {
                    "item": item,
                    "reason": "needs_review",
                    "suggestion": "Review and confirm or deprecate",
                }
                for item in items
            )

        resolver = MemoryConflictResolver(self._repo, self._settings)
        pending_candidates = resolver.list_pending()
        for candidate in pending_candidates:
            existing = self._repo.get(candidate.existing_item_id)
            new_item = self._repo.get(candidate.new_item_id)
            conflicts.append(
                {
                    "candidate_id": candidate.id,
                    "type": "conflict_candidate",
                    "conflict_type": candidate.conflict_type.value,
                    "existing_item": existing,
                    "new_item": new_item,
                    "created_at": candidate.created_at.isoformat(),
                    "suggestion": "Choose which value to keep; the other will be deprecated",
                }
            )

        return conflicts

    def resolve_conflict(self, candidate_id: str, accept_new: bool) -> bool:
        return self.resolve_conflict_with_reason(
            candidate_id,
            accept_new,
            "用户在记忆控制台裁决了冲突",
        )

    def resolve_conflict_with_reason(
        self,
        candidate_id: str,
        accept_new: bool,
        reason: str,
    ) -> bool:
        service = self._require_memory_service()
        return service.resolve_conflict(
            candidate_id,
            accept_new,
            reason=reason,
            actor="user",
        )

    def count_pending_conflicts(self) -> int:
        resolver = MemoryConflictResolver(self._repo, self._settings)
        return len(resolver.list_pending())

    def get_memory_types_summary(self) -> dict[str, int]:
        """Get count summary per memory type."""
        return {mt.value: len(self._repo.list_by_type(mt, limit=1000)) for mt in MemoryType}

    def get_status_summary(self) -> dict[str, int]:
        """Get count summary per status."""
        return {
            MemoryStatus.ACTIVE.value: self._repo.count(MemoryStatus.ACTIVE),
            MemoryStatus.DEPRECATED.value: self._repo.count(MemoryStatus.DEPRECATED),
            MemoryStatus.NEEDS_REVIEW.value: self._repo.count(MemoryStatus.NEEDS_REVIEW),
        }

    def explain_memory(self, item: MemoryItem) -> MemoryExplanation:
        """Translate raw provenance and confidence into relationship language."""
        provenance = self.get_provenance(item)
        source_label, why = self._source_explanation(item.source)
        revisions = self._repo.list_revisions(item.id, limit=20)
        user_confirmed = any(
            revision.actor == "user"
            and revision.revision_type
            in {
                MemoryRevisionType.CONFIRMED,
                MemoryRevisionType.CORRECTED,
                MemoryRevisionType.CONFLICT_RESOLVED,
            }
            for revision in revisions
        )
        if item.status == MemoryStatus.NEEDS_REVIEW:
            trust_label = "等待你确认"
        elif user_confirmed:
            trust_label = "你已确认"
        elif item.confidence >= 0.9:
            trust_label = "高可信"
        elif item.confidence >= 0.75:
            trust_label = "较可信，可随时校正"
        else:
            trust_label = "低可信，建议确认"

        if item.status == MemoryStatus.ACTIVE:
            usage_label = "会在相关对话中使用"
        elif item.status == MemoryStatus.NEEDS_REVIEW:
            usage_label = "确认前不会作为稳定事实"
        else:
            usage_label = "已停用，不会注入后续对话"
        feedback = self._repo.get_recall_feedback_counts(item.id)
        return MemoryExplanation(
            source_label=source_label,
            why_remembered=why,
            trust_label=trust_label,
            usage_label=usage_label,
            provenance=provenance,
            recall_count=feedback["total"],
            helpful_count=feedback[MemoryRecallFeedback.HELPFUL.value],
            not_relevant_count=feedback[MemoryRecallFeedback.NOT_RELEVANT.value],
            inaccurate_count=feedback[MemoryRecallFeedback.INACCURATE.value],
        )

    def list_recall_review(self, task_id: str) -> list[MemoryRecallReview]:
        """List reviewable structured memories used by one Task Run."""
        reviews: list[MemoryRecallReview] = []
        for receipt in self._repo.list_recall_receipts(task_id):
            item = self._repo.get(receipt.memory_id)
            if item is None:
                continue
            type_label = self._type_label(item.memory_type)
            safe_title = self._mask_sensitive_content(item.title.strip())
            is_current = (
                receipt.memory_updated_at is None or receipt.memory_updated_at == item.updated_at
            )
            content_preview = (
                self._preview(
                    self.get_sanitized_content(item, show_full=False),
                    180,
                )
                if is_current
                else "这条记忆已在任务后更新；为避免混淆，不把当前版本当作本次调用内容展示。"
            )
            reviews.append(
                MemoryRecallReview(
                    task_id=receipt.task_id,
                    memory_id=item.id,
                    title=safe_title or type_label,
                    type_label=type_label,
                    content_preview=content_preview,
                    reason=(self._mask_sensitive_content(receipt.reason) or "本次请求与这条记忆相关"),
                    feedback=receipt.feedback,
                    status=item.status,
                    feedback_at=receipt.feedback_at,
                    is_current=is_current,
                )
            )
        return reviews

    def record_recall_feedback(
        self,
        task_id: str,
        memory_id: str,
        feedback: MemoryRecallFeedback | str,
    ) -> tuple[bool, bool]:
        """Record explicit feedback through the governed MemoryService Interface."""
        service = self._require_memory_service()
        return service.record_recall_feedback(
            task_id,
            memory_id,
            MemoryRecallFeedback(feedback),
        )

    def list_timeline(
        self,
        *,
        memory_id: str | None = None,
        limit: int = 100,
    ) -> list[MemoryTimelineEntry]:
        """Build a content-minimized relationship timeline from Memory Revisions."""
        revisions = self._repo.list_revisions(memory_id, limit=max(limit, 100))
        current_items = {item.id: item for item in self._repo.list_all(limit=1000)}
        for revision in revisions:
            if revision.memory_id not in current_items:
                item = self._repo.get(revision.memory_id)
                if item is not None:
                    current_items[item.id] = item
        entries = [
            self._timeline_entry(revision, current_items.get(revision.memory_id))
            for revision in revisions
        ]
        revision_memory_ids = {revision.memory_id for revision in revisions}

        historical_items: list[MemoryItem]
        if memory_id:
            item = self._repo.get(memory_id)
            historical_items = [item] if item is not None else []
        else:
            historical_items = list(current_items.values())
        for item in historical_items:
            if item.id in revision_memory_ids:
                continue
            entries.append(
                MemoryTimelineEntry(
                    revision_id=f"legacy:{item.id}",
                    memory_id=item.id,
                    event_type=MemoryRevisionType.LEARNED.value,
                    event_label="最初记住",
                    title=item.title or self._type_label(item.memory_type),
                    content_preview=self._preview(item.content),
                    actor_label=self._actor_label(item.source),
                    reason="这条记忆保存于关系时间线启用之前",
                    occurred_at=item.created_at,
                    status=item.status.value,
                )
            )
        entries.sort(key=lambda entry: entry.occurred_at, reverse=True)
        return entries[: max(1, min(500, limit))]

    def list_revisions(
        self,
        *,
        memory_id: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRevision]:
        """Expose content-minimized Memory Revisions to relationship projections."""
        return self._repo.list_revisions(memory_id, limit)

    def get_sanitized_content(self, item: MemoryItem, show_full: bool = False) -> str:
        """Get content with optional masking of sensitive info.

        If show_full is False (default), masks potential secrets.
        """
        if show_full:
            return item.content
        return self._mask_sensitive_content(item.content)

    @staticmethod
    def _mask_sensitive_content(content: str) -> str:
        """Mask potentially sensitive content for display."""
        import re

        masked = content
        patterns = [
            (r"sk-[a-zA-Z0-9]{20,}", "sk-***"),
            (r"ghp_[a-zA-Z0-9]{36}", "ghp_***"),
            (r"xoxb-[a-zA-Z0-9-]+", "xoxb-***"),
            (r"Bearer\s+[a-zA-Z0-9._-]+", "Bearer ***"),
            (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "***@***.***"),
        ]
        for pattern, replacement in patterns:
            masked = re.sub(pattern, replacement, masked)
        return masked

    def _require_memory_service(self) -> MemoryService:
        if self._memory_service is None:
            raise RuntimeError("Memory governance requires MemoryService")
        return self._memory_service

    def _timeline_entry(
        self,
        revision: MemoryRevision,
        item: MemoryItem | None,
    ) -> MemoryTimelineEntry:
        forgotten = item is None
        if forgotten:
            title = "已永久忘记的记忆"
            preview = ""
            status = "forgotten"
        else:
            title = item.title or self._type_label(item.memory_type)
            preview = self._preview(self.get_sanitized_content(item))
            status = item.status.value
        return MemoryTimelineEntry(
            revision_id=revision.id,
            memory_id=revision.memory_id,
            event_type=revision.revision_type.value,
            event_label=self._revision_label(revision.revision_type),
            title=title,
            content_preview=preview,
            actor_label=self._actor_label(revision.actor),
            reason=revision.reason or "未提供额外原因",
            occurred_at=revision.created_at,
            status=status,
            forgotten=forgotten,
        )

    @staticmethod
    def _source_explanation(source: str) -> tuple[str, str]:
        normalized = (source or "unknown").strip().lower()
        explanations = {
            "bootstrap": ("设置同步", "来自你在设置中填写的身份信息"),
            "strong_signal": ("你明确告诉我", "来自你在对话中明确表达的事实"),
            "manual": ("手动添加", "由你主动创建或维护"),
            "user": ("你已确认", "由你在记忆控制台确认"),
            "user_correction": ("你已校正", "由你在记忆控制台修正"),
            "ai": ("对话提取", "从对话中提取，保留置信度供你校正"),
            "ai_patch": ("对话提取", "从对话分析生成的结构化记忆"),
            "exit_analysis": ("会话收尾", "在会话结束分析中提取"),
            "migration": ("历史迁移", "从旧版本地记忆文件迁移"),
            "dream": ("离线整理", "由本地记忆维护流程整理"),
        }
        return explanations.get(
            normalized,
            (source or "历史来源", "来源信息有限，可由你确认或修正"),
        )

    @staticmethod
    def _revision_label(revision_type: MemoryRevisionType) -> str:
        return {
            MemoryRevisionType.LEARNED: "最初记住",
            MemoryRevisionType.CONFIRMED: "再次确认",
            MemoryRevisionType.CORRECTED: "内容校正",
            MemoryRevisionType.RETIRED: "停止使用",
            MemoryRevisionType.RESTORED: "恢复使用",
            MemoryRevisionType.FORGOTTEN: "永久忘记",
            MemoryRevisionType.CONFLICT_RESOLVED: "冲突已裁决",
            MemoryRevisionType.FLAGGED_INACCURATE: "标记内容不准确",
            MemoryRevisionType.EXPIRED: "到期停用",
        }[revision_type]

    @staticmethod
    def _actor_label(actor: str) -> str:
        normalized = (actor or "system").strip().lower()
        if normalized in {"user", "manual", "user_correction"}:
            return "你"
        if normalized in {"ai", "ai_patch", "exit_analysis", "strong_signal"}:
            return "Lobuddy"
        if normalized in {"bootstrap", "migration", "maintenance", "system"}:
            return "系统"
        return actor or "系统"

    @staticmethod
    def _type_label(memory_type: MemoryType) -> str:
        return {
            MemoryType.USER_PROFILE: "关于你的信息",
            MemoryType.SYSTEM_PROFILE: "伙伴身份",
            MemoryType.PROJECT_MEMORY: "项目记忆",
            MemoryType.CONVERSATION_SUMMARY: "会话摘要",
            MemoryType.EPISODIC_MEMORY: "共同经历",
            MemoryType.PROCEDURAL_MEMORY: "做事方法",
        }[memory_type]

    @staticmethod
    def _preview(content: str, limit: int = 96) -> str:
        compact = " ".join(content.split())
        return compact if len(compact) <= limit else compact[: limit - 1] + "…"
