"""Durable Task Run models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from core.models.model_usage import ModelUsageEvidence
from core.models.pet import TaskDifficulty, TaskStatus


class RunUpdateKind(str, Enum):
    """Meaningful lifecycle changes within one Task Run."""

    QUEUED = "queued"
    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    RETRIED = "retried"


class RunUpdateStatus(str, Enum):
    """User-facing state of a Run Update."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"


class TaskRunOutcomeEvidence(BaseModel):
    """Content-free Task Run outcome projection for cross-domain verification."""

    task_id: str
    session_id: str = ""
    status: TaskStatus
    result_success: bool = False


class RunUpdate(BaseModel):
    """Append-only, privacy-safe progress for a Task Run."""

    id: str
    task_id: str
    kind: RunUpdateKind
    key: str = Field(default="", max_length=120)
    title: str = Field(default="", max_length=160)
    detail: str = Field(default="", max_length=500)
    status: RunUpdateStatus = RunUpdateStatus.RUNNING
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    stage_family: str = Field(default="", max_length=80)
    depends_on: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    estimated_duration_seconds: int = Field(default=0, ge=0, le=86_400)
    duration_ms: int = Field(default=0, ge=0, le=86_400_000)
    created_at: datetime = Field(default_factory=datetime.now)


class WorkStage(BaseModel):
    """Current projection of one keyed unit of Task Run progress."""

    key: str = Field(min_length=1, max_length=120)
    family: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=160)
    detail: str = Field(default="", max_length=500)
    status: RunUpdateStatus
    depends_on: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    blocked_by: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    estimated_duration_seconds: int = Field(default=0, ge=0, le=86_400)
    duration_ms: int = Field(default=0, ge=0, le=86_400_000)
    started_at: datetime
    finished_at: Optional[datetime] = None
    update_count: int = Field(default=1, ge=1)

    @property
    def completed(self) -> bool:
        return self.status == RunUpdateStatus.SUCCESS


class TaskRunSnapshot(BaseModel):
    """Read projection used by the task card and work record."""

    task_id: str
    input_summary: str
    session_id: str
    status: TaskStatus
    difficulty: TaskDifficulty
    attempt_no: int = 1
    parent_task_id: Optional[str] = None
    has_image: bool = False
    estimated_duration_seconds: int = 0
    estimated_token_usage: int = 0
    elapsed_seconds: int = 0
    estimated_remaining_seconds: int = 0
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    retryable: bool = False
    outcome_summary: str = ""
    error_message: str = ""
    usage_evidence: ModelUsageEvidence = Field(default_factory=ModelUsageEvidence)
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updates: list[RunUpdate] = Field(default_factory=list)
    stages: list[WorkStage] = Field(default_factory=list)
    critical_path: tuple[str, ...] = Field(default_factory=tuple)
    critical_path_remaining_seconds: int = Field(default=0, ge=0)

    @property
    def completed_stage_count(self) -> int:
        return sum(stage.completed for stage in self.stages)

    @property
    def waiting_stage_count(self) -> int:
        return sum(
            bool(stage.blocked_by) or stage.status == RunUpdateStatus.WARNING
            for stage in self.stages
        )
