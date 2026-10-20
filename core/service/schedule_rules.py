"""Timezone-aware deterministic calendar scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RepeatRule(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    frequency: Literal["once", "daily", "weekly"] = "once"
    local_time: str = Field(default="", pattern=r"^$|^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    end_at: float | None = Field(default=None, gt=0)
    catch_up: bool = True

    @field_validator("weekdays")
    @classmethod
    def valid_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value) or len(set(value)) != len(value):
            raise ValueError("星期必须是互不重复的 0–6")
        return value

    @model_validator(mode="after")
    def consistent(self) -> RepeatRule:
        if (self.frequency != "once") != bool(self.local_time):
            raise ValueError("周期提醒必须指定当地时刻")
        if (self.frequency == "weekly") != bool(self.weekdays):
            raise ValueError("每周提醒必须指定星期")
        return self


def next_occurrence(rule: RepeatRule, timezone: str, after: float) -> float | None:
    """Skip DST gaps, take the first fold once, and advance by calendar dates."""
    if rule.frequency == "once":
        return None
    zone = ZoneInfo(timezone)
    date = datetime.fromtimestamp(after, zone).date()
    hour, minute = map(int, rule.local_time.split(":"))
    for offset in range(370):
        day = date + timedelta(days=offset)
        if rule.frequency == "weekly" and day.weekday() not in rule.weekdays:
            continue
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone, fold=0)
        instant = candidate.timestamp()
        roundtrip = datetime.fromtimestamp(instant, zone)
        if (roundtrip.date(), roundtrip.hour, roundtrip.minute) != (day, hour, minute):
            continue
        if instant > after:
            return instant if rule.end_at is None or instant <= rule.end_at else None
    return None
