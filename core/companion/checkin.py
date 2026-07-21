"""Storage seam for user-authored, expiring companion state."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from core.companion.models import CompanionCheckIn


class CompanionCheckInStore(Protocol):
    """Keep only the latest minimal Companion Check-in."""

    def save_check_in(self, check_in: CompanionCheckIn) -> CompanionCheckIn:
        ...

    def active_check_in(self, now: datetime) -> CompanionCheckIn | None:
        ...

    def clear_check_in(self) -> int:
        ...


class InMemoryCompanionCheckInStore:
    """Ephemeral adapter used for privacy mode and isolated runtimes."""

    def __init__(self) -> None:
        self._current: CompanionCheckIn | None = None
        self._next_id = 1

    def save_check_in(self, check_in: CompanionCheckIn) -> CompanionCheckIn:
        stored = check_in.model_copy(update={"id": self._next_id})
        self._next_id += 1
        self._current = stored
        return stored

    def active_check_in(self, now: datetime) -> CompanionCheckIn | None:
        if self._current is None:
            return None
        if not self._current.is_active(now):
            self._current = None
            return None
        return self._current

    def clear_check_in(self) -> int:
        if self._current is None:
            return 0
        self._current = None
        return 1
