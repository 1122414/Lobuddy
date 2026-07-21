"""Domain models for reversible, content-minimized pet personality evolution."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from core.models.personality import PetPersonality, PersonalityDimension


PERSONALITY_TRAIT_LABELS: dict[PersonalityDimension, str] = {
    PersonalityDimension.FRIENDLINESS: "亲和陪伴",
    PersonalityDimension.CURIOSITY: "探索倾向",
    PersonalityDimension.TECHNICAL_SKILL: "技术协作",
    PersonalityDimension.CREATIVITY: "创意协作",
    PersonalityDimension.DILIGENCE: "完成韧性",
}


class PersonalityEvolutionKind(str, Enum):
    """Why one durable personality version exists."""

    BASELINE = "baseline"
    TASK_COMPLETED = "task_completed"
    RESTORED = "restored"


class PersonalityEvolutionRevision(BaseModel):
    """One append-only transition between two PetPersonality snapshots."""

    id: str
    pet_id: str = "default"
    sequence: int = Field(ge=1)
    kind: PersonalityEvolutionKind
    actor: str = Field(default="system", min_length=1, max_length=40)
    task_id: str | None = None
    reason: str = Field(default="", max_length=240)
    adjustments: dict[str, float] = Field(default_factory=dict)
    before: PetPersonality
    after: PetPersonality
    restored_from_revision_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class PersonalityTraitDelta(BaseModel):
    """User-facing numeric change for one pet trait."""

    dimension: PersonalityDimension
    label: str
    delta: float


class PersonalityVersionView(BaseModel):
    """Calm UI projection of one Personality Evolution revision."""

    revision_id: str
    sequence: int = Field(ge=1)
    kind: PersonalityEvolutionKind
    kind_label: str
    source_label: str
    summary: str
    reason: str
    trait_deltas: list[PersonalityTraitDelta] = Field(default_factory=list)
    personality: PetPersonality
    created_at: datetime
    is_current: bool = False
    can_restore: bool = False


class PersonalityExpression(BaseModel):
    """Small visible expression grounded in an applied trait adjustment."""

    dominant_dimension: PersonalityDimension
    badge_text: str
    message: str
    state_hint: str = "success"


class PersonalityEvolutionResult(BaseModel):
    """Outcome shared by automatic task evolution and explicit restoration."""

    applied: bool
    revision: PersonalityEvolutionRevision
    expression: PersonalityExpression | None = None
