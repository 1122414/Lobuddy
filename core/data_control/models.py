"""Domain models for the user-visible Data Control projection."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DataControlTone(StrEnum):
    """Small semantic vocabulary shared by domain and UI."""

    PROTECTED = "protected"
    ACTIVE = "active"
    ATTENTION = "attention"
    INACTIVE = "inactive"


class DataControlAction(StrEnum):
    """Explicit revocations supported by the Data Control Interface."""

    ENABLE_SESSION_PRIVACY = "enable_session_privacy"
    DISABLE_SESSION_PRIVACY = "disable_session_privacy"
    REVOKE_COMPUTER_USE = "revoke_computer_use"
    CLEAR_SCREEN_REGIONS = "clear_screen_regions"
    CLEAR_COMPANION_CHECKIN = "clear_companion_checkin"
    CLEAR_SESSION_CHAT = "clear_session_chat"


class DataControlFact(BaseModel):
    label: str = Field(max_length=20)
    value: str = Field(max_length=160)


class DataControlCard(BaseModel):
    """Content-minimized explanation of one governed data surface."""

    key: str = Field(min_length=1, max_length=40)
    group: str = Field(max_length=20)
    title: str = Field(max_length=40)
    state_label: str = Field(max_length=40)
    summary: str = Field(max_length=240)
    tone: DataControlTone
    facts: list[DataControlFact] = Field(default_factory=list, max_length=5)
    action: DataControlAction | None = None
    action_label: str = Field(default="", max_length=40)
    requires_confirmation: bool = False
    secondary_route: str = Field(default="", max_length=40)
    secondary_label: str = Field(default="", max_length=40)


class DataControlSnapshot(BaseModel):
    """Current-session projection; contains counts and policy, never private content."""

    session_id: str = Field(min_length=1, max_length=160)
    privacy_active: bool
    headline: str = Field(max_length=100)
    detail: str = Field(max_length=260)
    cards: list[DataControlCard] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class DataControlResult(BaseModel):
    action: DataControlAction
    changed_count: int = Field(default=0, ge=0)
    message: str = Field(max_length=200)
    snapshot: DataControlSnapshot
