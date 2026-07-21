"""Domain models for a user-selected, temporary screen region."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ScreenRegionCaptureStatus(StrEnum):
    READY = "ready"
    CLAIMED = "claimed"


class ScreenRegionBounds(BaseModel):
    """Logical desktop bounds selected directly by the user."""

    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ScreenRegionDraft(BaseModel):
    """A UI-owned temporary crop waiting to enter the managed Module."""

    path: Path
    bounds: ScreenRegionBounds
    screen_name: str = Field(default="", max_length=160)


class ScreenRegionCapture(BaseModel):
    """A validated crop owned by ScreenRegionRuntime until task release."""

    id: str
    path: Path
    bounds: ScreenRegionBounds
    screen_name: str = ""
    pixel_width: int = Field(gt=0)
    pixel_height: int = Field(gt=0)
    size_bytes: int = Field(gt=0)
    captured_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    status: ScreenRegionCaptureStatus = ScreenRegionCaptureStatus.READY

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at

    @property
    def display_size(self) -> str:
        return f"{self.pixel_width} × {self.pixel_height}"
