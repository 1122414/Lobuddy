"""Content-minimized models for explicit Task Run recovery review."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RecoveryTone(StrEnum):
    SAFE = "safe"
    ATTENTION = "attention"
    BLOCKED = "blocked"
    NEUTRAL = "neutral"


class RecoveryEvidence(BaseModel):
    label: str = Field(max_length=32)
    value: str = Field(max_length=180)
    detail: str = Field(default="", max_length=300)
    tone: RecoveryTone = RecoveryTone.NEUTRAL


class TaskRecoveryReview(BaseModel):
    """Freshness-bound explanation required before creating a retry Task Run."""

    task_id: str
    eligible: bool
    fingerprint: str = Field(min_length=64, max_length=64)
    headline: str = Field(max_length=120)
    summary: str = Field(max_length=360)
    reason: str = Field(default="", max_length=300)
    next_attempt_no: int = Field(ge=1)
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    last_update_title: str = Field(default="", max_length=160)
    last_update_detail: str = Field(default="", max_length=500)
    computer_plan_count: int = Field(default=0, ge=0)
    action_checkpoint_count: int = Field(default=0, ge=0)
    tool_trace_count: int = Field(default=0, ge=0)
    approved_action_count: int = Field(default=0, ge=0)
    active_grant_count: int = Field(default=0, ge=0)
    requires_reauthorization: bool = False
    requires_fresh_attachment: bool = False
    possible_side_effects: bool = False
    evidence: list[RecoveryEvidence] = Field(default_factory=list)
    safeguards: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.now)
