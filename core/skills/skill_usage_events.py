"""Skill usage event interfaces for future nanobot execution hook integration (P2-D4).

These interfaces are intentionally left as stubs/TODOs until nanobot exposes
reliable per-skill execution events. Current skills are prompt-visible only;
usage accounting must not be inferred from prompt content or task success.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Protocol


class SkillExecutionStatus(str, Enum):
    """Status of a skill execution attempt."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class SkillUsageEvent:
    """Event representing a single skill execution attempt.

    This will be populated by nanobot execution hooks when available.
    Do NOT synthesize these events from prompt analysis or task results.
    """

    skill_id: str
    skill_name: str
    status: SkillExecutionStatus
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: dict[str, str] = field(default_factory=dict)


class SkillUsageSink(Protocol):
    """Protocol for receiving skill usage events.

    Implementations will record events to analytics, database, or external systems.
    """

    def record(self, event: SkillUsageEvent) -> None:
        """Record a skill usage event."""
        ...


class NanobotSkillHookAdapter:
    """Adapter placeholder for nanobot skill execution hooks.

    TODO(5.8.x): Wire into nanobot_adapter.py when nanobot exposes:
        - skill_execution_started(skill_id)
        - skill_execution_completed(skill_id, result)
        - skill_execution_failed(skill_id, error)

    Current behavior: no-op (skills are prompt-visible, not usage-accounted).
    """

    def __init__(self, sink: Optional[SkillUsageSink] = None) -> None:
        self._sink = sink

    def on_execution_started(self, skill_id: str, skill_name: str, session_id: Optional[str] = None) -> None:
        """Hook called when a skill execution starts.

        TODO: Called by nanobot when it begins executing a skill.
        Currently a no-op stub.
        """
        if self._sink is not None:
            event = SkillUsageEvent(
                skill_id=skill_id,
                skill_name=skill_name,
                status=SkillExecutionStatus.STARTED,
                session_id=session_id,
            )
            self._sink.record(event)

    def on_execution_completed(self, skill_id: str, skill_name: str, session_id: Optional[str] = None) -> None:
        """Hook called when a skill execution completes successfully.

        TODO: Called by nanobot when a skill finishes successfully.
        Currently a no-op stub.
        """
        if self._sink is not None:
            event = SkillUsageEvent(
                skill_id=skill_id,
                skill_name=skill_name,
                status=SkillExecutionStatus.COMPLETED,
                session_id=session_id,
                finished_at=datetime.now(),
            )
            self._sink.record(event)

    def on_execution_failed(
        self,
        skill_id: str,
        skill_name: str,
        error_message: str,
        session_id: Optional[str] = None,
    ) -> None:
        """Hook called when a skill execution fails.

        TODO: Called by nanobot when a skill execution fails.
        Currently a no-op stub.
        """
        if self._sink is not None:
            event = SkillUsageEvent(
                skill_id=skill_id,
                skill_name=skill_name,
                status=SkillExecutionStatus.FAILED,
                session_id=session_id,
                finished_at=datetime.now(),
                error_message=error_message,
            )
            self._sink.record(event)
