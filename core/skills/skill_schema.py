"""Skill data schema for Lobuddy 5.2 skill system."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SkillStatus(str, Enum):
    """Valid skill statuses."""

    DRAFT = "draft"
    ACTIVE = "active"
    NEEDS_REVIEW = "needs_review"
    DISABLED = "disabled"
    ARCHIVED = "archived"
    DELETED = "deleted"


class SkillRecord(BaseModel):
    """A skill stored in SQLite and projected to SKILL.md."""

    id: str = Field(..., description="Unique identifier")
    name: str = Field(..., description="Short hyphenated name")
    path: str = Field(..., description="Path to SKILL.md file")
    description: str = Field(..., description="Trigger description")
    content: str = Field(default="", description="Recoverable SKILL.md source")
    category: str = Field(default="general", description="Skill category")
    status: SkillStatus = Field(default=SkillStatus.DRAFT, description="Lifecycle status")
    version: int = Field(default=1, ge=1, description="Version number")
    source: str = Field(default="manual", description="manual | auto | import")
    source_session_id: str | None = Field(default=None, description="Originating session")
    success_count: int = Field(default=0, ge=0, description="Successful uses")
    failure_count: int = Field(default=0, ge=0, description="Failed uses")
    last_used_at: datetime | None = Field(default=None, description="Last activation")
    review_after: datetime | None = Field(default=None, description="Scheduled review date")
    expires_at: datetime | None = Field(default=None, description="Optional expiration")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def failure_rate(self) -> float:
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.0
        return self.failure_count / total


class SkillEvent(BaseModel):
    """Audit event for a skill."""

    id: str = Field(..., description="Unique identifier")
    skill_id: str = Field(..., description="Referenced skill")
    event_type: str = Field(
        ...,
        description=(
            "create | patch | disable | enable | delete | use | review | "
            "archive | reject | validate"
        ),
    )
    detail: str = Field(default="", description="Event details")
    session_id: str | None = Field(default=None, description="Originating session")
    created_at: datetime = Field(default_factory=datetime.now)


class CandidateStatus(str, Enum):
    """Valid skill candidate statuses."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONVERTED = "converted"


class CandidateSource(str, Enum):
    """Trusted origin classification for a skill candidate."""

    MANUAL = "manual"
    SUCCESSFUL_TASK = "successful_task"
    DIAGNOSED_FAILURE = "diagnosed_failure"
    CORRECTION = "correction"
    IMPORT = "import"


class SkillCandidate(BaseModel):
    """A proposed skill before approval."""

    id: str = Field(..., description="Unique identifier")
    title: str = Field(..., description="Human-readable title")
    rationale: str = Field(..., description="Why this skill was proposed")
    proposed_name: str = Field(..., description="Suggested hyphenated name")
    proposed_content: str = Field(..., description="Proposed SKILL.md content")
    source_session_id: str | None = Field(default=None, description="Originating session")
    source_task_id: str | None = Field(default=None, description="Originating task")
    source_kind: CandidateSource = Field(
        default=CandidateSource.MANUAL,
        description="Trusted origin classification",
    )
    revision: int = Field(default=1, ge=1, description="Latest immutable proposal revision")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidence score")
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Sanitized evidence explaining why this proposal was created",
    )
    validation_errors: list[str] = Field(
        default_factory=list,
        description="Static validation findings captured before review",
    )
    status: CandidateStatus = Field(
        default=CandidateStatus.PENDING, description="Candidate lifecycle status"
    )
    reject_reason: str | None = Field(default=None, description="Reason for rejection")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
