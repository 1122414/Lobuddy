"""Focus companion mode - reserved interface for future Pomodoro feature.

Current phase: stub only. Do NOT implement complex task planning,
system notifications, calendar integration, or statistics.
"""

from dataclasses import dataclass


@dataclass
class FocusSession:
    focus_minutes: int = 25
    break_minutes: int = 5
    is_running: bool = False


class FocusCompanion:
    def __init__(self):
        self._sessions: list[FocusSession] = []

    def start_focus(self, minutes: int = 25, break_minutes: int = 5) -> FocusSession:
        session = FocusSession(focus_minutes=minutes, break_minutes=break_minutes, is_running=True)
        self._sessions.append(session)
        return session

    def stop_current(self):
        if self._sessions:
            self._sessions[-1].is_running = False

    def get_current_session(self):
        return self._sessions[-1] if self._sessions else None
