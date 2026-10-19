"""Local calendar rules and notification delivery, without executable cron strings."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from core.service.delegation_protocol import DelegationModel, DelegationReference
from core.service.schedule_rules import RepeatRule


class NotificationReference(DelegationModel):
    notification_id: str = Field(min_length=1, max_length=128)


class NotificationBatchReference(DelegationModel):
    batch_id: str = Field(min_length=1, max_length=128)


class NotificationView(DelegationModel):
    id: str
    reason: Literal["reminder", "task_result", "companionship"]
    source_id: str
    delegation_id: str = ""
    text: str
    planned_at: float
    created_at: float
    delivered_at: float | None = None
    read_at: float | None = None
    status: Literal["pending", "leased", "delivered", "read", "missed", "cancelled"] = "pending"
    batch_id: str = ""
    lease_until: float = 0


class NotificationBatch(DelegationModel):
    batch_id: str
    text: str
    count: int
    expires_at: float


class ScheduleView(DelegationModel):
    delegation_id: str
    next_at: float | None
    timezone: str
    repeat: RepeatRule
    state: str
    reason: str


class RecoveryRequest(DelegationReference):
    revision: int = Field(ge=1)
    action: Literal["inspect", "resume_readonly"] = "inspect"


class RuntimePower(DelegationModel):
    suspended: bool
