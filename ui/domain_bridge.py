"""Keep Qt thread dispatch and timers out of domain services."""

from PySide6.QtCore import QObject, QTimer, Signal

from core.focus.focus_companion import FocusCompanion
from core.models.pet import TaskStatus
from core.tasks.task_manager import TaskManager


class QtTaskEvents(QObject):
    task_started = Signal(str)
    task_completed = Signal(str, str, bool, str, str)
    pet_state_changed = Signal(TaskStatus)
    pet_exp_gained = Signal(int, int, int, bool)
    pet_level_up = Signal(int, int)
    pet_personality_changed = Signal(dict)
    ability_unlocked = Signal(str, str)

    def __init__(self, manager: TaskManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        for name in (
            "task_started",
            "task_completed",
            "pet_state_changed",
            "pet_exp_gained",
            "pet_level_up",
            "pet_personality_changed",
            "ability_unlocked",
        ):
            getattr(manager, name).connect(getattr(self, name).emit)


class QtFocusDriver(QObject):
    def __init__(self, companion: FocusCompanion, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(companion.poll)
        self._timer.start()
