"""Skill data schema for Lobuddy 5.2 skill system."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

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
    source_session_id: Optional[str] = Field(default=None, description="Originating session")
    success_count: int = Field(default=0, ge=0, description="Successful uses")
    failure_count: int = Field(default=0, ge=0, description="Failed uses")
    last_used_at: Optional[datetime] = Field(default=None, description="Last activation")
    review_after: Optional[datetime] = Field(default=None, description="Scheduled review date")
    expires_at: Optional[datetime] = Field(default=None, description="Optional expiration")
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
    session_id: Optional[str] = Field(default=None, description="Originating session")
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
    IMPORT = "import"


class EvaluationStatus(str, Enum):
    """Outcome of the isolated candidate package evaluation."""

    PASSED = "passed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class EvaluationCheckStatus(str, Enum):
    """Result of one deterministic evaluation check."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class ProvenanceStatus(str, Enum):
    """Independent verification state for candidate source evidence."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    NOT_REQUIRED = "not_required"


class BehaviorSimulationStatus(str, Enum):
    """Outcome of side-effect-free candidate behavior simulation."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_EVALUATED = "not_evaluated"


class SimulatedToolOutcome(str, Enum):
    """Synthetic tool outcome emitted without invoking a real tool."""

    PERMITTED = "permitted"
    REFUSED = "refused"


class EvaluationCheck(BaseModel):
    """One explainable result in a candidate evaluation report."""

    key: str
    title: str
    status: EvaluationCheckStatus
    detail: str = ""
    points: int = Field(default=0, ge=0)
    max_points: int = Field(default=0, ge=0)
    blocking: bool = False


class SkillPermissionProfile(BaseModel):
    """Permissions inferred from sanitized evidence and proposed content."""

    tools: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    risk_level: str = Field(default="low", pattern="^(low|medium|high)$")
    unknown_tools: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False


class SkillToolSimulationReceipt(BaseModel):
    """One content-free synthetic tool receipt."""

    scenario: str
    step_index: int = Field(default=0, ge=0)
    tool_name: str
    outcome: SimulatedToolOutcome
    capability: str = ""
    requires_confirmation: bool = False
    detail: str = ""


class SkillBehaviorSimulation(BaseModel):
    """Deterministic evidence from a side-effect-free declared-plan replay."""

    status: BehaviorSimulationStatus = BehaviorSimulationStatus.NOT_EVALUATED
    fingerprint: str = ""
    scenario_count: int = Field(default=0, ge=0)
    workflow_step_count: int = Field(default=0, ge=0)
    declared_tools: list[str] = Field(default_factory=list)
    simulated_tools: list[str] = Field(default_factory=list)
    refused_tools: list[str] = Field(default_factory=list)
    missing_tools: list[str] = Field(default_factory=list)
    undeclared_tools: list[str] = Field(default_factory=list)
    has_terminal_verification: bool = False
    has_refusal_policy: bool = False
    filesystem_accessed: bool = False
    network_accessed: bool = False
    commands_executed: bool = False
    summary: str = ""
    receipts: list[SkillToolSimulationReceipt] = Field(default_factory=list)


class SkillBehaviorEvidence(BaseModel):
    """Permissions and behavior proof produced behind one evaluation seam."""

    permissions: SkillPermissionProfile = Field(default_factory=SkillPermissionProfile)
    simulation: SkillBehaviorSimulation = Field(default_factory=SkillBehaviorSimulation)


class SkillCandidateProvenance(BaseModel):
    """Content-minimized proof that an evolved skill came from real work."""

    source_kind: CandidateSource = CandidateSource.MANUAL
    status: ProvenanceStatus = ProvenanceStatus.NOT_REQUIRED
    task_id: Optional[str] = None
    task_status: str = ""
    task_result_verified: bool = False
    session_binding_verified: bool = False
    declared_tools: list[str] = Field(default_factory=list)
    observed_tools: list[str] = Field(default_factory=list)
    missing_tools: list[str] = Field(default_factory=list)
    detail: str = ""


class SkillEvaluationReport(BaseModel):
    """Persistent, content-addressed evidence for approval gating."""

    id: str
    candidate_id: str
    candidate_revision: int = Field(default=1, ge=1)
    content_hash: str
    status: EvaluationStatus
    score: int = Field(default=0, ge=0, le=100)
    minimum_score: int = Field(default=75, ge=0, le=100)
    summary: str = ""
    checks: list[EvaluationCheck] = Field(default_factory=list)
    permissions: SkillPermissionProfile = Field(default_factory=SkillPermissionProfile)
    provenance: SkillCandidateProvenance = Field(default_factory=SkillCandidateProvenance)
    behavior: SkillBehaviorSimulation = Field(default_factory=SkillBehaviorSimulation)
    created_at: datetime = Field(default_factory=datetime.now)


class SkillCandidateRevision(BaseModel):
    """Immutable sanitized candidate content saved before approval."""

    id: str
    candidate_id: str
    revision: int = Field(ge=1)
    content_hash: str
    content: str
    created_at: datetime = Field(default_factory=datetime.now)


class SkillCandidateDiff(BaseModel):
    """Human-readable comparison between the latest two candidate revisions."""

    from_revision: int = Field(default=1, ge=1)
    to_revision: int = Field(default=1, ge=1)
    added_lines: int = Field(default=0, ge=0)
    removed_lines: int = Field(default=0, ge=0)
    changed: bool = False
    unified_diff: str = ""


class SkillCandidate(BaseModel):
    """A proposed skill before approval."""

    id: str = Field(..., description="Unique identifier")
    title: str = Field(..., description="Human-readable title")
    rationale: str = Field(..., description="Why this skill was proposed")
    proposed_name: str = Field(..., description="Suggested hyphenated name")
    proposed_content: str = Field(..., description="Proposed SKILL.md content")
    source_session_id: Optional[str] = Field(default=None, description="Originating session")
    source_task_id: Optional[str] = Field(default=None, description="Originating task")
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
    reject_reason: Optional[str] = Field(default=None, description="Reason for rejection")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
