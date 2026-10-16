"""Focus companion - Pomodoro timer with pet state integration."""

import logging
from datetime import datetime, timedelta
from enum import Enum

from core.config import Settings
from core.events.hook import EventHook

logger = logging.getLogger(__name__)


class FocusState(str, Enum):
    """Focus session states."""

    IDLE = "idle"
    FOCUSING = "focusing"
    PAUSED = "paused"
    BREAK = "break"
    COMPLETED = "completed"
    STOPPED = "stopped"


class FocusSession:
    """A single focus session with timer."""

    def __init__(
        self,
        focus_minutes: int = 25,
        break_minutes: int = 5,
    ):
        self.state_changed: EventHook[[FocusState]] = EventHook()
        self.tick: EventHook[[int]] = EventHook()
        self.completed: EventHook[[]] = EventHook()
        self._focus_minutes = focus_minutes
        self._break_minutes = break_minutes
        self._state = FocusState.IDLE
        self._started_at: datetime | None = None
        self._ends_at: datetime | None = None
        self._paused_remaining: int = 0

    @property
    def state(self) -> FocusState:
        return self._state

    @property
    def seconds_remaining(self) -> int:
        if self._state == FocusState.PAUSED:
            return self._paused_remaining
        if self._ends_at is None:
            return 0
        remaining = (self._ends_at - datetime.now()).total_seconds()
        return max(0, int(remaining))

    @property
    def focus_minutes(self) -> int:
        return self._focus_minutes

    @property
    def break_minutes(self) -> int:
        return self._break_minutes

    def start_focus(self) -> None:
        if self._state == FocusState.FOCUSING:
            return

        self._state = FocusState.FOCUSING
        self._started_at = datetime.now()
        self._ends_at = self._started_at + timedelta(minutes=self._focus_minutes)
        self.state_changed.emit(self._state)
        logger.info(f"Focus started: {self._focus_minutes} minutes")

    def pause(self) -> None:
        if self._state != FocusState.FOCUSING:
            return

        self._paused_remaining = self.seconds_remaining
        self._state = FocusState.PAUSED
        self.state_changed.emit(self._state)
        logger.info(f"Focus paused: {self._paused_remaining}s remaining")

    def resume(self) -> None:
        if self._state != FocusState.PAUSED:
            return

        self._state = FocusState.FOCUSING
        self._ends_at = datetime.now() + timedelta(seconds=self._paused_remaining)
        self.state_changed.emit(self._state)
        logger.info(f"Focus resumed: {self._paused_remaining}s remaining")

    def start_break(self) -> None:
        if self._state != FocusState.COMPLETED:
            return

        self._state = FocusState.BREAK
        self._ends_at = datetime.now() + timedelta(minutes=self._break_minutes)
        self.state_changed.emit(self._state)
        logger.info(f"Break started: {self._break_minutes} minutes")

    def stop(self) -> None:
        self._state = FocusState.STOPPED
        self._ends_at = None
        self.state_changed.emit(self._state)
        logger.info("Focus stopped")

    def reset(self) -> None:
        self._state = FocusState.IDLE
        self._started_at = None
        self._ends_at = None
        self.state_changed.emit(self._state)

    def _on_tick(self) -> None:
        if self._state not in (FocusState.FOCUSING, FocusState.BREAK):
            return
        remaining = self.seconds_remaining
        self.tick.emit(remaining)

        if remaining <= 0:
            if self._state == FocusState.FOCUSING:
                self._state = FocusState.COMPLETED
                self.completed.emit()
                logger.info("Focus completed")
            elif self._state == FocusState.BREAK:
                self._state = FocusState.IDLE
                logger.info("Break completed")
            self.state_changed.emit(self._state)


class FocusCompanion:
    """Focus companion manager."""

    def __init__(self, settings: Settings) -> None:
        self.session_changed: EventHook[[FocusSession | None]] = EventHook()
        self._settings = settings
        self._current_session: FocusSession | None = None

    @property
    def is_active(self) -> bool:
        return self._current_session is not None and self._current_session.state in (
            FocusState.FOCUSING,
            FocusState.BREAK,
            FocusState.PAUSED,
        )

    @property
    def is_paused(self) -> bool:
        return (
            self._current_session is not None and self._current_session.state == FocusState.PAUSED
        )

    @property
    def current_session(self) -> FocusSession | None:
        return self._current_session

    def start_focus(self, minutes: int | None = None) -> FocusSession:
        if self._current_session and self._current_session.state in (
            FocusState.FOCUSING,
            FocusState.BREAK,
        ):
            self._current_session.stop()

        focus_min = minutes or self._settings.focus_default_minutes
        break_min = self._settings.focus_break_minutes

        self._current_session = FocusSession(
            focus_minutes=focus_min,
            break_minutes=break_min,
        )
        self._current_session.completed.connect(self._on_focus_completed)
        self._current_session.start_focus()
        self.session_changed.emit(self._current_session)
        return self._current_session

    def pause(self) -> None:
        if self._current_session and self._current_session.state == FocusState.FOCUSING:
            self._current_session.pause()

    def resume(self) -> None:
        if self._current_session and self._current_session.state == FocusState.PAUSED:
            self._current_session.resume()

    def stop(self) -> None:
        if self._current_session:
            self._current_session.stop()
            self._current_session = None
            self.session_changed.emit(None)

    def poll(self) -> None:
        """Advance from a host-owned timer (Qt or asyncio)."""
        if self._current_session is not None:
            self._current_session._on_tick()

    def _on_focus_completed(self) -> None:
        if self._settings.focus_auto_loop and self._current_session is not None:
            self._current_session.start_break()
        else:
            self._current_session = None
            self.session_changed.emit(None)
