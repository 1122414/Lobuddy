"""Structured memory service for Lobuddy."""

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Optional

from core.config import Settings
from core.memory.memory_conflict_resolver import MemoryConflictResolver
from core.memory.memory_projection import MemoryProjection
from core.memory.memory_prompts import MEMORY_UPDATE_PROMPT
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    ConflictCandidate,
    MemoryContextEvidence,
    MemoryItem,
    MemoryPatch,
    MemoryPatchAction,
    MemoryPatchItem,
    MemoryRecallFeedback,
    MemoryRecallReceipt,
    MemoryRevision,
    MemoryRevisionType,
    MemoryStatus,
    MemoryType,
    PromptContextBundle,
)
from core.memory.memory_selector import MemorySelector
from core.memory.privacy_mode import PrivacyModeManager

logger = logging.getLogger(__name__)


_SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$")


def sanitize_memory_text(text: str) -> str:
    """Sanitize memory text before storage."""
    sanitized = text
    for pattern, replacement in [
        (r"sk-[a-zA-Z0-9]{20,}", "sk-***"),
        (r"ghp_[a-zA-Z0-9]{36}", "ghp_***"),
        (r"xoxb-[a-zA-Z0-9-]+", "xoxb-***"),
        (r"Bearer\s+[a-zA-Z0-9._-]+", "Bearer ***"),
    ]:
        sanitized = re.sub(pattern, replacement, sanitized)
    return sanitized


# Backward-compatible private alias for older internal call sites.
_sanitize_memory_text = sanitize_memory_text


def _extract_json(text: str) -> str | None:
    block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if block:
        return block.group(1).strip()

    start = text.find("[")
    if start != -1:
        end = text.rfind("]")
        if end > start:
            return text[start : end + 1]

    start = text.find("{")
    if start != -1:
        end = text.rfind("}")
        if end > start:
            return text[start : end + 1]
    return None


def _parse_legacy_user_md(text: str) -> list[tuple[str, str]]:
    """Parse the old USER.md projection into (section, item) pairs."""
    result: list[tuple[str, str]] = []
    current = "Basic Notes"
    for line in text.splitlines():
        header = _SECTION_HEADER_RE.match(line)
        if header:
            current = header.group(1).strip() or "Basic Notes"
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            item = stripped[2:].strip()
            if item:
                result.append((current, item))
    return result


def _deduplicate_items(items: list[MemoryItem]) -> list[MemoryItem]:
    """Remove duplicate items by content, keeping the most recent."""
    seen: dict[str, MemoryItem] = {}
    for item in items:
        key = item.content.strip().lower()
        if key in seen:
            if item.updated_at > seen[key].updated_at:
                seen[key] = item
        else:
            seen[key] = item
    return list(seen.values())


def _compress_memories(items: list[MemoryItem], max_chars: int) -> list[MemoryItem]:
    """Compress memories to fit within budget."""
    if not items:
        return []
    total = sum(len(item.content) for item in items)
    if total <= max_chars:
        return items
    target = max_chars / total
    result = []
    for item in items:
        current_len = len(item.content)
        new_len = int(current_len * target)
        if new_len < 10:
            new_len = 10
        if new_len < current_len:
            current = item.content[:new_len] + "..."
            result.append(
                MemoryItem(
                    id=item.id,
                    memory_type=item.memory_type,
                    content=current,
                    source=item.source,
                    confidence=item.confidence,
                    importance=item.importance,
                )
            )
        else:
            result.append(item)
    return result


class MemoryService:
    """Orchestrates structured memory storage, projection, and prompt context injection."""

    def __init__(
        self,
        settings: Settings,
        repo: MemoryRepository | None = None,
        privacy: PrivacyModeManager | None = None,
    ) -> None:
        self._settings = settings
        self._repo = repo or MemoryRepository()
        self._privacy = privacy
        self._projection = MemoryProjection(settings.data_dir, settings.workspace_path)
        self._selector = MemorySelector(settings, self._repo, privacy=privacy)
        if settings.memory_enable_migration:
            self._maybe_migrate_from_legacy()
        self._deprecate_invalid_identity_memories()
        self._ensure_bootstrap_memories()

    def update_settings(self, settings: Settings) -> None:
        """Refresh recall policy without replacing the repository or privacy state."""
        self._settings = settings
        self._selector = MemorySelector(
            settings,
            self._repo,
            privacy=self._privacy,
        )

    def save_memory(self, item: MemoryItem) -> MemoryItem:
        saved = self._save_memory_with_revision(item)
        self._refresh_projections()
        return saved

    def save_memories(self, items: list[MemoryItem]) -> list[MemoryItem]:
        saved = [self._save_memory_with_revision(item) for item in items]
        if saved:
            self._refresh_projections()
        return saved

    def _save_memory_with_revision(self, item: MemoryItem) -> MemoryItem:
        existing = self._repo.get(item.id)
        item.content = _sanitize_memory_text(item.content)
        item.updated_at = datetime.now()
        if existing is None:
            revision_type = MemoryRevisionType.LEARNED
            reason = "Lobuddy 首次保存这条记忆"
            previous_content = ""
        elif existing.content == item.content:
            revision_type = MemoryRevisionType.CONFIRMED
            reason = "这条记忆被再次确认"
            previous_content = existing.content
        else:
            revision_type = MemoryRevisionType.CORRECTED
            reason = "这条记忆被更新"
            previous_content = existing.content
        saved = self._repo.save_with_revision(
            item,
            self._make_revision(
                item,
                revision_type,
                actor=item.source or "system",
                reason=reason,
                previous_content=previous_content,
            ),
        )
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

    def deprecate_memory(
        self,
        item_id: str,
        reason: str = "用户选择暂时不再使用这条记忆",
        actor: str = "user",
    ) -> bool:
        item = self._repo.get(item_id)
        if item is None:
            return False
        revision = self._make_revision(
            item,
            MemoryRevisionType.RETIRED,
            actor=actor,
            reason=reason,
            previous_content=item.content,
            new_content=item.content,
        )
        ok = self._repo.update_status_with_revision(
            item_id,
            MemoryStatus.DEPRECATED,
            revision,
        )
        if ok:
            self._refresh_projections()
        return ok

    def restore_memory(
        self,
        item_id: str,
        reason: str = "用户恢复使用这条记忆",
        actor: str = "user",
    ) -> bool:
        item = self._repo.get(item_id)
        if item is None:
            return False
        revision = self._make_revision(
            item,
            MemoryRevisionType.RESTORED,
            actor=actor,
            reason=reason,
            previous_content=item.content,
            new_content=item.content,
        )
        ok = self._repo.update_status_with_revision(
            item_id,
            MemoryStatus.ACTIVE,
            revision,
        )
        if ok:
            self._refresh_projections()
        return ok

    def delete_memory(
        self,
        item_id: str,
        reason: str = "用户要求永久忘记这条记忆",
        actor: str = "user",
    ) -> bool:
        item = self._repo.get(item_id)
        if item is None:
            return False
        revision = self._make_revision(
            item,
            MemoryRevisionType.FORGOTTEN,
            actor=actor,
            reason=reason,
            previous_content=item.content,
            new_content="",
        )
        ok = self._repo.delete_with_revision(item_id, revision)
        if ok:
            self._refresh_projections()
        return ok

    def revise_memory(
        self,
        item_id: str,
        content: str,
        reason: str = "用户在记忆控制台修正内容",
        actor: str = "user",
    ) -> Optional[MemoryItem]:
        item = self._repo.get(item_id)
        if item is None:
            return None
        content = _sanitize_memory_text(content)
        if not content:
            return None
        if content == item.content:
            return self.confirm_memory(item_id, reason, actor)
        previous_content = item.content
        item.content = content
        item.confidence = 1.0
        item.status = MemoryStatus.ACTIVE
        item.updated_at = datetime.now()
        revision = self._make_revision(
            item,
            MemoryRevisionType.CORRECTED,
            actor=actor,
            reason=reason,
            previous_content=previous_content,
        )
        saved = self._repo.save_with_revision(item, revision)
        self._refresh_projections()
        return saved

    def edit_memory(self, item_id: str, content: str) -> bool:
        return self.revise_memory(item_id, content) is not None

    def confirm_memory(
        self,
        item_id: str,
        reason: str = "用户确认这条记忆仍然准确",
        actor: str = "user",
    ) -> Optional[MemoryItem]:
        item = self._repo.get(item_id)
        if item is None:
            return None
        item.confidence = 1.0
        item.status = MemoryStatus.ACTIVE
        item.updated_at = datetime.now()
        revision = self._make_revision(
            item,
            MemoryRevisionType.CONFIRMED,
            actor=actor,
            reason=reason,
            previous_content=item.content,
        )
        saved = self._repo.save_with_revision(item, revision)
        self._refresh_projections()
        return saved

    def list_revisions(
        self,
        memory_id: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRevision]:
        return self._repo.list_revisions(memory_id, limit)

    def apply_patch(self, patch: MemoryPatch) -> tuple[list[MemoryItem], list[MemoryPatchItem]]:
        """Apply a MemoryPatch. For business writes, prefer MemoryWriteGateway - this
        is retained for tests and internal low-level calls."""
        accepted: list[MemoryItem] = []
        rejected: list[MemoryPatchItem] = []
        min_confidence = getattr(self._settings, "memory_min_confidence", 0.75)

        for item in patch.items:
            if item.action == MemoryPatchAction.UNCERTAIN:
                rejected.append(item)
                continue
            if item.confidence < min_confidence:
                rejected.append(item)
                continue

            content = _sanitize_memory_text(item.content)
            if not content:
                rejected.append(item)
                continue

            existing = self._find_similar(item.memory_type, item.title)
            if item.action in {
                MemoryPatchAction.ADD,
                MemoryPatchAction.UPDATE,
                MemoryPatchAction.MERGE,
            }:
                if existing:
                    previous_content = existing.content
                    existing.content = content
                    existing.scope = item.scope or existing.scope
                    existing.confidence = max(existing.confidence, item.confidence)
                    existing.importance = max(existing.importance, item.importance)
                    existing.priority = self._priority_for(item.importance, item.memory_type)
                    existing.status = MemoryStatus.ACTIVE
                    revision_type = (
                        MemoryRevisionType.CONFIRMED
                        if previous_content == content
                        else MemoryRevisionType.CORRECTED
                    )
                    accepted.append(
                        self._repo.save_with_revision(
                            existing,
                            self._make_revision(
                                existing,
                                revision_type,
                                actor="ai",
                                reason=item.reason or "AI 根据对话更新了这条记忆",
                                previous_content=previous_content,
                            ),
                        )
                    )
                else:
                    new_memory = MemoryItem(
                        id=str(uuid.uuid4()),
                        memory_type=item.memory_type,
                        scope=item.scope,
                        title=item.title,
                        content=content,
                        source="ai",
                        confidence=item.confidence,
                        importance=item.importance,
                        priority=self._priority_for(item.importance, item.memory_type),
                    )
                    accepted.append(
                        self._repo.save_with_revision(
                            new_memory,
                            self._make_revision(
                                new_memory,
                                MemoryRevisionType.LEARNED,
                                actor="ai",
                                reason=item.reason or "AI 从对话中提取了这条记忆",
                            ),
                        )
                    )
            elif item.action in {MemoryPatchAction.REMOVE, MemoryPatchAction.DEPRECATE}:
                if existing:
                    revision = self._make_revision(
                        existing,
                        MemoryRevisionType.RETIRED,
                        actor="ai",
                        reason=item.reason or "AI 判断这条记忆已不再适用",
                        previous_content=existing.content,
                    )
                    if self._repo.update_status_with_revision(
                        existing.id,
                        MemoryStatus.DEPRECATED,
                        revision,
                    ):
                        existing.status = MemoryStatus.DEPRECATED
                        accepted.append(existing)
                    else:
                        rejected.append(item)
                else:
                    rejected.append(item)

        if accepted:
            self._refresh_projections()
        return accepted, rejected

    def apply_gateway_patch(
        self,
        patch: MemoryPatch,
        *,
        source: str,
        source_session_id: str | None = None,
        source_message_id: str | None = None,
    ) -> tuple[list[MemoryItem], list[MemoryPatchItem]]:
        """Apply a MemoryPatch already accepted by MemoryWriteGateway.

        Does NOT apply memory_min_confidence again — gateway owns business
        confidence policy for gateway writes. Provenance is written pre-save.
        """
        accepted: list[MemoryItem] = []
        rejected: list[MemoryPatchItem] = []

        for item in patch.items:
            if item.action == MemoryPatchAction.UNCERTAIN:
                rejected.append(item)
                continue

            content = _sanitize_memory_text(item.content)
            if not content:
                rejected.append(item)
                continue

            existing = self._find_similar(item.memory_type, item.title)
            if item.action in {
                MemoryPatchAction.ADD,
                MemoryPatchAction.UPDATE,
                MemoryPatchAction.MERGE,
            }:
                if existing:
                    previous_content = existing.content
                    existing.content = content
                    existing.scope = item.scope or existing.scope
                    existing.confidence = max(existing.confidence, item.confidence)
                    existing.importance = max(existing.importance, item.importance)
                    existing.priority = self._priority_for(item.importance, item.memory_type)
                    existing.status = MemoryStatus.ACTIVE
                    existing.source = source
                    existing.source_session_id = source_session_id
                    existing.source_message_id = source_message_id
                    revision_type = (
                        MemoryRevisionType.CONFIRMED
                        if previous_content == content
                        else MemoryRevisionType.CORRECTED
                    )
                    accepted.append(
                        self._repo.save_with_revision(
                            existing,
                            self._make_revision(
                                existing,
                                revision_type,
                                actor=source,
                                reason=item.reason or "记忆写入网关更新了这条记忆",
                                previous_content=previous_content,
                            ),
                        )
                    )
                else:
                    new_memory = MemoryItem(
                        id=str(uuid.uuid4()),
                        memory_type=item.memory_type,
                        scope=item.scope,
                        title=item.title,
                        content=content,
                        source=source,
                        source_session_id=source_session_id,
                        source_message_id=source_message_id,
                        confidence=item.confidence,
                        importance=item.importance,
                        priority=self._priority_for(item.importance, item.memory_type),
                    )
                    accepted.append(
                        self._repo.save_with_revision(
                            new_memory,
                            self._make_revision(
                                new_memory,
                                MemoryRevisionType.LEARNED,
                                actor=source,
                                reason=item.reason or "记忆写入网关保存了这条记忆",
                            ),
                        )
                    )
            elif item.action in {MemoryPatchAction.REMOVE, MemoryPatchAction.DEPRECATE}:
                if existing:
                    existing.source = source
                    existing.source_session_id = source_session_id
                    existing.source_message_id = source_message_id
                    revision = self._make_revision(
                        existing,
                        MemoryRevisionType.RETIRED,
                        actor=source,
                        reason=item.reason or "记忆写入网关停用了这条记忆",
                        previous_content=existing.content,
                    )
                    if self._repo.update_status_with_revision(
                        existing.id,
                        MemoryStatus.DEPRECATED,
                        revision,
                    ):
                        existing.status = MemoryStatus.DEPRECATED
                        accepted.append(existing)
                    else:
                        rejected.append(item)
                else:
                    rejected.append(item)

        if accepted:
            self._refresh_projections()
        return accepted, rejected

    def import_review_memories(
        self,
        package_id: str,
        candidates: list[tuple[MemoryPatchItem, str]],
    ) -> tuple[list[MemoryItem], list[str]]:
        """Atomically persist untrusted portable content as review-only memory."""
        prepared: list[tuple[MemoryItem, MemoryRevision, str]] = []
        for candidate, entry_digest in candidates:
            if candidate.action != MemoryPatchAction.ADD:
                raise ValueError("Memory imports only accept ADD candidates")
            content = sanitize_memory_text(candidate.content).strip()
            title = sanitize_memory_text(candidate.title).strip()[:120]
            if not content:
                raise ValueError("Imported memory content cannot be empty")
            item = MemoryItem(
                id=str(uuid.uuid4()),
                memory_type=candidate.memory_type,
                scope=candidate.scope.strip() or "global",
                title=title,
                content=content,
                source="import",
                source_session_id=None,
                source_message_id=None,
                confidence=min(0.5, candidate.confidence),
                importance=candidate.importance,
                priority=self._priority_for(candidate.importance, candidate.memory_type),
                status=MemoryStatus.NEEDS_REVIEW,
            )
            prepared.append(
                (
                    item,
                    self._make_revision(
                        item,
                        MemoryRevisionType.LEARNED,
                        actor="import",
                        reason=candidate.reason or "从记忆迁移包导入，等待用户确认",
                    ),
                    entry_digest,
                )
            )
        saved, skipped = self._repo.save_import_batch(package_id, prepared)
        if saved:
            self._refresh_projections()
        return saved, skipped

    def save_review_memories(self, items: list[MemoryItem]) -> list[MemoryItem]:
        """Persist high-importance uncertain memories for explicit user review."""
        prepared: list[tuple[MemoryItem, MemoryRevision]] = []
        for item in items:
            item.title = sanitize_memory_text(item.title).strip()[:120]
            item.content = sanitize_memory_text(item.content).strip()
            if not item.content:
                raise ValueError("Review memory content cannot be empty")
            item.status = MemoryStatus.NEEDS_REVIEW
            item.priority = self._priority_for(item.importance, item.memory_type)
            item.updated_at = datetime.now()
            prepared.append(
                (
                    item,
                    self._make_revision(
                        item,
                        MemoryRevisionType.LEARNED,
                        actor=item.source or "ai",
                        reason="内容较重要但仍不确定，等待用户确认",
                    ),
                )
            )
        saved = self._repo.save_many_with_revisions(prepared)
        if saved:
            self._refresh_projections()
        return saved

    def apply_ai_response(self, ai_response: str) -> tuple[bool, str]:
        try:
            json_str = _extract_json(ai_response)
            if not json_str:
                return False, "No JSON found in response"

            data = json.loads(json_str)
            raw_items = [data] if isinstance(data, dict) else data
            if not isinstance(raw_items, list):
                return False, "Invalid JSON format"

            max_items = getattr(self._settings, "memory_update_max_patch_items", 8)
            patch_items: list[MemoryPatchItem] = []
            for raw in raw_items[:max_items]:
                try:
                    patch_items.append(MemoryPatchItem(**raw))
                except Exception as exc:
                    logger.warning("Skipping invalid memory patch item: %s", exc)

            if not patch_items:
                return False, "No valid patch items"

            accepted, rejected = self.apply_patch(MemoryPatch(items=patch_items))
            if not accepted:
                return False, f"All {len(rejected)} items rejected"
            message = f"Updated {len(accepted)} memory items"
            if rejected:
                message += f", rejected {len(rejected)}"
            return True, message
        except json.JSONDecodeError as exc:
            return False, f"Invalid JSON: {exc}"
        except Exception as exc:
            logger.warning("Memory AI response failed: %s", exc)
            return False, f"Error: {exc}"

    def parse_ai_response_to_patch(self, ai_response: str) -> MemoryPatch | None:
        """Parse nanobot AI response into a MemoryPatch. Does NOT apply it.

        This separates JSON extraction from write discipline — the caller
        (typically MemoryWriteGateway) decides whether to accept/reject.
        """
        try:
            json_str = _extract_json(ai_response)
            if not json_str:
                logger.debug("No JSON found in AI response")
                return None

            data = json.loads(json_str)
            raw_items = [data] if isinstance(data, dict) else data
            if not isinstance(raw_items, list):
                logger.debug("Invalid JSON format in AI response")
                return None

            max_items = getattr(self._settings, "memory_update_max_patch_items", 8)
            patch_items: list[MemoryPatchItem] = []
            for raw in raw_items[:max_items]:
                try:
                    patch_items.append(MemoryPatchItem(**raw))
                except Exception as exc:
                    logger.warning("Skipping invalid memory patch item: %s", exc)

            if not patch_items:
                return None
            return MemoryPatch(items=patch_items)
        except json.JSONDecodeError as exc:
            logger.debug("Invalid JSON in AI response: %s", exc)
            return None
        except Exception as exc:
            logger.warning("parse_ai_response_to_patch failed: %s", exc)
            return None

    def build_update_prompt(self, recent_messages: list[dict[str, str]]) -> str:
        current = self.build_prompt_context().build_injection_text() or "(empty)"
        conversation = "\n".join(
            f"{msg.get('role', 'unknown')}: "
            f"{_sanitize_memory_text(str(msg.get('content', '')))}"
            for msg in recent_messages
        )
        return MEMORY_UPDATE_PROMPT.format(current_memory=current, conversation=conversation)

    def build_prompt_context(
        self, user_message: str = "", session_id: str = ""
    ) -> PromptContextBundle:
        return self._selector.select_for_prompt(user_message, session_id)

    def record_recall(
        self,
        task_id: str,
        session_id: str,
        evidence: list[MemoryContextEvidence],
    ) -> int:
        """Persist receipts and return the reviewable count for this Task Run."""
        selected_at = datetime.now()
        receipts: list[MemoryRecallReceipt] = []
        seen: set[str] = set()
        for evidence_item in evidence:
            if (
                evidence_item.memory_type == MemoryType.CONVERSATION_SUMMARY
                or evidence_item.memory_id in seen
            ):
                continue
            memory = self._repo.get(evidence_item.memory_id)
            if memory is None:
                continue
            seen.add(evidence_item.memory_id)
            receipts.append(
                MemoryRecallReceipt(
                    task_id=task_id,
                    session_id=session_id,
                    memory_id=evidence_item.memory_id,
                    memory_type=memory.memory_type,
                    reason=self._sanitize_recall_reason(evidence_item.reason),
                    contributed_chars=evidence_item.chars,
                    memory_updated_at=memory.updated_at,
                    selected_at=selected_at,
                )
            )
        self._repo.save_recall_receipts(receipts)
        return self._repo.count_recall_receipts(task_id)

    @staticmethod
    def _sanitize_recall_reason(reason: str) -> str:
        """Keep receipt reasons bounded and free of common credentials or addresses."""
        sanitized = sanitize_memory_text(reason)
        sanitized = re.sub(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
            "[email]",
            sanitized,
        )
        return sanitized.strip()[:120]

    def record_recall_feedback(
        self,
        task_id: str,
        memory_id: str,
        feedback: MemoryRecallFeedback,
    ) -> tuple[bool, bool]:
        """Record one final user judgment; inaccurate content is paused for review."""
        item = self._repo.get(memory_id)
        if item is None:
            raise ValueError("Recalled memory no longer exists")
        revision = None
        if feedback == MemoryRecallFeedback.INACCURATE:
            revision = self._make_revision(
                item,
                MemoryRevisionType.FLAGGED_INACCURATE,
                actor="user",
                reason="用户在本次回答的记忆反馈中标记内容不准确",
                previous_content=item.content,
                new_content=item.content,
            )
        recorded, paused = self._repo.record_recall_feedback(
            task_id,
            memory_id,
            feedback,
            revision=revision,
        )
        if recorded and feedback == MemoryRecallFeedback.INACCURATE:
            self._refresh_projections()
        return recorded, paused

    def upsert_identity_memory(
        self,
        *,
        memory_type: MemoryType,
        title: str,
        content: str,
        source: str,
        source_session_id: str | None = None,
        source_message_id: str | None = None,
        confidence: float = 0.95,
        importance: float = 0.9,
    ) -> MemoryItem:
        """Upsert an identity-level memory (user name, pet name, etc.).

        If an identical content match exists, updates its provenance
        (source/source_session_id/source_message_id/updated_at) to record
        the most recent confirmation source ("recent provenance" strategy).
        """
        content = _sanitize_memory_text(content)
        if self._is_invalid_identity_memory(content):
            raise ValueError(f"Refusing invalid identity memory: {content}")
        existing = self._find_similar(memory_type, title)
        if existing and existing.content == content:
            existing.source = source
            existing.source_session_id = source_session_id or existing.source_session_id
            existing.source_message_id = source_message_id or existing.source_message_id
            existing.updated_at = datetime.now()
            existing.confidence = max(existing.confidence, confidence)
            existing.importance = max(existing.importance, importance)
            self._repo.save_with_revision(
                existing,
                self._make_revision(
                    existing,
                    MemoryRevisionType.CONFIRMED,
                    actor=source,
                    reason="身份信息在后续对话中被再次确认",
                    previous_content=existing.content,
                ),
            )
            self._refresh_projections()
            return existing

        item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=memory_type,
            scope="global",
            title=title,
            content=content,
            source=source,
            source_session_id=source_session_id,
            source_message_id=source_message_id,
            confidence=confidence,
            importance=importance,
            priority=self._priority_for(importance, memory_type),
        )
        saved = self._repo.save_with_revision(
            item,
            self._make_revision(
                item,
                MemoryRevisionType.LEARNED,
                actor=source,
                reason="从明确身份信息中学习",
            ),
        )
        self.detect_conflicts_for_item(saved)
        self._refresh_projections()
        return saved

    def _find_similar(self, memory_type: MemoryType, title: str) -> Optional[MemoryItem]:
        items = self._repo.list_by_type(memory_type, MemoryStatus.ACTIVE, limit=100)
        for item in items:
            if item.title == title:
                return item
        return None

    def _refresh_projections(self) -> None:
        try:
            all_items: list[MemoryItem] = []
            for mt in MemoryType:
                all_items.extend(self._repo.list_by_type(mt, limit=1000))
            self._projection.project_all(all_items)
        except Exception as exc:
            logger.warning("Projection refresh failed: %s", exc)

    def _maybe_migrate_from_legacy(self) -> None:
        profile_path = self._settings.memory_profile_file
        if not profile_path.exists():
            return
        try:
            if self._repo.list_by_type(MemoryType.USER_PROFILE, limit=1):
                return
            legacy_items = _parse_legacy_user_md(profile_path.read_text(encoding="utf-8"))
            migrated = 0
            for section, content in legacy_items:
                clean = _sanitize_memory_text(content)
                if not clean:
                    continue
                migrated_item = MemoryItem(
                    id=str(uuid.uuid4()),
                    memory_type=MemoryType.USER_PROFILE,
                    scope="global",
                    title=section,
                    content=clean,
                    source="migration",
                    confidence=0.9,
                    importance=0.7,
                    priority=70,
                )
                self._repo.save_with_revision(
                    migrated_item,
                    self._make_revision(
                        migrated_item,
                        MemoryRevisionType.LEARNED,
                        actor="migration",
                        reason="从旧版本地记忆文件迁移",
                    ),
                )
                migrated += 1
            if migrated > 0:
                logger.info("Migrated %d items from legacy USER.md", migrated)
                backup = profile_path.with_suffix(".md.bak")
                try:
                    profile_path.rename(backup)
                except OSError:
                    pass
                self._refresh_projections()
        except Exception as exc:
            logger.warning("Legacy migration failed: %s", exc)

    def _ensure_bootstrap_memories(self) -> None:
        try:
            pet_name = self._settings.pet_name or "Lobuddy"
            expected_system = f"My name is {pet_name}. I am an AI desktop pet assistant."
            system_items = self._repo.list_by_type(
                MemoryType.SYSTEM_PROFILE, MemoryStatus.ACTIVE, limit=100
            )
            bootstrap_system = [item for item in system_items if item.source == "bootstrap"]
            if bootstrap_system:
                for item in bootstrap_system:
                    if item.content != expected_system:
                        previous_content = item.content
                        item.content = expected_system
                        item.updated_at = datetime.now()
                        self._repo.save_with_revision(
                            item,
                            self._make_revision(
                                item,
                                MemoryRevisionType.CORRECTED,
                                actor="bootstrap",
                                reason="设置中的伙伴名称发生变化",
                                previous_content=previous_content,
                            ),
                        )
            else:
                system_item = MemoryItem(
                    id=str(uuid.uuid4()),
                    memory_type=MemoryType.SYSTEM_PROFILE,
                    scope="global",
                    title="Identity",
                    content=expected_system,
                    source="bootstrap",
                    confidence=1.0,
                    importance=0.9,
                    priority=90,
                )
                self._repo.save_with_revision(
                    system_item,
                    self._make_revision(
                        system_item,
                        MemoryRevisionType.LEARNED,
                        actor="bootstrap",
                        reason="从设置同步伙伴身份",
                    ),
                )

            user_name = self._settings.user_name.strip()
            user_items = self._repo.list_by_type(
                MemoryType.USER_PROFILE, MemoryStatus.ACTIVE, limit=100
            )
            bootstrap_user = [item for item in user_items if item.source == "bootstrap"]
            if user_name:
                expected_user = f"The user's name is {user_name}."
                if bootstrap_user:
                    for item in bootstrap_user:
                        if item.content != expected_user:
                            previous_content = item.content
                            item.content = expected_user
                            item.updated_at = datetime.now()
                            self._repo.save_with_revision(
                                item,
                                self._make_revision(
                                    item,
                                    MemoryRevisionType.CORRECTED,
                                    actor="bootstrap",
                                    reason="设置中的用户名称发生变化",
                                    previous_content=previous_content,
                                ),
                            )
                else:
                    user_item = MemoryItem(
                        id=str(uuid.uuid4()),
                        memory_type=MemoryType.USER_PROFILE,
                        scope="global",
                        title="Basic Notes",
                        content=expected_user,
                        source="bootstrap",
                        confidence=1.0,
                        importance=0.9,
                        priority=90,
                    )
                    self._repo.save_with_revision(
                        user_item,
                        self._make_revision(
                            user_item,
                            MemoryRevisionType.LEARNED,
                            actor="bootstrap",
                            reason="从设置同步用户身份",
                        ),
                    )
            else:
                for item in bootstrap_user:
                    self._repo.update_status_with_revision(
                        item.id,
                        MemoryStatus.DEPRECATED,
                        self._make_revision(
                            item,
                            MemoryRevisionType.RETIRED,
                            actor="bootstrap",
                            reason="设置中的用户名称已清空",
                            previous_content=item.content,
                        ),
                    )

            self._refresh_projections()
        except Exception as exc:
            logger.warning("Bootstrap memories failed: %s", exc)

    def refresh_bootstrap_memories(self) -> None:
        self._deprecate_invalid_identity_memories()
        self._ensure_bootstrap_memories()

    def resolve_conflicts(self, memory_type: MemoryType, scope: str = "global") -> int:
        resolved = 0
        try:
            items = self._repo.list_by_type(memory_type, MemoryStatus.ACTIVE, scope, limit=100)
            by_content: dict[str, list[MemoryItem]] = {}
            for item in items:
                key = f"{item.title}:{item.content[:80]}"
                by_content.setdefault(key, []).append(item)

            for group in by_content.values():
                if len(group) < 2:
                    continue
                group.sort(key=lambda x: x.confidence, reverse=True)
                winner = group[0]
                for item in group[1:]:
                    if item.confidence >= winner.confidence:
                        self._repo.update_status(item.id, MemoryStatus.NEEDS_REVIEW)
                    else:
                        self._repo.update_status(item.id, MemoryStatus.DEPRECATED)
                    resolved += 1
            if resolved > 0:
                self._refresh_projections()
        except Exception as exc:
            logger.warning("Conflict resolution failed: %s", exc)
        return resolved

    def cleanup_expired(self) -> int:
        cleaned = 0
        try:
            for mt in MemoryType:
                items = self._repo.list_by_type(mt, MemoryStatus.ACTIVE, limit=1000)
                for item in items:
                    if item.is_expired():
                        revision = self._make_revision(
                            item,
                            MemoryRevisionType.EXPIRED,
                            actor="maintenance",
                            reason="这条记忆到达预设有效期",
                            previous_content=item.content,
                        )
                        if self._repo.update_status_with_revision(
                            item.id,
                            MemoryStatus.DEPRECATED,
                            revision,
                        ):
                            cleaned += 1
            if cleaned > 0:
                self._refresh_projections()
        except Exception as exc:
            logger.warning("Expired cleanup failed: %s", exc)
        return cleaned

    def detect_conflicts(
        self,
        memory_type: MemoryType,
        scope: str = "global",
    ) -> list[ConflictCandidate]:
        resolver = MemoryConflictResolver(self._repo, self._settings)
        return resolver.detect_conflicts(memory_type, scope)

    def detect_conflicts_for_item(self, item: MemoryItem) -> list[ConflictCandidate]:
        resolver = MemoryConflictResolver(self._repo, self._settings)
        return resolver.detect_conflicts_for_new_item(item)

    def list_pending_conflicts(self) -> list[ConflictCandidate]:
        resolver = MemoryConflictResolver(self._repo, self._settings)
        return resolver.list_pending()

    def resolve_conflict(
        self,
        candidate_id: str,
        accept_new: bool,
        reason: str = "用户在记忆控制台裁决了冲突",
        actor: str = "user",
    ) -> bool:
        resolver = MemoryConflictResolver(self._repo, self._settings)
        result = resolver.resolve_conflict(
            candidate_id,
            accept_new,
            actor=actor,
            reason=reason,
        )
        if result is not None:
            self._refresh_projections()
            return True
        return False

    def _deprecate_invalid_identity_memories(self) -> int:
        deprecated = 0
        try:
            for memory_type in (MemoryType.USER_PROFILE, MemoryType.SYSTEM_PROFILE):
                items = self._repo.list_by_type(memory_type, MemoryStatus.ACTIVE, limit=1000)
                for item in items:
                    if self._is_invalid_identity_memory(item.content):
                        revision = self._make_revision(
                            item,
                            MemoryRevisionType.RETIRED,
                            actor="maintenance",
                            reason="身份内容无效，已停止使用",
                            previous_content=item.content,
                        )
                        if self._repo.update_status_with_revision(
                            item.id,
                            MemoryStatus.DEPRECATED,
                            revision,
                        ):
                            deprecated += 1
            if deprecated:
                self._refresh_projections()
        except Exception as exc:
            logger.warning("Invalid identity cleanup failed: %s", exc)
        return deprecated

    @staticmethod
    def _make_revision(
        item: MemoryItem,
        revision_type: MemoryRevisionType,
        *,
        actor: str,
        reason: str,
        previous_content: str = "",
        new_content: str | None = None,
        related_memory_id: str | None = None,
    ) -> MemoryRevision:
        clean_actor = (actor or "system").strip()[:80] or "system"
        clean_reason = _sanitize_memory_text(reason).strip()[:500]
        if revision_type == MemoryRevisionType.FORGOTTEN:
            for sensitive_content in {item.content, previous_content}:
                if sensitive_content:
                    clean_reason = clean_reason.replace(sensitive_content, "[已移除]")
        current_content = item.content if new_content is None else new_content
        return MemoryRevision(
            id=str(uuid.uuid4()),
            memory_id=item.id,
            revision_type=revision_type,
            actor=clean_actor,
            reason=clean_reason,
            related_memory_id=related_memory_id,
            previous_content_hash=MemoryService._content_hash(previous_content),
            new_content_hash=MemoryService._content_hash(current_content),
        )

    @staticmethod
    def _content_hash(content: str) -> str:
        if not content:
            return ""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _priority_for(importance: float, memory_type: MemoryType) -> int:
        base = 50 + int(max(0.0, min(1.0, importance)) * 40)
        if memory_type in {MemoryType.USER_PROFILE, MemoryType.SYSTEM_PROFILE}:
            base += 10
        return max(1, min(100, base))

    @staticmethod
    def _is_invalid_identity_memory(content: str) -> bool:
        normalized = content.strip().lower().rstrip(".。!！?？")
        invalid_values = {"who", "what", "unknown", "谁", "什么"}
        if normalized in invalid_values:
            return True
        for prefix in ("the user's name is ", "my name is "):
            if normalized.startswith(prefix):
                value = normalized[len(prefix) :].split(".", 1)[0].strip()
                return value in invalid_values
        return False
