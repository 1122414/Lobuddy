"""Local calendar rules and notification delivery, without executable cron strings."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field

from core.service.delegation_protocol import DelegationModel, DelegationReference
from core.service.jev_protocol import JevDecision
from core.service.schedule_rules import RepeatRule


class ScheduleResolve(DelegationModel):
    local: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$")
    timezone: str = Field(min_length=1, max_length=128)

    def instant(self) -> float:
        try:
            zone = ZoneInfo(self.timezone)
            wall = datetime.fromisoformat(self.local)
            instant = wall.replace(tzinfo=zone, fold=0).timestamp()
            if datetime.fromtimestamp(instant, zone).replace(tzinfo=None) != wall:
                raise ValueError("该当地时刻不存在，请重新选择时间")
            return instant
        except (ZoneInfoNotFoundError, OverflowError, OSError) as error:
            raise ValueError("日期或时区无效") from error


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
    decision: JevDecision | None = None


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
