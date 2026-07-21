"""Application container — composition root holding all component instances."""

import asyncio
import sys

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication

from app.config import Settings
from app.service_wiring import Services, apply_theme_from_settings, create_services
from core.models.appearance import get_appearance
from core.pet_state_manager import PetStateManager
from core.storage.chat_repo import ChatRepository
from core.storage.pet_repo import PetRepository
from core.storage.settings_repo import SettingsRepository
from core.tasks.task_manager import TaskManager
from ui.theme import ThemeManager


class AsyncWorker(QThread):
    """Worker thread for async tasks."""

    def __init__(self, loop):
        super().__init__()
        self.loop = loop

    def run(self):
        self.loop.run_forever()

    def force_stop(self):
        if self.isRunning():
            self.terminate()
            self.wait(500)


class AppContainer:
    """Composition root holding all UI components and backend services."""

    def __init__(self, settings: Settings):
        self.settings = settings

        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setStyleSheet(
            "QToolTip { background: #FFF8EF; color: #4A2E1F; "
            "border: 1px solid #F1D9C0; border-radius: 8px; padding: 6px 10px; "
            "font-size: 11px; }"
        )

        self.theme_mgr = ThemeManager.instance()
        apply_theme_from_settings(self.theme_mgr, settings)

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.worker = AsyncWorker(self.loop)
        self.worker.start()

        from ui.pet_window import PetWindow
        from ui.task_panel import TaskPanel
        from ui.task_card_panel import TaskCardPanel
        from ui.system_tray import SystemTray
        from ui.hotkey_manager import HotkeyManager

        self.pet_appearance = get_appearance()

        self.pet_window = PetWindow()
        self.pet_window.move(self.pet_appearance.position_x, self.pet_appearance.position_y)
        if settings.pet_avatar_animation_enabled:
            self.pet_window.start_breathing()
        self.pet_window.set_mood_enabled(settings.companion_greeting_enabled)

        self.chat_repo = ChatRepository()
        self.pet_repo = PetRepository()
        pet = self.pet_repo.get_or_create_pet()
        self.pet_window.set_pet_name(pet.name)
        self.pet_window.set_settings(settings)

        self.task_panel = TaskPanel(self.chat_repo)
        self.task_panel.set_settings(settings)
        self.task_panel.resize(
            self.pet_appearance.task_panel_width, self.pet_appearance.task_panel_height
        )

        self.state_mgr = PetStateManager()
        self.state_mgr.enabled = settings.pet_state_enabled
        self.pet_window._state_mgr = self.state_mgr

        self.task_card_panel = TaskCardPanel()
        self.system_tray = SystemTray()
        self.hotkey_manager = HotkeyManager()
        self.task_manager = TaskManager(settings)

        self.services: Services = create_services(
            settings,
            self.task_manager,
            chat_repo=self.chat_repo,
        )

        self.settings_repo = SettingsRepository()

        self.idle_timer = QTimer()
        self.idle_timer.setInterval(30000)
