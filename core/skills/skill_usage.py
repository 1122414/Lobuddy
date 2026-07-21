"""Skill usage tracking interfaces for Lobuddy 5.8 (P2-D4).

This module defines the event types and sink interface for skill usage feedback.
Actual usage tracking is intentionally NOT implemented yet — we wait for nanobot
to expose reliable per-skill execution hooks.

Current status: skills are prompt-visible, not usage-accounted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class SkillUsageEventType(Enum):
    """Types of skill usage events."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class SkillUsageEvent:
    """An event representing skill usage at a point in time.

    Immutable — once created, the event does not change.
    """

    skill_id: str
    event_type: SkillUsageEventType
    timestamp: datetime = field(default_factory=datetime.now)
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class SkillUsageSink:
    """Interface for consuming skill usage events.

    Implementations may write to SQLite, log files, or external telemetry.
    """

    def record(self, event: SkillUsageEvent) -> None:
        raise NotImplementedError

    def get_events(
        self,
        skill_id: Optional[str] = None,
        event_type: Optional[SkillUsageEventType] = None,
        limit: int = 100,
    ) -> list[SkillUsageEvent]:
        raise NotImplementedError


class NoOpSkillUsageSink(SkillUsageSink):
    """Default no-op sink until real tracking is wired."""

    def record(self, event: SkillUsageEvent) -> None:
        pass

    def get_events(
        self,
        skill_id: Optional[str] = None,
        event_type: Optional[SkillUsageEventType] = None,
        limit: int = 100,
    ) -> list[SkillUsageEvent]:
        return []


class NanobotSkillHookAdapter:
    """Adapter to wire nanobot execution hooks to SkillUsageSink.

    This is a placeholder (P2-D4) — nanobot does not yet expose reliable
    per-skill execution events. When that becomes available, implement:

        def on_skill_started(self, skill_name: str, session_id: str): ...
        def on_skill_completed(self, skill_name: str, session_id: str): ...
        def on_skill_failed(self, skill_name: str, session_id: str, error: str): ...

    Do NOT infer usage from:
    - Prompt text containing skill names
    - Overall task success/failure
    - Natural language output parsing
    """

    def __init__(self, sink: SkillUsageSink | None = None) -> None:
        self._sink = sink or NoOpSkillUsageSink()

    def emit(self, event: SkillUsageEvent) -> None:
        self._sink.record(event)
