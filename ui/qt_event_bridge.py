from PySide6.QtCore import QObject, Signal

from core.events.bus import EventBus
from core.events.events import (
    FocusSessionChanged,
    QueueLengthUpdated,
    SubagentCompleted,
    SubagentSpawned,
    TaskAbilityUnlocked,
    TaskCompleted,
    TaskExpGained,
    TaskLevelUp,
    TaskStarted,
)


class QtEventBridge(QObject):
    task_started = Signal(str)
    task_completed = Signal(str, str, bool, str, str)
    task_exp_gained = Signal(int, int, int, bool)
    task_level_up = Signal(int, int)
    task_ability_unlocked = Signal(str, str)
    focus_session_changed = Signal(str, int)
    queue_length_updated = Signal(int)

    _SLOT_NAMES = {
        "task_started": "on_task_started",
        "task_completed": "on_task_completed",
        "task_exp_gained": "on_pet_exp_gained",
        "task_level_up": "on_pet_level_up",
        "task_ability_unlocked": "on_ability_unlocked",
        "focus_session_changed": "on_focus_session_changed",
        "queue_length_updated": "on_queue_length_updated",
    }

    def __init__(self, bus: EventBus, parent: QObject | None = None):
        super().__init__(parent)
        self._bus = bus
        self._subscribe_all()

    def _subscribe_all(self) -> None:
        self._bus.subscribe(TaskStarted, self._on_task_started)
        self._bus.subscribe(TaskCompleted, self._on_task_completed)
        self._bus.subscribe(TaskExpGained, self._on_task_exp_gained)
        self._bus.subscribe(TaskLevelUp, self._on_task_level_up)
        self._bus.subscribe(TaskAbilityUnlocked, self._on_task_ability_unlocked)
        self._bus.subscribe(FocusSessionChanged, self._on_focus_session_changed)
        self._bus.subscribe(QueueLengthUpdated, self._on_queue_length_updated)
        self._bus.subscribe(SubagentSpawned, self._on_subagent_spawned)
        self._bus.subscribe(SubagentCompleted, self._on_subagent_completed)

    def _on_task_started(self, event: TaskStarted) -> None:
        self.task_started.emit(event.task_id)

    def _on_task_completed(self, event: TaskCompleted) -> None:
        self.task_completed.emit(
            event.task_id, event.session_id, event.success, event.summary, event.error_message
        )

    def _on_task_exp_gained(self, event: TaskExpGained) -> None:
        self.task_exp_gained.emit(event.amount, event.current_exp, event.required_exp, event.level_up)

    def _on_task_level_up(self, event: TaskLevelUp) -> None:
        self.task_level_up.emit(event.level, event.stage)

    def _on_task_ability_unlocked(self, event: TaskAbilityUnlocked) -> None:
        self.task_ability_unlocked.emit(event.ability_id, event.ability_name)

    def _on_focus_session_changed(self, event: FocusSessionChanged) -> None:
        self.focus_session_changed.emit(event.state, event.seconds_remaining)

    def _on_queue_length_updated(self, event: QueueLengthUpdated) -> None:
        self.queue_length_updated.emit(event.length)

    def _on_subagent_spawned(self, event: SubagentSpawned) -> None:
        pass

    def _on_subagent_completed(self, event: SubagentCompleted) -> None:
        pass

    def connect_to_container(self, container: object) -> None:
        for signal_name, slot_name in self._SLOT_NAMES.items():
            signal = getattr(self, signal_name, None)
            slot = getattr(container, slot_name, None)
            if signal is not None and slot is not None and callable(slot):
                signal.connect(slot)
