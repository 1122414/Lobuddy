"""Content-minimized projections for Lobuddy's relationship rhythm."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from core.companion.models import CompanionCheckIn, CompanionPreferenceSummary


class RelationshipMemoryKind(str, Enum):
    """Relationship-facing groups backed by Structured Memory."""

    PREFERENCE = "preference"
    SHARED_MOMENT = "shared_moment"
    WORKING_STYLE = "working_style"


class RelationshipMemoryEvidence(BaseModel):
    """One sanitized Structured Memory shown as relationship evidence."""

    memory_id: str
    kind: RelationshipMemoryKind
    kind_label: str
    title: str
    preview: str
    source_label: str
    trust_label: str
    status_label: str
    updated_at: datetime


class GrowthTraitEvidence(BaseModel):
    """One task-grounded PetPersonality dimension, never a user emotion claim."""

    dimension: str
    label: str
    value: float = Field(ge=0.0, le=100.0)
    delta_from_baseline: float
    evidence_count: int = Field(default=0, ge=0)
    explanation: str


class RelationshipRhythmSnapshot(BaseModel):
    """A deterministic projection over existing governed relationship adapters."""

    generated_at: datetime
    privacy_active: bool = False
    headline: str
    guidance: str
    memories: list[RelationshipMemoryEvidence] = Field(default_factory=list)
    active_memory_count: int = Field(default=0, ge=0)
    explicitly_confirmed_count: int = Field(default=0, ge=0)
    pending_review_count: int = Field(default=0, ge=0)
    preference_summary: CompanionPreferenceSummary = Field(
        default_factory=CompanionPreferenceSummary
    )
    active_check_in: CompanionCheckIn | None = None
    growth_traits: list[GrowthTraitEvidence] = Field(default_factory=list)
    personality_version_count: int = Field(default=0, ge=0)
