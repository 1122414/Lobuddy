"""Deep Personality Evolution Module with task and restoration adapters."""

from __future__ import annotations

from core.models.personality import PetPersonality, PersonalityDimension
from core.models.pet import TaskDifficulty, TaskRecord
from core.personality.evolution_models import (
    PERSONALITY_TRAIT_LABELS,
    PersonalityEvolutionKind,
    PersonalityEvolutionResult,
    PersonalityExpression,
    PersonalityTraitDelta,
    PersonalityVersionView,
)
from core.personality.personality_engine import PersonalityEngine
from core.storage.personality_evolution_repo import PersonalityEvolutionRepository
from core.storage.pet_repo import PetRepository


class PersonalityEvolution:
    """Own versioning, restoration, and visible expression behind one Interface."""

    _KIND_LABELS = {
        PersonalityEvolutionKind.BASELINE: "历史起点",
        PersonalityEvolutionKind.TASK_COMPLETED: "任务成长",
        PersonalityEvolutionKind.RESTORED: "用户恢复",
    }
    _SOURCE_LABELS = {
        PersonalityEvolutionKind.BASELINE: "系统建立",
        PersonalityEvolutionKind.TASK_COMPLETED: "成功任务",
        PersonalityEvolutionKind.RESTORED: "你主动选择",
    }
    _TASK_DIFFICULTY_LABELS = {
        TaskDifficulty.SIMPLE: "简单",
        TaskDifficulty.MEDIUM: "中等",
        TaskDifficulty.COMPLEX: "复杂",
    }
    _EXPRESSION_COPY = {
        PersonalityDimension.FRIENDLINESS: (
            "亲和陪伴",
            "刚才的协作让我更懂得怎样温和地回应你。",
        ),
        PersonalityDimension.CURIOSITY: (
            "探索倾向",
            "刚才的协作让我更愿意先理解清楚，再和你一起行动。",
        ),
        PersonalityDimension.TECHNICAL_SKILL: (
            "技术协作",
            "刚才这次技术协作，让我更熟悉一起解决问题的节奏了。",
        ),
        PersonalityDimension.CREATIVITY: (
            "创意协作",
            "刚才的创作过程，让我更会陪你把想法慢慢变成方案。",
        ),
        PersonalityDimension.DILIGENCE: (
            "完成韧性",
            "又一起稳稳完成了一件事，我会继续陪你把过程守住。",
        ),
    }

    def __init__(
        self,
        *,
        pets: PetRepository | None = None,
        revisions: PersonalityEvolutionRepository | None = None,
    ) -> None:
        self._pets = pets or PetRepository()
        self._revisions = revisions or PersonalityEvolutionRepository(self._pets.db)

    def evolve_from_task(
        self,
        task: TaskRecord,
        *,
        pet_id: str = "default",
    ) -> PersonalityEvolutionResult:
        """Apply one idempotent, content-minimized task evolution."""
        pet = self._pets.get_or_create_pet(pet_id)
        before = pet.personality.model_copy(deep=True)
        requested = PersonalityEngine.analyze_task(task, before)
        after = before.model_copy(deep=True)
        PersonalityEngine.apply_adjustments(after, requested)
        actual = {
            dimension: round(
                float(getattr(after, dimension)) - float(getattr(before, dimension)),
                4,
            )
            for dimension in requested
        }
        difficulty = self._TASK_DIFFICULTY_LABELS[task.difficulty]
        revision, applied = self._revisions.apply_task_evolution(
            pet_id=pet_id,
            task_id=task.id,
            expected_before=before,
            after=after,
            adjustments=actual,
            reason=f"成功完成一次{difficulty}任务；仅保留成长维度，不保存任务正文",
        )
        return PersonalityEvolutionResult(
            applied=applied,
            revision=revision,
            expression=self.expression_for(revision.adjustments) if applied else None,
        )

    def restore(
        self,
        revision_id: str,
        *,
        pet_id: str = "default",
        reason: str = "这版更符合我希望的伙伴成长方式",
    ) -> PersonalityEvolutionResult:
        """Restore only PetPersonality and append a new user-authored version."""
        clean_reason = " ".join(reason.split()).strip()[:240]
        if not clean_reason:
            raise ValueError("恢复原因不能为空")
        revision, applied = self._revisions.restore(
            pet_id=pet_id,
            target_revision_id=revision_id,
            reason=clean_reason,
        )
        return PersonalityEvolutionResult(
            applied=applied,
            revision=revision,
            expression=self.expression_for(revision.adjustments) if applied else None,
        )

    def history(
        self,
        *,
        pet_id: str = "default",
        limit: int = 100,
    ) -> list[PersonalityVersionView]:
        """Return current-aware, content-minimized versions for UI and tests."""
        pet = self._pets.get_or_create_pet(pet_id)
        self._revisions.ensure_baseline(pet_id, pet.personality)
        revisions = self._revisions.list_revisions(pet_id, limit=limit)
        current = self._pets.get_or_create_pet(pet_id).personality
        current_dump = current.model_dump()
        views = []
        for revision in revisions:
            is_current = revision.after.model_dump() == current_dump
            deltas = self._trait_deltas(revision.adjustments)
            views.append(
                PersonalityVersionView(
                    revision_id=revision.id,
                    sequence=revision.sequence,
                    kind=revision.kind,
                    kind_label=self._KIND_LABELS[revision.kind],
                    source_label=self._SOURCE_LABELS[revision.kind],
                    summary=self._summary(revision.kind, deltas),
                    reason=revision.reason,
                    trait_deltas=deltas,
                    personality=revision.after.model_copy(deep=True),
                    created_at=revision.created_at,
                    is_current=is_current,
                    can_restore=not is_current,
                )
            )
        return views

    def version_count(self, *, pet_id: str = "default") -> int:
        """Return a count after ensuring a real baseline version exists."""
        pet = self._pets.get_or_create_pet(pet_id)
        self._revisions.ensure_baseline(pet_id, pet.personality)
        return self._revisions.count(pet_id)

    @classmethod
    def expression_for(
        cls,
        adjustments: dict[str, float],
    ) -> PersonalityExpression | None:
        """Map applied task evidence to one restrained visible pet expression."""
        dimensions = [
            PersonalityDimension(key)
            for key in adjustments
            if key in {dimension.value for dimension in PersonalityDimension}
        ]
        if not dimensions:
            return None
        dominant = max(
            dimensions,
            key=lambda dimension: (
                abs(float(adjustments.get(dimension.value, 0.0))),
                cls._dimension_priority(dimension),
            ),
        )
        label, message = cls._EXPRESSION_COPY[dominant]
        delta = float(adjustments.get(dominant.value, 0.0))
        badge = f"{label} +{delta:g}" if delta > 0 else f"{label} · 新证据"
        return PersonalityExpression(
            dominant_dimension=dominant,
            badge_text=badge,
            message=message,
        )

    @staticmethod
    def _trait_deltas(adjustments: dict[str, float]) -> list[PersonalityTraitDelta]:
        deltas = []
        for dimension in PersonalityDimension:
            if dimension.value not in adjustments:
                continue
            deltas.append(
                PersonalityTraitDelta(
                    dimension=dimension,
                    label=PERSONALITY_TRAIT_LABELS[dimension],
                    delta=float(adjustments[dimension.value]),
                )
            )
        return sorted(deltas, key=lambda item: abs(item.delta), reverse=True)

    @staticmethod
    def _summary(
        kind: PersonalityEvolutionKind,
        deltas: list[PersonalityTraitDelta],
    ) -> str:
        if kind == PersonalityEvolutionKind.BASELINE:
            return "保存启用版本历史时的五维成长状态"
        if not deltas:
            return "恢复了计数与成长状态，五维数值没有变化"
        parts = [
            f"{item.label} {item.delta:+g}" if item.delta else f"{item.label} · 新证据"
            for item in deltas[:3]
        ]
        return " · ".join(parts)

    @staticmethod
    def _dimension_priority(dimension: PersonalityDimension) -> int:
        order = {
            PersonalityDimension.TECHNICAL_SKILL: 5,
            PersonalityDimension.CREATIVITY: 4,
            PersonalityDimension.CURIOSITY: 3,
            PersonalityDimension.FRIENDLINESS: 2,
            PersonalityDimension.DILIGENCE: 1,
        }
        return order[dimension]
