"""Main entry point for Lobuddy application."""

import asyncio
import os
import sys
import uuid
from datetime import datetime

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.bootstrap import async_bootstrap
from app.config import Settings
from core.models.chat import ChatMessage
from core.storage.chat_repo import ChatRepository
from core.storage.pet_repo import PetRepository
from core.tasks.task_manager import TaskManager
from ui.theme import ThemePreset
from core.pet_state_manager import PetStateManager
from core.time_format import get_greeting_for_hour


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


def _apply_theme_from_settings(theme_mgr, settings):
    """Apply theme from settings to ThemeManager singleton."""
    preset_map = {
        "cozy_orange": ThemePreset.COZY_ORANGE,
        "sakura_pink": ThemePreset.SAKURA_PINK,
        "mint_green": ThemePreset.MINT_GREEN,
        "night_companion": ThemePreset.NIGHT_COMPANION,
    }
    preset = preset_map.get(settings.theme_preset, ThemePreset.COZY_ORANGE)

    custom_overrides = {}
    if settings.theme_primary_color:
        custom_overrides["primary"] = settings.theme_primary_color
    if settings.theme_background_color:
        custom_overrides["background"] = settings.theme_background_color
    if settings.theme_accent_color:
        custom_overrides["border_focus"] = settings.theme_accent_color

    if custom_overrides:
        theme_mgr.apply_theme(preset, custom_overrides)
    else:
        theme_mgr.set_preset(preset)


def run_ui_mode(settings: Settings):
    """Run PySide6 UI mode."""
    from ui.pet_window import PetWindow
    from ui.task_panel import TaskPanel
    from ui.task_card_panel import TaskCardPanel
    from ui.system_tray import SystemTray
    from ui.hotkey_manager import HotkeyManager
    from ui.theme import ThemeManager
    from core.models.pet import TaskStatus
    from core.models.task_card import TaskCardModel
    from core.models.appearance import get_appearance, save_appearance

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet("QToolTip { background: #FFF8EF; color: #4A2E1F; border: 1px solid #F1D9C0; border-radius: 8px; padding: 6px 10px; font-size: 11px; }")

    theme_mgr = ThemeManager.instance()
    _apply_theme_from_settings(theme_mgr, settings)

    # Create event loop for async tasks
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    worker = AsyncWorker(loop)
    worker.start()

    pet_appearance = get_appearance()

    # Create components
    pet_window = PetWindow()
    pet_window.move(pet_appearance.position_x, pet_appearance.position_y)
    if settings.pet_avatar_animation_enabled:
        pet_window.start_breathing()
    pet_window.set_mood_enabled(settings.companion_greeting_enabled)
    chat_repo = ChatRepository()
    pet_repo = PetRepository()
    pet = pet_repo.get_or_create_pet()
    pet_window.set_pet_name(pet.name)
    pet_window.set_settings(settings)
    task_panel = TaskPanel(chat_repo)
    task_panel.set_settings(settings)
    task_panel.resize(pet_appearance.task_panel_width, pet_appearance.task_panel_height)

    state_mgr = PetStateManager()
    state_mgr.enabled = settings.pet_state_enabled
    pet_window._state_mgr = state_mgr
    state_texts = {
        "idle": settings.pet_state_text_idle,
        "listening": settings.pet_state_text_listening,
        "thinking": settings.pet_state_text_thinking,
        "working": settings.pet_state_text_working,
        "happy": settings.pet_state_text_happy,
        "sleepy": settings.pet_state_text_sleepy,
        "error": settings.pet_state_text_error,
    }

    def _update_state_display():
        text = state_mgr.get_state_text(state_texts)
        if text and state_mgr.enabled:
            pet_window.set_pet_state_override(text)

    def _on_task_panel_input_change():
        if task_panel.input_box.text():
            state_mgr.on_user_typing()
    _update_state_display()

    idle_timer = QTimer()
    idle_timer.setInterval(30000)

    def _on_idle_timer():
        now = datetime.now()
        state_mgr.update_time_based_state(
            now.hour, 0,
            settings.pet_idle_after_minutes,
            settings.pet_sleepy_start_hour,
            settings.pet_sleepy_end_hour,
        )
        _update_state_display()

    idle_timer.timeout.connect(_on_idle_timer)
    idle_timer.start()

    task_panel.input_box.textChanged.connect(_on_task_panel_input_change)
    task_card_panel = TaskCardPanel()
    system_tray = SystemTray()
    hotkey_manager = HotkeyManager()
    task_manager = TaskManager(settings)
    from core.memory.user_profile_service import UserProfileService
    from core.memory.memory_service import MemoryService
    from core.memory.memory_maintenance import MemoryMaintenance
    from core.skills.skill_maintenance import SkillMaintenance
    from core.focus.focus_companion import FocusCompanion, FocusState

    profile_service = UserProfileService(settings)
    task_manager.adapter.set_profile_service(profile_service)
    memory_service = MemoryService(settings)
    task_manager.adapter.set_memory_service(memory_service)

    memory_maintenance = MemoryMaintenance(settings)
    skill_maintenance = SkillMaintenance(settings)

    maintenance_timer = QTimer()
    maintenance_timer.setInterval(settings.skill_maintenance_interval_hours * 3600 * 1000)

    def _run_maintenance():
        try:
            mem_report = memory_maintenance.run_maintenance()
            skill_report = skill_maintenance.run_maintenance()
            print(f"[Maintenance] Memory: {mem_report}, Skills: {skill_report}")
        except Exception as e:
            print(f"[Maintenance] Error: {e}")

    maintenance_timer.timeout.connect(_run_maintenance)
    maintenance_timer.start()
    QTimer.singleShot(30000, _run_maintenance)

    focus_companion = FocusCompanion(settings)

    def _connect_focus_session(session):
        if session:
            session.tick.connect(pet_window.update_focus_timer)
            session.state_changed.connect(lambda state: _on_focus_state_changed(state))

    def on_focus_button_clicked():
        if not focus_companion.is_active:
            session = focus_companion.start_focus()
            _connect_focus_session(session)
            pet_window.set_focus_active(True)
            pet_window.update_focus_button_state("focusing")
            pet_window.set_pet_state_override(settings.focus_status_text)
        elif focus_companion.is_paused:
            focus_companion.resume()
            pet_window.update_focus_button_state("focusing")
        else:
            focus_companion.pause()
            pet_window.update_focus_button_state("paused")

    def on_focus_stop():
        focus_companion.stop()
        pet_window.clear_focus_timer()
        pet_window.set_focus_active(False)
        pet_window.clear_pet_state_override()

    def _on_focus_state_changed(state: FocusState):
        if state == FocusState.COMPLETED:
            if settings.focus_auto_loop:
                session = focus_companion.current_session
                if session:
                    session.start_break()
            else:
                pet_window.clear_focus_timer()
                pet_window.set_focus_active(False)
                pet_window.update_focus_button_state("idle")
                pet_window.clear_pet_state_override()
        elif state == FocusState.IDLE:
            pet_window.clear_focus_timer()
            pet_window.set_focus_active(False)
            pet_window.update_focus_button_state("idle")
            pet_window.clear_pet_state_override()
        elif state == FocusState.PAUSED:
            pet_window.update_focus_button_state("paused")
            pet_window.update_focus_timer(focus_companion.current_session.seconds_remaining)
        elif state == FocusState.FOCUSING:
            pet_window.update_focus_button_state("focusing")

    pet_window.focus_requested.connect(on_focus_button_clicked)
    pet_window.focus_stop_requested.connect(on_focus_stop)

    theme_mgr.theme_changed.connect(pet_window.refresh_theme)
    theme_mgr.theme_changed.connect(task_panel.refresh_theme)

    pet_window.refresh_theme()
    task_panel.refresh_theme()

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

    chat_session = chat_repo.get_or_create_session("default", "default")
    for msg in chat_session.messages:
        is_user = msg.role == "user"
        task_panel._add_message_to_display(
            msg.content, is_user=is_user, is_markdown=not is_user,
            image_path=msg.image_path or "", created_at=msg.created_at, msg_id=msg.id
        )
    QTimer.singleShot(200, task_panel._scroll_bottom)

    if settings.daily_greeting_enabled and settings_repo.get_setting("daily_greeting_today") != datetime.now().strftime("%Y%m%d"):
        hour = datetime.now().hour
        greeting_key = get_greeting_for_hour(hour)
        greeting_map = {
            "morning": settings.greeting_morning,
            "afternoon": settings.greeting_afternoon,
            "evening": settings.greeting_evening,
            "night": settings.greeting_night,
        }
        msg = greeting_map.get(greeting_key, "")
        if msg:
            pet_window.show_speech_bubble(msg, 4000)
        settings_repo.set_setting("daily_greeting_today", datetime.now().strftime("%Y%m%d"))

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
        state_mgr.on_message_sent()
        _update_state_display()

    def on_task_started(task_id: str):
        pet_window.set_pet_state(TaskStatus.RUNNING)
        state_mgr.on_task_running()
        _update_state_display()
        card = TaskCardModel(
            title="任务进行中",
            status="running",
            task_id=task_id,
            short_result="正在处理你的请求...",
        )
        task_card_panel.show_card(card)
        task_card_panel.show_at_corner()

    def on_task_completed(
        task_id: str, session_id: str, success: bool, summary: str, error_message: str
    ):
        nonlocal _last_exp_reward
        pet_window.set_pet_state(TaskStatus.SUCCESS if success else TaskStatus.FAILED)

        status = "success" if success else "failed"
        source = summary
        short_result = source[:120] + "..." if len(source) > 120 else source

        card = TaskCardModel(
            title="任务完成" if success else "任务失败",
            status=status,
            task_id=task_id,
            short_result=short_result,
            details=summary if success else f"{summary}\n\n错误详情: {error_message or '无'}",
            exp_reward=_last_exp_reward if success else 0,
        )
        _last_exp_reward = 0
        task_card_panel.show_card(card)
        task_card_panel.show_at_corner()

        display_content = summary

        assistant_msg = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="assistant",
            content=display_content,
        )
        chat_repo.save_message(assistant_msg)

        if session_id == task_panel.current_session_id:
            task_panel.add_pet_response(
                display_content, session_id,
                created_at=assistant_msg.created_at, msg_id=assistant_msg.id
            )
        if not success:
            state_mgr.on_task_error()
        else:
            state_mgr.on_task_complete()
        _update_state_display()

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
            task_panel.current_session_id = session_id
            task_panel._load_session_messages(session_id)

        history_window.session_selected.connect(on_session_selected)
        history_window.exec()

    _settings_window = None

    def on_settings_requested():
        from ui.settings_window import SettingsWindow

        nonlocal _settings_window
        if _settings_window is not None and _settings_window.isVisible():
            _settings_window.raise_()
            _settings_window.activateWindow()
            return

        try:
            _settings_window = SettingsWindow(settings)
        except Exception as e:
            QMessageBox.critical(None, "Error", f"Failed to open settings: {e}")
            return

        def on_settings_saved(updated_settings: Settings):
            nonlocal settings
            settings = updated_settings
            task_manager.settings = updated_settings
            task_manager.adapter.settings = updated_settings
            task_manager.adapter.subagent_factory.settings = updated_settings
            task_manager.adapter.history_compressor.settings = updated_settings
            _apply_theme_from_settings(theme_mgr, updated_settings)
            pet_window.reload_appearance()
            pet_window.set_settings(updated_settings)
            task_panel.set_settings(updated_settings)
            state_mgr.enabled = updated_settings.pet_state_enabled
            _update_state_display()

        _settings_window.settings_saved.connect(on_settings_saved)

        def on_settings_destroyed():
            nonlocal _settings_window
            _settings_window = None

        _settings_window.destroyed.connect(on_settings_destroyed)
        _settings_window.show()

    task_panel.history_requested.connect(on_history_requested)
    task_panel.settings_requested.connect(on_settings_requested)

    def on_task_continue(task_id: str):
        show_task_panel()

    task_card_panel.continue_clicked.connect(on_task_continue)

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
        pet_appearance.task_panel_width = max(task_panel.width(), 420)
        pet_appearance.task_panel_height = max(task_panel.height(), 520)
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
    pet_window.click_feedback_changed.connect(_update_state_display)
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
