"""Main entry point for Lobuddy application."""

import asyncio
import os
import sys
import uuid

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.bootstrap import async_bootstrap
from app.config import Settings
from core.models.chat import ChatMessage
from core.storage.chat_repo import ChatRepository
from core.storage.pet_repo import PetRepository
from core.tasks.task_manager import TaskManager


class AsyncWorker(QThread):
    """Worker thread for async tasks."""

    def __init__(self, loop):
        super().__init__()
        self.loop = loop

    def run(self):
        """Run event loop."""
        self.loop.run_forever()

    def force_stop(self):
        """Force stop the thread if graceful stop fails."""
        if self.isRunning():
            self.terminate()
            self.wait(500)


def run_ui_mode(settings: Settings):
    """Run PySide6 UI mode."""
    from ui.pet_window import PetWindow
    from ui.task_panel import TaskPanel
    from ui.task_card_panel import TaskCardPanel
    from ui.system_tray import SystemTray
    from ui.hotkey_manager import HotkeyManager
    from core.models.pet import TaskStatus
    from core.models.task_card import TaskCardModel
    from core.models.appearance import get_appearance, save_appearance

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Create event loop for async tasks
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    worker = AsyncWorker(loop)
    worker.start()

    pet_appearance = get_appearance()

    # Create components
    pet_window = PetWindow()
    pet_window.move(pet_appearance.position_x, pet_appearance.position_y)
    chat_repo = ChatRepository()
    pet_repo = PetRepository()
    task_panel = TaskPanel(chat_repo)
    task_card_panel = TaskCardPanel()
    system_tray = SystemTray()
    hotkey_manager = HotkeyManager()
    task_manager = TaskManager(settings)

    # First-run onboarding
    from core.storage.settings_repo import SettingsRepository

    settings_repo = SettingsRepository()
    first_run = settings_repo.get_setting("first_run_completed") != "true"
    if first_run:
        welcome = QMessageBox()
        welcome.setWindowTitle("Welcome to Lobuddy!")
        welcome.setText(
            "🐱 Welcome to Lobuddy - Your AI Desktop Pet!\n\n"
            "Lobuddy will stay on your desktop and help you with tasks.\n\n"
            "Quick tips:\n"
            "• Left-click: Open quick menu\n"
            "• Right-click: Context menu\n"
            "• Ctrl+Shift+L: Toggle chat panel\n"
            "• Tray icon: Exit application\n\n"
            "Your pet starts at Lv1. Complete tasks to help it grow!"
        )
        welcome.setIcon(QMessageBox.Icon.Information)
        welcome.exec()
        settings_repo.set_setting("first_run_completed", "true")

    # Load default chat history
    chat_session = chat_repo.get_or_create_session("default", "default")
        for msg in chat_session.messages:
            is_user = msg.role == "user"
            task_panel._add_message_to_display(
                msg.content, is_user=is_user, is_markdown=not is_user, image_path=msg.image_path or ""
            )

    # Connect signals
    def show_task_panel():
        task_panel.set_position_near(pet_window.x(), pet_window.y())
        task_panel.show()

    def on_task_submitted(text: str, session_id: str, image_path: str = ""):
        current_settings = task_manager.settings
        if not current_settings.llm_api_key or not current_settings.llm_api_key.strip():
            QMessageBox.warning(
                task_panel,
                "API Key Missing",
                "Please configure your LLM API Key in Settings first.",
            )
            return
        if not current_settings.llm_base_url or not current_settings.llm_base_url.strip():
            QMessageBox.warning(
                task_panel,
                "Base URL Missing",
                "Please configure your LLM Base URL in Settings first.",
            )
            return
        if not current_settings.llm_model or not current_settings.llm_model.strip():
            QMessageBox.warning(
                task_panel,
                "Model Missing",
                "Please configure your LLM Model in Settings first.",
            )
            return

        user_msg = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="user",
            content=text,
            image_path=image_path if image_path else None,
        )
        chat_repo.save_message(user_msg)

        asyncio.run_coroutine_threadsafe(
            task_manager.submit_task(text, session_id, image_path), loop
        )

    def on_task_started(task_id: str):
        pet_window.set_pet_state(TaskStatus.RUNNING)
        card = TaskCardModel(
            title="Task",
            status="running",
            task_id=task_id,
            short_result="Processing your request...",
        )
        task_card_panel.show_card(card)
        task_card_panel.show_near(pet_window.x(), pet_window.y(), pet_window.width(), pet_window.height())

    def on_task_completed(
        task_id: str, session_id: str, success: bool, summary: str, error_message: str
    ):
        nonlocal _last_exp_reward
        pet_window.set_pet_state(TaskStatus.SUCCESS if success else TaskStatus.FAILED)

        status = "success" if success else "failed"
        source = error_message if not success and error_message else summary
        short_result = source[:120] + "..." if len(source) > 120 else source

        card = TaskCardModel(
            title="Task Complete",
            status=status,
            task_id=task_id,
            short_result=short_result,
            details=summary if success else f"{summary}\n\nError: {error_message}",
            exp_reward=_last_exp_reward if success else 0,
        )
        _last_exp_reward = 0
        task_card_panel.show_card(card)
        task_card_panel.show_near(pet_window.x(), pet_window.y(), pet_window.width(), pet_window.height())

        display_content = summary
        if not success and error_message:
            display_content = f"{summary}\n\n错误详情: {error_message}"

        assistant_msg = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="assistant",
            content=display_content,
        )
        chat_repo.save_message(assistant_msg)

        short_chat_msg = short_result
        if session_id == task_panel.current_session_id:
            task_panel.add_pet_response(short_chat_msg, session_id)

    _last_exp_reward = 0

    def on_pet_exp_gained(amount: int, current_exp: int, required_exp: int, level_up: bool):
        nonlocal _last_exp_reward
        _last_exp_reward = amount
        pet = pet_repo.get_or_create_pet()
        pet_window.update_exp_display(current_exp, required_exp, pet.level)
        pet_window.show_exp_gained(amount)

    def on_pet_level_up(level: int, stage: int):
        print(f"🎉 Pet leveled up to Lv{level} (Stage {stage})!")
        pet = pet_repo.get_or_create_pet()
        pet_window.update_exp_display(0, pet.get_exp_for_next_level(), level)

    def on_ability_unlocked(ability_id: str, ability_name: str):
        print(f"🔓 Ability unlocked: {ability_name}!")
        # Could show a notification dialog here

    pet_window.chat_requested.connect(show_task_panel)
    task_panel.task_submitted.connect(on_task_submitted)

    def on_history_requested():
        from ui.history_window import HistoryWindow

        history_window = HistoryWindow(chat_repo, task_panel)

        def on_session_selected(session_id: str):
            task_panel._load_session_messages(session_id)

        history_window.session_selected.connect(on_session_selected)
        history_window.exec()

    def on_settings_requested():
        from ui.settings_window import SettingsWindow

        settings_window = SettingsWindow(settings)

        def on_settings_saved(updated_settings: Settings):
            nonlocal settings
            settings = updated_settings
            task_manager.settings = updated_settings
            task_manager.adapter.settings = updated_settings

        settings_window.settings_saved.connect(on_settings_saved)
        settings_window.exec()

    task_panel.history_requested.connect(on_history_requested)
    task_panel.settings_requested.connect(on_settings_requested)

    def on_task_continue(task_id: str):
        show_task_panel()

    def _show_placeholder(title: str, feature: str):
        QMessageBox.information(task_card_panel, title, f"{feature} feature coming soon!")

    task_card_panel.continue_clicked.connect(on_task_continue)
    task_card_panel.screenshot_clicked.connect(lambda _: _show_placeholder("Screenshot", "Screenshot"))
    task_card_panel.open_web_clicked.connect(lambda _: _show_placeholder("Open Web", "Open web"))

    task_manager.task_started.connect(on_task_started)
    task_manager.task_completed.connect(on_task_completed)
    task_manager.pet_exp_gained.connect(on_pet_exp_gained)
    task_manager.pet_level_up.connect(on_pet_level_up)
    task_manager.ability_unlocked.connect(on_ability_unlocked)

    def on_exit_requested():
        import threading

        if getattr(on_exit_requested, "_armed", False):
            return
        on_exit_requested._armed = True

        pet_appearance.position_x = pet_window.x()
        pet_appearance.position_y = pet_window.y()
        save_appearance(pet_appearance)

        killer = threading.Timer(4.0, lambda: os._exit(0))
        killer.daemon = True
        killer.start()

        system_tray.hide()
        pet_window.force_close()
        task_panel.close()
        task_card_panel.close()
        app.exit(0)

    system_tray.show_requested.connect(pet_window.show)
    system_tray.exit_requested.connect(on_exit_requested)

    def on_pet_settings_requested():
        from ui.pet_settings_panel import PetSettingsPanel
        dialog = PetSettingsPanel(pet_appearance, pet_window)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            pet_window.reload_appearance()
            pet_window.set_pet_state(TaskStatus.IDLE)

    def on_about_requested():
        print("About requested (not yet implemented)")

    def on_close_requested():
        on_exit_requested()

    pet_window.settings_requested.connect(on_settings_requested)
    pet_window.pet_settings_requested.connect(on_pet_settings_requested)
    pet_window.close_requested.connect(on_close_requested)
    system_tray.settings_requested.connect(on_settings_requested)
    system_tray.about_requested.connect(on_about_requested)

    hotkey_manager.activated.connect(show_task_panel)

    # Initial state
    pet_window.set_pet_state(TaskStatus.IDLE)

    # Initialize EXP display
    pet = pet_repo.get_or_create_pet()
    pet_window.update_exp_display(pet.exp, pet.get_exp_for_next_level(), pet.level)

    # Show components
    pet_window.show()
    system_tray.show()
    hotkey_manager.start()

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        @PHANDLER_ROUTINE
        def _console_ctrl_handler(ctrl_type):
            if ctrl_type in (2, 5, 6):
                app.quit()
                return True
            return False

        kernel32.SetConsoleCtrlHandler(_console_ctrl_handler, True)

    # Run
    try:
        exit_code = app.exec()
    finally:
        # Cleanup
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                task_manager.queue.stop(), loop
            )
            try:
                future.result(timeout=2)
            except Exception:
                pass
        hotkey_stopped = hotkey_manager.stop()
        for task in asyncio.all_tasks(loop):
            task.cancel()
        loop.call_soon_threadsafe(loop.stop)
        worker_stopped = worker.wait(3000)
        if not worker_stopped:
            worker.force_stop()
            worker_stopped = not worker.isRunning()
        if not worker_stopped or not hotkey_stopped:
            print("[CRITICAL] Shutdown incomplete; forcing process exit")
            os._exit(0)

    sys.exit(exit_code)


def main():
    """Main entry point."""
    try:
        settings, _ = asyncio.run(async_bootstrap())
        run_ui_mode(settings)
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
