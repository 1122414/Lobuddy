"""Pet state manager - determines pet display state based on user behavior."""

from datetime import datetime
from enum import Enum
from typing import Optional


class PetState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    WORKING = "working"
    HAPPY = "happy"
    SLEEPY = "sleepy"
    ERROR = "error"


STATE_PRIORITY = {
    PetState.ERROR: 100,
    PetState.WORKING: 90,
    PetState.THINKING: 80,
    PetState.LISTENING: 70,
    PetState.HAPPY: 60,
    PetState.SLEEPY: 50,
    PetState.IDLE: 0,
}


class PetStateManager:
    def __init__(self):
        self._current_state: PetState = PetState.IDLE
        self._previous_state: PetState = PetState.IDLE
        self._temp_state: Optional[PetState] = None
        self._temp_state_until: Optional[datetime] = None
        self._last_interaction: datetime = datetime.now()
        self._enabled: bool = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
        if not value:
            self._current_state = PetState.IDLE

    @property
    def current_state(self) -> PetState:
        if not self._enabled:
            return PetState.IDLE
        if self._temp_state and self._temp_state_until:
            if datetime.now() < self._temp_state_until:
                return self._temp_state
            self._temp_state = None
            self._temp_state_until = None
        return self._current_state

    def set_state(self, state: PetState, temporary: bool = False, duration_ms: int = 2000):
        if not self._enabled:
            return
        self._last_interaction = datetime.now()
        if temporary:
            self._temp_state = state
            self._temp_state_until = datetime.fromtimestamp(
                datetime.now().timestamp() + duration_ms / 1000.0
            )
            return
        if state == PetState.IDLE:
            self._previous_state = self._current_state
        self._current_state = MaxPriorityState(self._current_state, state)

    def on_user_typing(self):
        self.set_state(PetState.LISTENING, temporary=True, duration_ms=3000)

    def on_message_sent(self):
        self.set_state(PetState.THINKING)

    def on_task_running(self):
        self.set_state(PetState.WORKING, temporary=True, duration_ms=10000)

    def on_task_complete(self):
        self.set_state(PetState.IDLE)

    def on_task_error(self):
        self.set_state(PetState.ERROR)

    def on_pet_clicked(self):
        self.set_state(PetState.HAPPY, temporary=True, duration_ms=2500)

    def update_time_based_state(self, hour: int, idle_minutes: float,
                                 idle_threshold: int, sleepy_start: int,
                                 sleepy_end: int):
        if not self._enabled:
            return
        if hour >= sleepy_start or hour < sleepy_end:
            self._current_state = MaxPriorityState(self._current_state, PetState.SLEEPY)
        elif idle_minutes > idle_threshold and self._current_state not in (
            PetState.THINKING, PetState.WORKING, PetState.ERROR
        ):
            self._current_state = PetState.IDLE

    def get_state_text(self, state_texts: dict[str, str]) -> str:
        state = self.current_state
        return state_texts.get(state.value, "")


def MaxPriorityState(a: PetState, b: PetState) -> PetState:
    pa = STATE_PRIORITY.get(a, 0)
    pb = STATE_PRIORITY.get(b, 0)
    return b if pb > pa else a
