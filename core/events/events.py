"""Domain events — pure Python dataclasses, no Qt dependency."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ==================== Subagent Events ====================


@dataclass
class SubagentSpawned:
    subagent_type: str
    task_id: str
    workspace: Path


@dataclass
class SubagentCompleted:
    subagent_type: str
    task_id: str
    success: bool
    summary: str


# ==================== Task Lifecycle Events ====================


@dataclass
class TaskQueued:
    task_id: str
    session_id: str
    queued_at: datetime = field(default_factory=datetime.now)


@dataclass
class TaskStarted:
    task_id: str
    started_at: datetime = field(default_factory=datetime.now)


@dataclass
class TaskCompleted:
    task_id: str
    session_id: str
    success: bool
    summary: str
    error_message: str
    completed_at: datetime = field(default_factory=datetime.now)


@dataclass
class TaskFailed:
    task_id: str
    session_id: str
    error_message: str
    failed_at: datetime = field(default_factory=datetime.now)


# ==================== Tool Call Events ====================


@dataclass
class ToolCallPlanned:
    task_id: str
    tool_name: str
    estimated_risk: str = "low"
    call_id: str = ""
    stage_key: str = ""


@dataclass
class ToolCallExecuted:
    task_id: str
    tool_name: str
    success: bool
    duration_ms: float = 0.0
    call_id: str = ""
    stage_key: str = ""


@dataclass
class ToolCallBlocked:
    task_id: str
    tool_name: str
    reason: str
    call_id: str = ""
    stage_key: str = ""


@dataclass
class ComputerUseProgress:
    """Privacy-safe progress for one recoverable desktop plan."""

    task_id: str
    plan_id: str
    phase: str
    step_key: str
    title: str
    detail: str = ""
    status: str = "running"
    step_index: int = 0
    max_actions: int = 0
    stage_family: str = ""
    depends_on: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=datetime.now)


# ==================== HITL Events ====================


@dataclass
class HitlRequested:
    task_id: str
    tool_name: str
    command_preview: str
    risk_tags: list[str] = field(default_factory=list)
    request_id: str = ""


@dataclass
class HitlApproved:
    task_id: str
    tool_name: str
    reason: str = ""
    request_id: str = ""


@dataclass
class HitlDenied:
    task_id: str
    tool_name: str
    reason: str = ""
    request_id: str = ""


@dataclass
class HitlTimeout:
    task_id: str
    tool_name: str
    request_id: str = ""


# ==================== Memory Events ====================


@dataclass
class MemoryProposed:
    memory_type: str
    title: str
    confidence: float


@dataclass
class MemoryAccepted:
    memory_type: str
    memory_id: str
    title: str


@dataclass
class MemoryRejected:
    memory_type: str
    title: str
    reason: str


@dataclass
class MemoryContextPrepared:
    """Content-minimized evidence for memory used by one task."""

    task_id: str
    session_id: str
    selected_count: int
    reviewable_count: int | None = None
    type_counts: dict[str, int] = field(default_factory=dict)
    total_chars: int = 0
    privacy_active: bool = False
    injection_enabled: bool = True


# ==================== Skill Events ====================


@dataclass
class SkillCandidateCreated:
    skill_name: str
    rationale: str
    confidence: float


@dataclass
class SkillCandidateApproved:
    skill_name: str
    skill_id: str


@dataclass
class SkillCandidateDisabled:
    skill_name: str
    skill_id: str
    reason: str = ""


# ==================== Pet Growth Events ====================


@dataclass
class TaskExpGained:
    amount: int
    current_exp: int
    required_exp: int
    level_up: bool


@dataclass
class TaskLevelUp:
    level: int
    stage: int


@dataclass
class TaskAbilityUnlocked:
    ability_id: str
    ability_name: str


# ==================== Focus Events ====================


@dataclass
class FocusSessionChanged:
    state: str
    seconds_remaining: int = 0


# ==================== Queue Events ====================


@dataclass
class QueueLengthUpdated:
    length: int
