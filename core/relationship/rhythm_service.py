"""Relationship Rhythm Module over governed memories, care choices, and pet growth."""

from __future__ import annotations

from datetime import datetime

from core.companion.runtime import CompanionRuntime
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_schema import (
    MemoryItem,
    MemoryRevision,
    MemoryRevisionType,
    MemoryStatus,
    MemoryType,
)
from core.memory.privacy_mode import PrivacyModeManager
from core.models.personality import PersonalityDimension
from core.personality.evolution import PersonalityEvolution
from core.personality.evolution_models import PERSONALITY_TRAIT_LABELS
from core.relationship.models import (
    GrowthTraitEvidence,
    RelationshipMemoryEvidence,
    RelationshipMemoryKind,
    RelationshipRhythmSnapshot,
)
from core.storage.pet_repo import PetRepository


class RelationshipRhythmService:
    """Project evidence from three existing Adapters without inventing a score."""

    _RELATIONSHIP_TYPES = {
        MemoryType.USER_PROFILE,
        MemoryType.EPISODIC_MEMORY,
        MemoryType.PROCEDURAL_MEMORY,
    }
    _MEMORY_KIND = {
        MemoryType.USER_PROFILE: (RelationshipMemoryKind.PREFERENCE, "偏好与边界"),
        MemoryType.EPISODIC_MEMORY: (RelationshipMemoryKind.SHARED_MOMENT, "共同瞬间"),
        MemoryType.PROCEDURAL_MEMORY: (RelationshipMemoryKind.WORKING_STYLE, "协作方式"),
    }
    _TRAIT_EVIDENCE_LABELS = {
        PersonalityDimension.FRIENDLINESS: "沟通协作",
        PersonalityDimension.CURIOSITY: "探索与理解",
        PersonalityDimension.TECHNICAL_SKILL: "技术任务",
        PersonalityDimension.CREATIVITY: "创作与设计",
        PersonalityDimension.DILIGENCE: "成功完成",
    }

    def __init__(
        self,
        memory_control: MemoryControlService,
        companion: CompanionRuntime,
        *,
        pets: PetRepository | None = None,
        privacy: PrivacyModeManager | None = None,
        personality_evolution: PersonalityEvolution | None = None,
    ) -> None:
        self._memories = memory_control
        self._companion = companion
        self._pets = pets or PetRepository()
        self._privacy = privacy
        self._personality_evolution = personality_evolution or PersonalityEvolution(
            pets=self._pets
        )

    @property
    def personality_evolution(self) -> PersonalityEvolution:
        """Expose the governed Personality Evolution Interface to relationship UI."""
        return self._personality_evolution

    def snapshot(
        self,
        *,
        session_id: str = "",
        now: datetime | None = None,
        memory_limit: int = 6,
    ) -> RelationshipRhythmSnapshot:
        """Build a current, content-minimized view from governed evidence."""
        now = now or datetime.now()
        privacy_active = bool(
            self._privacy
            and session_id
            and self._privacy.is_privacy_active(session_id)
        )
        candidates = [
            item
            for item in self._memories.list_memories(limit=1000)
            if item.memory_type in self._RELATIONSHIP_TYPES
        ]
        active = [item for item in candidates if item.status == MemoryStatus.ACTIVE]
        pending = [item for item in candidates if item.status == MemoryStatus.NEEDS_REVIEW]
        revisions = self._revision_index(candidates)
        confirmed_ids = {
            memory_id
            for memory_id, item_revisions in revisions.items()
            if any(
                revision.actor in {"user", "manual", "user_correction"}
                and revision.revision_type
                in {
                    MemoryRevisionType.LEARNED,
                    MemoryRevisionType.CONFIRMED,
                    MemoryRevisionType.CORRECTED,
                    MemoryRevisionType.CONFLICT_RESOLVED,
                }
                for revision in item_revisions
            )
        }
        confirmed_ids.update(
            item.id
            for item in candidates
            if item.source in {"manual", "strong_signal", "user", "user_correction"}
        )

        visible = sorted(
            [*pending, *active],
            key=lambda item: (
                item.status != MemoryStatus.NEEDS_REVIEW,
                item.id not in confirmed_ids,
                -item.importance,
                -item.updated_at.timestamp(),
            ),
        )[: max(1, min(12, memory_limit))]
        memory_evidence = [
            self._memory_evidence(item, confirmed=item.id in confirmed_ids) for item in visible
        ]
        check_in = self._companion.active_check_in(now=now)
        if check_in is not None:
            headline = "我会按你刚刚选择的方式陪着你"
            guidance = "当前状态由你主动填写，只在有效期内影响陪伴方式。"
        elif active:
            headline = "我记得你明确留下的偏好，也会保留校正权"
            guidance = "这些内容来自可管理的结构化记忆，不来自屏幕上的情绪猜测。"
        else:
            headline = "我们的节奏可以从一句你愿意留下的话开始"
            guidance = "你可以主动告诉我一项偏好、一个共同瞬间或一种协作方式。"

        return RelationshipRhythmSnapshot(
            generated_at=now,
            privacy_active=privacy_active,
            headline=headline,
            guidance=guidance,
            memories=memory_evidence,
            active_memory_count=len(active),
            explicitly_confirmed_count=sum(item.id in confirmed_ids for item in active),
            pending_review_count=len(pending),
            preference_summary=self._companion.feedback_summary(now=now),
            active_check_in=check_in,
            growth_traits=self._growth_traits(),
            personality_version_count=self._personality_evolution.version_count(),
        )

    def clear_current_check_in(self) -> int:
        """Revoke the current user-authored Companion Check-in."""
        return self._companion.clear_check_in()

    def restore_care_boundaries(self) -> int:
        """Clear mute/snooze choices while retaining positive feedback evidence."""
        return self._companion.clear_feedback_preferences()

    def _memory_evidence(
        self,
        item: MemoryItem,
        *,
        confirmed: bool,
    ) -> RelationshipMemoryEvidence:
        kind, kind_label = self._MEMORY_KIND[item.memory_type]
        explanation = self._memories.explain_memory(item)
        if item.status == MemoryStatus.NEEDS_REVIEW:
            trust_label = "等待你确认"
            status_label = "不会作为稳定事实"
        elif item.source == "manual":
            trust_label = "你主动留下"
            status_label = "会在相关对话中使用"
        elif item.source == "strong_signal":
            trust_label = "你明确说过"
            status_label = "会在相关对话中使用"
        elif confirmed:
            trust_label = "你已确认"
            status_label = explanation.usage_label
        else:
            trust_label = explanation.trust_label
            status_label = explanation.usage_label
        return RelationshipMemoryEvidence(
            memory_id=item.id,
            kind=kind,
            kind_label=kind_label,
            title=item.title.strip() or kind_label,
            preview=self._preview(self._memories.get_sanitized_content(item)),
            source_label=explanation.source_label,
            trust_label=trust_label,
            status_label=status_label,
            updated_at=item.updated_at,
        )

    def _growth_traits(self) -> list[GrowthTraitEvidence]:
        personality = self._pets.get_or_create_pet().personality
        traits: list[GrowthTraitEvidence] = []
        for dimension, evidence_label in self._TRAIT_EVIDENCE_LABELS.items():
            label = PERSONALITY_TRAIT_LABELS[dimension]
            value = float(getattr(personality, dimension.value))
            evidence_count = sum(
                count
                for key, count in personality.interaction_counts.items()
                if key.startswith(f"{dimension.value}:")
            )
            if evidence_count:
                explanation = f"来自 {evidence_count} 次成功任务中的“{evidence_label}”线索"
            else:
                explanation = "当前为基础值，尚无成功任务证据"
            traits.append(
                GrowthTraitEvidence(
                    dimension=dimension.value,
                    label=label,
                    value=value,
                    delta_from_baseline=round(value - 50.0, 1),
                    evidence_count=evidence_count,
                    explanation=explanation,
                )
            )
        return sorted(
            traits,
            key=lambda trait: (-trait.delta_from_baseline, -trait.evidence_count, trait.label),
        )

    def _revision_index(self, items: list[MemoryItem]) -> dict[str, list[MemoryRevision]]:
        item_ids = {item.id for item in items}
        index: dict[str, list[MemoryRevision]] = {}
        for revision in self._memories.list_revisions(limit=1000):
            if revision.memory_id in item_ids:
                index.setdefault(revision.memory_id, []).append(revision)
        return index

    @staticmethod
    def _preview(content: str, limit: int = 112) -> str:
        compact = " ".join(content.split())
        return compact if len(compact) <= limit else compact[: limit - 1] + "…"
