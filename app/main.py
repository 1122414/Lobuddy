"""Main entry point for Lobuddy application."""

import asyncio
import sys
import uuid

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

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


def run_ui_mode(settings: Settings):
    """Run PySide6 UI mode."""
    from ui.pet_window import PetWindow
    from ui.task_panel import TaskPanel
    from ui.system_tray import SystemTray
    from ui.hotkey_manager import HotkeyManager
    from core.models.pet import TaskStatus

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Create event loop for async tasks
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    worker = AsyncWorker(loop)
    worker.start()

    # Create components
    pet_window = PetWindow()
    chat_repo = ChatRepository()
    pet_repo = PetRepository()
    task_panel = TaskPanel(chat_repo)
    system_tray = SystemTray()
    hotkey_manager = HotkeyManager()
    task_manager = TaskManager(settings)

    # Load default chat history
    chat_session = chat_repo.get_or_create_session("default", "default")
    for msg in chat_session.messages:
        is_user = msg.role == "user"
        task_panel._add_message_to_display(
            msg.content, is_user=is_user, is_markdown=not is_user, image_path=msg.image_path
        )

    # Connect signals
    def show_task_panel():
        task_panel.set_position_near(pet_window.x(), pet_window.y())
        task_panel.show()

    def on_task_submitted(text: str, session_id: str, image_path: str = ""):
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

    def on_task_completed(
        task_id: str, session_id: str, success: bool, summary: str, error_message: str
    ):
        pet_window.set_pet_state(TaskStatus.IDLE)

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

        if session_id == task_panel.current_session_id:
            task_panel.add_pet_response(display_content, session_id)

    def on_pet_exp_gained(amount: int, current_exp: int, required_exp: int, level_up: bool):
        # Get current pet level for display
        pet = pet_repo.get_or_create_pet()
        pet_window.update_exp_display(current_exp, required_exp, pet.level)

    def on_pet_level_up(level: int, stage: int):
        print(f"🎉 Pet leveled up to Lv{level} (Stage {stage})!")
        pet_window.update_exp_display(0, pet.get_exp_for_next_level(), level)

    def on_ability_unlocked(ability_id: str, ability_name: str):
        print(f"🔓 Ability unlocked: {ability_name}!")
        # Could show a notification dialog here

    pet_window.task_requested.connect(show_task_panel)
    task_panel.task_submitted.connect(on_task_submitted)

    task_manager.task_started.connect(on_task_started)
    task_manager.task_completed.connect(on_task_completed)
    task_manager.pet_exp_gained.connect(on_pet_exp_gained)
    task_manager.pet_level_up.connect(on_pet_level_up)
    task_manager.ability_unlocked.connect(on_ability_unlocked)

    system_tray.show_requested.connect(pet_window.show)
    system_tray.exit_requested.connect(app.quit)

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

    # Run
    try:
        exit_code = app.exec()
    finally:
        # Cleanup
        hotkey_manager.stop()
        loop.call_soon_threadsafe(loop.stop)
        worker.wait(1000)

    sys.exit(exit_code)


def main():
    """Main entry point."""
    try:
        settings, health = asyncio.run(async_bootstrap())
        run_ui_mode(settings)
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
