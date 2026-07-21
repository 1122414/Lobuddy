"""UI Controller — signal wiring, startup sequences, and shutdown.

All non-critical UI modules are lazily imported inside their handler
functions with error handling — first-open failure shows a message
rather than crashing the app.
"""

import logging
import os
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QMessageBox

from app.config import Settings
from app.container import AppContainer
from app.service_wiring import apply_theme_from_settings
from core.companion.models import CompanionSupportMode
from core.focus.focus_companion import FocusState
from core.logging.trace import get_logger
from core.models.chat import ChatMessage
from core.models.pet import TaskStatus
from core.models.task_card import TaskCardModel, TaskStep
from core.time_format import get_greeting_for_hour
from ui.theme import ThemeManager

system_log = get_logger("system")


class UiController:
    """Wires Qt signals, manages startup sequence, and handles shutdown."""

    def __init__(self, container: AppContainer):
        self.c = container
        self._last_exp_reward = 0
        self._settings_window = None
        self._memory_console_window = None
        self._memory_recall_dialog = None
        self._memory_recall_task_id = ""
        self._relationship_rhythm_dialog = None
        self._skill_lab_window = None
        self._data_control_dialog = None
        self._task_run_snapshots: dict[str, object] = {}

    def start(self) -> int:
        c = self.c

        theme_mgr = ThemeManager.instance()
        theme_mgr.theme_changed.connect(c.pet_window.refresh_theme)
        theme_mgr.theme_changed.connect(c.task_panel.refresh_theme)
        theme_mgr.theme_changed.connect(c.task_card_panel.refresh_theme)
        c.pet_window.refresh_theme()
        c.task_panel.refresh_theme()
        c.task_card_panel.refresh_theme()

        first_run = c.settings_repo.get_setting("first_run_completed") != "true"
        if first_run:
            welcome = QMessageBox()
            welcome.setWindowTitle("Welcome to Lobuddy!")
            welcome.setText(
                "\U0001f431 Welcome to Lobuddy - Your AI Desktop Pet!\n\n"
                "Lobuddy will stay on your desktop and help you with tasks.\n\n"
                "Quick tips:\n"
                "\u2022 Left-click: Open quick menu\n"
                "\u2022 Right-click: Context menu\n"
                "\u2022 Ctrl+Shift+L: Toggle chat panel\n"
                "\u2022 Tray icon: Exit application\n\n"
                "Your pet starts at Lv1. Complete tasks to help it grow!"
            )
            welcome.setIcon(QMessageBox.Icon.Information)
            welcome.exec()
            c.settings_repo.set_setting("first_run_completed", "true")

        last_sessions = c.chat_repo.get_all_sessions(limit=1)
        if last_sessions:
            chat_session = c.chat_repo.get_session(last_sessions[0].id)
            c.task_panel.current_session_id = chat_session.id
        else:
            chat_session = c.chat_repo.get_or_create_session("default", "default")
            c.task_panel.current_session_id = "default"
        for msg in chat_session.messages:
            is_user = msg.role == "user"
            c.task_panel._add_message_to_display(
                msg.content,
                is_user=is_user,
                is_markdown=not is_user,
                image_path=msg.image_path or "",
                created_at=msg.created_at,
                msg_id=msg.id,
            )
        QTimer.singleShot(200, c.task_panel._scroll_bottom)

        self._wire_companion_feedback()
        settings = c.settings
        if settings.daily_greeting_enabled:
            hour = datetime.now().hour
            greeting_key = get_greeting_for_hour(hour)
            greeting_map = {
                "morning": settings.greeting_morning,
                "afternoon": settings.greeting_afternoon,
                "evening": settings.greeting_evening,
                "night": settings.greeting_night,
            }
            msg = greeting_map.get(greeting_key, "")
            session_id = getattr(c.task_panel, "current_session_id", "")
            privacy_active = bool(
                c.services.privacy_manager
                and c.services.privacy_manager.is_privacy_active(session_id)
            )
            intervention = (
                c.services.companion_runtime.startup_greeting(
                    msg,
                    privacy_active=privacy_active,
                )
                if c.services.companion_runtime is not None
                else None
            )
            if intervention is not None:
                c.pet_window.show_companion_intervention(intervention)

        self._wire_idle_timer()
        self._wire_task_signals()
        self._wire_focus_signals()
        self._wire_pet_growth_signals()
        self._wire_ui_signals()
        self._wire_exit_signals()
        self._wire_privacy_indicator()

        if c.services.skill_manager is not None:
            stats = c.services.skill_manager.get_candidate_stats()
            c.task_panel.update_skill_candidate_count(stats["pending"])

        pet = c.pet_repo.get_or_create_pet()
        c.pet_window.set_pet_state(TaskStatus.IDLE)
        c.pet_window.update_exp_display(pet.exp, pet.get_exp_for_next_level(), pet.level)

        c.pet_window.show()
        c.system_tray.show()
        c.hotkey_manager.start()

        if sys.platform == "win32":
            self._register_console_handler()

        try:
            exit_code = c.app.exec()
        finally:
            self.shutdown()
        return exit_code

    def shutdown(self) -> None:
        c = self.c

        c.pet_appearance.position_x = c.pet_window.x()
        c.pet_appearance.position_y = c.pet_window.y()
        c.pet_appearance.task_panel_width = max(c.task_panel.width(), 420)
        c.pet_appearance.task_panel_height = max(c.task_panel.height(), 520)
        from core.models.appearance import save_appearance

        save_appearance(c.pet_appearance)

        analysis_thread = None
        svc = c.services
        if c.settings.exit_analysis_enabled and svc.memory_service is not None:
            session_id = getattr(c.task_panel, "current_session_id", "")
            if session_id:

                def _run_exit_analysis():
                    try:
                        from core.memory.exit_analyzer import ExitAnalyzer

                        analyzer = ExitAnalyzer(
                            c.settings,
                            svc.memory_service,
                            gateway=svc.memory_gateway,
                            privacy=svc.privacy_manager,
                        )
                        analyzer.analyze_and_persist(session_id)
                    except Exception as e:
                        logging.getLogger(__name__).debug("Exit analysis error: %s", e)

                analysis_thread = threading.Thread(target=_run_exit_analysis, daemon=True)
                analysis_thread.start()

        if analysis_thread is not None:
            analysis_thread.join(timeout=3.5)

        if svc.runtime_maintenance is not None:
            svc.runtime_maintenance.stop()
        if svc.screen_region_runtime is not None:
            svc.screen_region_runtime.clear_all()

        killer = threading.Timer(0.5, lambda: os._exit(0))
        killer.daemon = True
        killer.start()

        c.system_tray.hide()
        c.pet_window.force_close()
        c.task_panel.close()
        c.task_card_panel.close()
        if self._skill_lab_window is not None:
            self._skill_lab_window.close()
        c.app.exit(0)

        if c.loop.is_running():
            import asyncio

            future = asyncio.run_coroutine_threadsafe(c.task_manager.queue.stop(), c.loop)
            try:
                future.result(timeout=2)
            except Exception:
                pass
        c.hotkey_manager.stop()
        for task in asyncio.all_tasks(c.loop):
            task.cancel()
        c.loop.call_soon_threadsafe(c.loop.stop)
        worker_stopped = c.worker.wait(3000)
        if not worker_stopped:
            c.worker.force_stop()
            worker_stopped = not c.worker.isRunning()
        if not worker_stopped or not True:
            print("[CRITICAL] Shutdown incomplete; forcing process exit")
            os._exit(0)

    def _wire_idle_timer(self) -> None:
        c = self.c

        state_texts = {
            "idle": c.settings.pet_state_text_idle,
            "listening": c.settings.pet_state_text_listening,
            "thinking": c.settings.pet_state_text_thinking,
            "working": c.settings.pet_state_text_working,
            "happy": c.settings.pet_state_text_happy,
            "sleepy": c.settings.pet_state_text_sleepy,
            "error": c.settings.pet_state_text_error,
        }

        def _update_state_display():
            text = c.state_mgr.get_state_text(state_texts)
            if text and c.state_mgr.enabled:
                c.pet_window.set_pet_state_override(text)

        def _on_task_panel_input_change():
            if c.task_panel.input_box.text():
                c.state_mgr.on_user_typing()

        _update_state_display()

        def _on_idle_timer():
            now = datetime.now()
            idle_minutes = 0.0
            runtime = c.services.companion_runtime
            if runtime is not None:
                session_id = getattr(c.task_panel, "current_session_id", "")
                privacy_active = bool(
                    c.services.privacy_manager
                    and c.services.privacy_manager.is_privacy_active(session_id)
                )
                focus_active = bool(
                    c.services.focus_companion and c.services.focus_companion.is_active
                )
                result = runtime.poll(
                    privacy_active=privacy_active,
                    focus_active=focus_active,
                    now=now,
                )
                idle_minutes = result.snapshot.idle_seconds / 60
                if result.intervention is not None:
                    c.pet_window.show_companion_intervention(result.intervention)
            screen_runtime = c.services.screen_region_runtime
            if screen_runtime is not None:
                attached_path = c.task_panel.current_image_path or ""
                managed_before_prune = bool(
                    attached_path and screen_runtime.owns_path(attached_path)
                )
                screen_runtime.prune()
                if managed_before_prune and not screen_runtime.owns_path(attached_path):
                    c.task_panel._clear_image_preview(notify=False)
                    c.task_panel.set_agent_status(
                        "选区已过期",
                        "需要时可以重新框选",
                        tone="idle",
                    )
            c.state_mgr.update_time_based_state(
                now.hour,
                idle_minutes,
                c.settings.pet_idle_after_minutes,
                c.settings.pet_sleepy_start_hour,
                c.settings.pet_sleepy_end_hour,
            )
            _update_state_display()

        self._update_state_display = _update_state_display
        c.idle_timer.setInterval(c.settings.observation_interval_seconds * 1000)
        c.idle_timer.timeout.connect(_on_idle_timer)
        c.idle_timer.start()
        c.task_panel.input_box.textChanged.connect(_on_task_panel_input_change)
        c.pet_window.click_feedback_changed.connect(_update_state_display)

    def _should_save_chat_history(self, session_id: str) -> bool:
        svc = self.c.services
        if svc.privacy_manager is None:
            return True
        if not svc.privacy_manager.is_privacy_active(session_id):
            return True
        return self.c.settings.privacy_mode_allow_chat_history

    def _wire_task_signals(self) -> None:
        c = self.c

        def run_projection(task_id: str):
            snapshot = self._task_run_snapshots.get(task_id)
            if snapshot is not None:
                return snapshot
            try:
                snapshot = c.task_manager.get_task_run(task_id)
            except ValueError:
                return None
            self._task_run_snapshots[task_id] = snapshot
            return snapshot

        def run_meta(snapshot) -> str:
            if snapshot is None:
                return ""
            parts = []
            if snapshot.attempt_no > 1:
                parts.append(f"第 {snapshot.attempt_no} 次尝试")
            if snapshot.elapsed_seconds:
                parts.append(
                    f"已用 {c.task_manager.task_runs.format_duration(snapshot.elapsed_seconds)}"
                )
            if snapshot.estimated_remaining_seconds:
                parts.append(
                    "预计还需 "
                    + c.task_manager.task_runs.format_duration(snapshot.estimated_remaining_seconds)
                )
            elif snapshot.status == TaskStatus.QUEUED and snapshot.estimated_duration_seconds:
                parts.append(
                    "预计约 "
                    + c.task_manager.task_runs.format_duration(snapshot.estimated_duration_seconds)
                )
            if snapshot.usage_evidence.available:
                usage_label = "实测" if snapshot.usage_evidence.source.value == "provider" else "估算"
                parts.append(
                    f"{usage_label} "
                    + c.task_manager.task_runs.format_token_usage(
                        snapshot.usage_evidence.total_tokens
                    )
                    + " Token"
                )
            elif snapshot.estimated_token_usage > 0:
                parts.append(
                    "参考预算 "
                    + c.task_manager.task_runs.format_token_usage(snapshot.estimated_token_usage)
                    + " Token"
                )
            return " · ".join(parts)

        def run_steps(snapshot) -> list[TaskStep]:
            if snapshot is None:
                return []
            titles = {stage.key: stage.title for stage in snapshot.stages}
            critical = set(snapshot.critical_path)
            steps = []
            for stage in snapshot.stages:
                if stage.finished_at is not None and stage.duration_ms > 0:
                    duration_text = c.task_manager.task_runs.format_stage_duration(
                        stage.duration_ms
                    )
                elif stage.duration_ms > 0:
                    duration_text = "已用 " + c.task_manager.task_runs.format_stage_duration(
                        stage.duration_ms
                    )
                elif stage.estimated_duration_seconds > 0:
                    duration_text = "预计 " + c.task_manager.task_runs.format_duration(
                        stage.estimated_duration_seconds
                    )
                else:
                    duration_text = ""
                waiting_text = ""
                if stage.blocked_by:
                    waiting_labels = [
                        titles.get(dependency, "前置阶段") for dependency in stage.blocked_by
                    ]
                    waiting_text = "等待：" + "、".join(waiting_labels[:2])
                elif stage.status.value == "warning":
                    waiting_text = "等待你的决定"
                steps.append(
                    TaskStep(
                        text=stage.title,
                        status=stage.status.value,
                        key=stage.key,
                        detail=(
                            stage.detail if len(stage.detail) <= 120 else stage.detail[:117] + "..."
                        ),
                        duration_text=duration_text,
                        waiting_text=waiting_text,
                        critical=stage.key in critical,
                    )
                )
            return steps

        def run_stage_summary(snapshot) -> str:
            if snapshot is None or not snapshot.stages:
                return ""
            parts = [f"工作阶段 {snapshot.completed_stage_count}/{len(snapshot.stages)}"]
            if snapshot.waiting_stage_count:
                parts.append(f"等待 {snapshot.waiting_stage_count}")
            if snapshot.critical_path_remaining_seconds:
                parts.append(
                    "关键路径约 "
                    + c.task_manager.task_runs.format_duration(
                        snapshot.critical_path_remaining_seconds
                    )
                )
            return " · ".join(parts)

        def show_task_panel():
            c.task_panel.set_position_near(c.pet_window.x(), c.pet_window.y())
            c.task_panel.show()

        def on_task_submitted(text: str, session_id: str, image_path: str = ""):
            current_settings = c.task_manager.settings
            screen_runtime = c.services.screen_region_runtime
            managed_screen_region = bool(
                image_path and screen_runtime is not None and screen_runtime.owns_path(image_path)
            )

            def discard_managed_region() -> None:
                if managed_screen_region and screen_runtime is not None:
                    screen_runtime.discard_path(image_path)

            if not current_settings.llm_api_key or not current_settings.llm_api_key.strip():
                discard_managed_region()
                QMessageBox.warning(
                    c.task_panel,
                    "API Key Missing",
                    "Please configure your LLM API Key in Settings first.",
                )
                return
            if not current_settings.llm_base_url or not current_settings.llm_base_url.strip():
                discard_managed_region()
                QMessageBox.warning(
                    c.task_panel,
                    "Base URL Missing",
                    "Please configure your LLM Base URL in Settings first.",
                )
                return
            if not current_settings.llm_model or not current_settings.llm_model.strip():
                discard_managed_region()
                QMessageBox.warning(
                    c.task_panel,
                    "Model Missing",
                    "Please configure your LLM Model in Settings first.",
                )
                return

            user_msg = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="user",
                content=text,
                image_path=(image_path if image_path and not managed_screen_region else None),
            )
            if self._should_save_chat_history(session_id):
                c.chat_repo.save_message(user_msg)

            import asyncio

            async def submit() -> str:
                if managed_screen_region and screen_runtime is not None:
                    return await screen_runtime.handoff_to_task(
                        image_path,
                        lambda managed_path: c.task_manager.submit_task(
                            text,
                            session_id,
                            managed_path,
                        ),
                    )
                return await c.task_manager.submit_task(text, session_id, image_path)

            future = asyncio.run_coroutine_threadsafe(submit(), c.loop)

            def submission_done(completed) -> None:
                try:
                    completed.result()
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "Task submission failed: %s",
                        exc,
                    )

                    def show_failure() -> None:
                        c.task_panel.set_agent_status(
                            "没有开始执行",
                            "临时选区已删除",
                            tone="error",
                        )
                        QMessageBox.warning(
                            c.task_panel,
                            "任务没有开始",
                            str(exc),
                        )

                    QTimer.singleShot(0, c.task_panel, show_failure)

            future.add_done_callback(submission_done)
            c.state_mgr.on_message_sent()
            self._update_state_display()

        def on_task_started(task_id: str):
            snapshot = run_projection(task_id)
            c.pet_window.set_pet_state(TaskStatus.RUNNING)
            c.task_panel.set_agent_status(
                "正在替你处理",
                "可以继续和我说话",
                tone="working",
            )
            c.state_mgr.on_task_running()
            self._update_state_display()
            card = TaskCardModel(
                title="正在处理这件事",
                status="running",
                task_id=task_id,
                short_result="我已经开始行动，关键步骤会及时告诉你。",
                meta_text=run_meta(snapshot),
                progress=snapshot.progress if snapshot is not None else 0.08,
                steps=run_steps(snapshot),
                stage_summary=run_stage_summary(snapshot),
            )
            c.task_card_panel.show_card(card)
            c.task_card_panel.show_at_corner()

        def on_task_completed(
            task_id: str, session_id: str, success: bool, summary: str, error_message: str
        ):
            if c.services.screen_region_runtime is not None:
                c.services.screen_region_runtime.release_task(task_id)
            snapshot = run_projection(task_id)
            cancelled = snapshot is not None and snapshot.status == TaskStatus.CANCELLED
            if cancelled:
                pet_status = TaskStatus.CANCELLED
                agent_title = "已安全暂停"
                agent_detail = "没有自动继续或重放"
                agent_tone = "warning"
                card_status = "cancelled"
                card_title = "这项工作已安全暂停"
                card_details = f"{summary}\n\n暂停原因：{error_message or '用户或应用停止了任务'}"
            elif success:
                pet_status = TaskStatus.SUCCESS
                agent_title = "已经完成"
                agent_detail = "结果已放进对话"
                agent_tone = "success"
                card_status = "success"
                card_title = "这件事处理好了"
                card_details = summary
            else:
                pet_status = TaskStatus.FAILED
                agent_title = "需要一起看看"
                agent_detail = "你可以让我换一种方式"
                agent_tone = "error"
                card_status = "failed"
                card_title = "这次没能完成"
                card_details = f"{summary}\n\n错误详情: {error_message or '无'}"
            exp_reward = self._last_exp_reward if success else 0
            c.pet_window.set_pet_state(pet_status)
            c.task_panel.set_agent_status(
                agent_title,
                agent_detail,
                tone=agent_tone,
            )
            short_result = summary[:120] + "..." if len(summary) > 120 else summary
            card = TaskCardModel(
                title=card_title,
                status=card_status,
                task_id=task_id,
                short_result=short_result,
                details=card_details,
                exp_reward=exp_reward,
                steps=run_steps(snapshot),
                available_actions=(
                    ["retry"] if snapshot is not None and snapshot.retryable else ["continue"]
                ),
                meta_text=run_meta(snapshot),
                progress=snapshot.progress if snapshot is not None else 1.0,
                stage_summary=run_stage_summary(snapshot),
            )
            c.task_card_panel.show_card(card)
            c.task_card_panel.show_at_corner()
            self._last_exp_reward = 0
            if c.services.skill_manager is not None:
                stats = c.services.skill_manager.get_candidate_stats()
                c.task_panel.update_skill_candidate_count(stats["pending"])

            assistant_msg = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content=summary,
            )
            if self._should_save_chat_history(session_id):
                c.chat_repo.save_message(assistant_msg)

            if session_id == c.task_panel.current_session_id:
                c.task_panel.add_pet_response(
                    summary,
                    session_id,
                    created_at=assistant_msg.created_at,
                    msg_id=assistant_msg.id,
                )
            if cancelled:
                c.state_mgr.on_task_complete()
            elif not success:
                c.state_mgr.on_task_error()
            else:
                c.state_mgr.on_task_complete()
            runtime = c.services.companion_runtime
            if runtime is not None and not cancelled:
                privacy_active = bool(
                    c.services.privacy_manager
                    and c.services.privacy_manager.is_privacy_active(session_id)
                )
                focus_active = bool(
                    c.services.focus_companion and c.services.focus_companion.is_active
                )
                intervention = runtime.record_task_outcome(
                    success,
                    privacy_active=privacy_active,
                    focus_active=focus_active,
                )
                if intervention is not None:
                    c.pet_window.show_companion_intervention(intervention)
            self._update_state_display()

        c.task_manager.task_started.connect(on_task_started)
        c.task_manager.task_completed.connect(on_task_completed)

        def on_task_run_updated(snapshot) -> None:
            self._task_run_snapshots[snapshot.task_id] = snapshot
            if snapshot.status == TaskStatus.QUEUED:
                c.task_card_panel.show_card(
                    TaskCardModel(
                        title=("已安排重新尝试" if snapshot.attempt_no > 1 else "已加入工作队列"),
                        status="pending",
                        task_id=snapshot.task_id,
                        short_result=snapshot.input_summary,
                        meta_text=run_meta(snapshot),
                        progress=snapshot.progress,
                    )
                )
                c.task_card_panel.show_at_corner()
                return
            if snapshot.status != TaskStatus.RUNNING:
                return
            steps = run_steps(snapshot)
            latest = steps[-1] if steps else None
            card_status = (
                "warning" if latest is not None and latest.status == "warning" else "running"
            )
            is_computer_use = bool(
                snapshot.stages and snapshot.stages[-1].family.startswith("computer-")
            )
            c.task_card_panel.show_card(
                TaskCardModel(
                    title="受控电脑操作" if is_computer_use else "正在处理这件事",
                    status=card_status,
                    task_id=snapshot.task_id,
                    short_result=(latest.text if latest is not None else "正在规划并执行这项工作"),
                    steps=steps,
                    meta_text=run_meta(snapshot),
                    progress=snapshot.progress,
                    stage_summary=run_stage_summary(snapshot),
                )
            )
            c.task_card_panel.show_at_corner()

        c.task_manager.task_run_updated.connect(on_task_run_updated)

        def on_memory_context_prepared(event) -> None:
            if event.session_id == c.task_panel.current_session_id:
                c.task_panel.update_memory_context(event)

        c.task_manager.memory_context_prepared.connect(on_memory_context_prepared)

        def on_memory_context_requested(task_id: str) -> None:
            control = c.services.memory_control
            if control is None:
                QMessageBox.information(c.task_panel, "记忆反馈", "记忆服务尚未初始化")
                return
            if (
                self._memory_recall_dialog is not None
                and self._memory_recall_dialog.isVisible()
                and self._memory_recall_task_id == task_id
            ):
                self._memory_recall_dialog.raise_()
                self._memory_recall_dialog.activateWindow()
                return
            if self._memory_recall_dialog is not None:
                self._memory_recall_dialog.close()
            try:
                from ui.memory_recall_review_dialog import MemoryRecallReviewDialog

                dialog = MemoryRecallReviewDialog(
                    control,
                    task_id,
                    parent=c.task_panel,
                )
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Memory recall review failed: %s",
                    exc,
                    exc_info=True,
                )
                QMessageBox.warning(c.task_panel, "记忆反馈", f"无法打开这次记忆反馈：{exc}")
                return

            self._memory_recall_dialog = dialog
            self._memory_recall_task_id = task_id

            def on_memory_changed(_memory_id: str) -> None:
                if self._memory_console_window is not None:
                    self._memory_console_window.refresh()
                if self._relationship_rhythm_dialog is not None:
                    self._relationship_rhythm_dialog.refresh()

            def on_memory_recall_destroyed() -> None:
                if self._memory_recall_dialog is dialog:
                    self._memory_recall_dialog = None
                    self._memory_recall_task_id = ""

            dialog.memory_changed.connect(on_memory_changed)
            dialog.destroyed.connect(on_memory_recall_destroyed)
            dialog.show()

        c.task_panel.memory_context_requested.connect(on_memory_context_requested)

        def on_computer_use_progress(event) -> None:
            status = (
                event.status
                if event.status in {"pending", "running", "success", "warning", "failed"}
                else "running"
            )
            detail = event.detail if len(event.detail) <= 90 else event.detail[:87] + "..."
            c.task_panel.set_agent_status(
                event.title,
                detail,
                tone=(
                    "error"
                    if status == "failed"
                    else ("success" if event.phase == "completed" else "working")
                ),
            )

        c.task_manager.computer_use_progress.connect(on_computer_use_progress)
        c.pet_window.chat_requested.connect(show_task_panel)
        c.task_panel.task_submitted.connect(on_task_submitted)
        c.task_panel.attachment_cleared.connect(
            lambda path: (
                c.services.screen_region_runtime.discard_path(path)
                if c.services.screen_region_runtime is not None
                else None
            )
        )

        def on_screen_region_requested() -> None:
            runtime = c.services.screen_region_runtime
            if runtime is None or not runtime.available:
                QMessageBox.information(
                    c.task_panel,
                    "屏幕选区暂不可用",
                    "请先在设置中启用屏幕选区，并配置图片分析模型。",
                )
                return

            c.task_panel.hide()

            def select_region() -> None:
                from ui.screen_region_selector import ScreenRegionSelector

                try:
                    selector = ScreenRegionSelector(
                        c.task_panel,
                        minimum_size=c.task_manager.settings.screen_region_min_size_px,
                    )
                except Exception as exc:
                    show_task_panel()
                    QMessageBox.warning(
                        c.task_panel,
                        "无法截取当前屏幕",
                        str(exc),
                    )
                    return

                result = selector.exec()
                show_task_panel()
                c.task_panel.raise_()
                c.task_panel.activateWindow()
                if result != QDialog.DialogCode.Accepted:
                    if selector.error_message:
                        QMessageBox.warning(
                            c.task_panel,
                            "无法创建屏幕选区",
                            selector.error_message,
                        )
                    return
                try:
                    capture = runtime.adopt_temporary_capture(selector.selected_draft())
                except Exception as exc:
                    QMessageBox.warning(
                        c.task_panel,
                        "无法使用这个屏幕选区",
                        str(exc),
                    )
                    return
                c.task_panel.attach_screen_region(capture)
                c.task_panel.set_agent_status(
                    "已看见你框选的区域",
                    "说说想了解什么，或直接发送",
                    tone="listening",
                )

            QTimer.singleShot(180, select_region)

        c.task_panel.screen_region_requested.connect(on_screen_region_requested)
        c.task_card_panel.continue_clicked.connect(lambda tid: show_task_panel())

        def on_retry_requested(task_id: str) -> None:
            try:
                review = c.task_manager.get_task_recovery_review(task_id)
                from ui.task_recovery_dialog import TaskRecoveryDialog

                dialog = TaskRecoveryDialog(review, c.task_panel)
            except Exception as exc:
                QMessageBox.warning(
                    c.task_panel,
                    "无法准备恢复审查",
                    str(exc),
                )
                return
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            import asyncio

            future = asyncio.run_coroutine_threadsafe(
                c.task_manager.retry_task(
                    task_id,
                    recovery_fingerprint=review.fingerprint,
                ),
                c.loop,
            )

            poll_timer = QTimer(c.task_panel)
            poll_timer.setInterval(80)

            def retry_done() -> None:
                if not future.done():
                    return
                poll_timer.stop()
                poll_timer.deleteLater()
                try:
                    future.result()
                except Exception as exc:
                    QMessageBox.warning(
                        c.task_panel,
                        "无法重新尝试",
                        str(exc),
                    )

            poll_timer.timeout.connect(retry_done)
            poll_timer.start()

        c.task_card_panel.retry_clicked.connect(on_retry_requested)
        c.hotkey_manager.activated.connect(show_task_panel)

    def _wire_companion_feedback(self) -> None:
        c = self.c

        def on_feedback(intervention_id: int, action: str) -> None:
            runtime = c.services.companion_runtime
            if runtime is None:
                return
            try:
                result = runtime.submit_feedback(intervention_id, action)
            except ValueError:
                logging.getLogger(__name__).warning(
                    "Ignored unknown companion feedback action: %s",
                    action,
                )
                return
            c.pet_window.show_speech_bubble(result.message, 4200)

        c.pet_window.companion_feedback_requested.connect(on_feedback)

        def on_check_in_requested() -> None:
            runtime = c.services.companion_runtime
            if runtime is None:
                return
            session_id = getattr(c.task_panel, "current_session_id", "")
            privacy_active = bool(
                c.services.privacy_manager
                and c.services.privacy_manager.is_privacy_active(session_id)
            )
            from ui.companion_checkin_dialog import CompanionCheckInDialog

            dialog = CompanionCheckInDialog(
                c.pet_window,
                active_check_in=runtime.active_check_in(),
                privacy_active=privacy_active,
                duration_minutes=c.settings.companion_checkin_duration_minutes,
            )

            def on_clear() -> None:
                runtime.clear_check_in()
                c.pet_window.show_speech_bubble(
                    "已经清除当前状态，我不会再用它调整陪伴方式。",
                    4200,
                )

            dialog.clear_requested.connect(on_clear)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                mood, energy, support_mode = dialog.selected_values()
                result = runtime.submit_check_in(
                    mood,
                    energy,
                    support_mode,
                    privacy_active=privacy_active,
                )
            except ValueError as exc:
                logging.getLogger(__name__).warning("Invalid companion Check-in: %s", exc)
                return
            c.pet_window.show_companion_intervention(result.intervention)
            if (
                support_mode == CompanionSupportMode.FOCUS
                and c.settings.focus_mode_enabled
                and c.services.focus_companion is not None
                and not c.services.focus_companion.is_active
            ):
                QTimer.singleShot(0, c.pet_window.focus_requested.emit)

        c.pet_window.companion_check_in_requested.connect(on_check_in_requested)

    def _wire_pet_growth_signals(self) -> None:
        c = self.c

        def on_pet_exp_gained(amount: int, current_exp: int, required_exp: int, level_up: bool):
            self._last_exp_reward = amount
            pet = c.pet_repo.get_or_create_pet()
            c.pet_window.update_exp_display(current_exp, required_exp, pet.level)
            c.pet_window.show_exp_gained(amount)

        def on_pet_level_up(level: int, stage: int):
            print(f"\U0001f389 Pet leveled up to Lv{level} (Stage {stage})!")
            pet = c.pet_repo.get_or_create_pet()
            c.pet_window.update_exp_display(0, pet.get_exp_for_next_level(), level)

        def on_ability_unlocked(ability_id: str, ability_name: str):
            print(f"\U0001f513 Ability unlocked: {ability_name}!")

        def on_personality_changed(adjustments: dict):
            evolution = c.services.personality_evolution
            if evolution is None:
                return
            expression = evolution.expression_for(adjustments)
            if expression is None:
                return

            def show_growth() -> None:
                c.pet_window.show_personality_expression(expression)
                if (
                    self._relationship_rhythm_dialog is not None
                    and self._relationship_rhythm_dialog.isVisible()
                ):
                    self._relationship_rhythm_dialog.refresh()

            QTimer.singleShot(650, show_growth)

        c.task_manager.pet_exp_gained.connect(on_pet_exp_gained)
        c.task_manager.pet_level_up.connect(on_pet_level_up)
        c.task_manager.pet_personality_changed.connect(on_personality_changed)
        c.task_manager.ability_unlocked.connect(on_ability_unlocked)

    def _wire_focus_signals(self) -> None:
        c = self.c
        svc = c.services

        def _on_focus_state_changed(state: FocusState):
            if state == FocusState.COMPLETED:
                if c.settings.focus_end_reminder_enabled:
                    c.pet_window.show_speech_bubble(
                        "这一轮专注完成啦，辛苦了。先松松肩膀，休息一下吧。",
                        5000,
                    )
                if c.settings.focus_auto_loop:
                    session = svc.focus_companion.current_session
                    if session:
                        session.start_break()
                else:
                    c.pet_window.clear_focus_timer()
                    c.pet_window.set_focus_active(False)
                    c.pet_window.update_focus_button_state("idle")
                    c.pet_window.clear_pet_state_override()
            elif state == FocusState.IDLE:
                if c.settings.focus_break_end_reminder_enabled:
                    c.pet_window.show_speech_bubble(
                        "休息时间结束啦。准备好了，我们再开始下一小段。",
                        5000,
                    )
                c.pet_window.clear_focus_timer()
                c.pet_window.set_focus_active(False)
                c.pet_window.update_focus_button_state("idle")
                c.pet_window.clear_pet_state_override()
            elif state == FocusState.PAUSED:
                c.pet_window.update_focus_button_state("paused")
                if svc.focus_companion.current_session:
                    c.pet_window.update_focus_timer(
                        svc.focus_companion.current_session.seconds_remaining
                    )
            elif state == FocusState.FOCUSING:
                c.pet_window.update_focus_button_state("focusing")

        def _connect_focus_session(session):
            if session:
                session.tick.connect(c.pet_window.update_focus_timer)
                session.state_changed.connect(lambda state: _on_focus_state_changed(state))

        def on_focus_button_clicked():
            if not c.settings.focus_mode_enabled:
                c.pet_window.show_speech_bubble(
                    "专注陪伴尚未启用，可以在设置里开启。",
                    4000,
                )
                return
            if not svc.focus_companion.is_active:
                session = svc.focus_companion.start_focus()
                _connect_focus_session(session)
                c.pet_window.set_focus_active(True)
                c.pet_window.update_focus_button_state("focusing")
                c.pet_window.set_pet_state_override(c.settings.focus_status_text)
            elif svc.focus_companion.is_paused:
                svc.focus_companion.resume()
                c.pet_window.update_focus_button_state("focusing")
            else:
                svc.focus_companion.pause()
                c.pet_window.update_focus_button_state("paused")

        def on_focus_stop():
            svc.focus_companion.stop()
            c.pet_window.clear_focus_timer()
            c.pet_window.set_focus_active(False)
            c.pet_window.clear_pet_state_override()

        c.pet_window.focus_requested.connect(on_focus_button_clicked)
        c.pet_window.focus_stop_requested.connect(on_focus_stop)

    def _wire_ui_signals(self) -> None:
        c = self.c

        def on_history_requested():
            from ui.history_window import HistoryWindow

            history_window = HistoryWindow(c.chat_repo, c.task_panel)

            def on_session_selected(session_id: str):
                c.task_panel.current_session_id = session_id
                c.task_panel._load_session_messages(session_id)

            history_window.session_selected.connect(on_session_selected)
            history_window.exec()

        def on_settings_requested():
            if self._settings_window is not None and self._settings_window.isVisible():
                self._settings_window.raise_()
                self._settings_window.activateWindow()
                return
            try:
                from ui.settings_window import SettingsWindow

                self._settings_window = SettingsWindow(c.settings)
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "Failed to open settings window: %s", e, exc_info=True
                )
                QMessageBox.critical(None, "Error", f"Failed to open settings: {e}")
                return

            def on_settings_saved(updated_settings: Settings):
                c.settings = updated_settings
                system_log.info(
                    "Settings updated — model=%s, theme=%s",
                    updated_settings.llm_model,
                    updated_settings.theme_preset,
                )
                c.task_manager.update_settings(updated_settings)
                c.task_manager.adapter.settings = updated_settings
                c.task_manager.adapter.subagent_factory.settings = updated_settings
                c.task_manager.adapter.history_compressor.settings = updated_settings
                apply_theme_from_settings(ThemeManager.instance(), updated_settings)
                c.pet_window.reload_appearance()
                c.pet_window.set_settings(updated_settings)
                c.task_panel.set_settings(updated_settings)
                c.state_mgr.enabled = updated_settings.pet_state_enabled
                c.idle_timer.setInterval(updated_settings.observation_interval_seconds * 1000)
                self._update_state_display()
                svc = c.services
                svc.memory_service.update_settings(updated_settings)
                svc.memory_service.refresh_bootstrap_memories()
                if svc.memory_gateway is not None:
                    svc.memory_gateway.update_settings(updated_settings)
                if svc.privacy_manager is not None:
                    svc.privacy_manager.update_settings(updated_settings)
                if svc.companion_runtime is not None:
                    svc.companion_runtime.update_settings(updated_settings)
                if svc.screen_region_runtime is not None:
                    svc.screen_region_runtime.update_settings(updated_settings)
                    attached_path = c.task_panel.current_image_path or ""
                    if attached_path and not svc.screen_region_runtime.owns_path(attached_path):
                        c.task_panel._clear_image_preview(notify=False)
                if svc.skill_manager is not None:
                    svc.skill_manager.update_settings(updated_settings)
                if svc.data_control is not None:
                    svc.data_control.update_settings(updated_settings)
                evolution = getattr(c.task_manager.adapter, "_skill_evolution", None)
                if evolution is not None:
                    evolution.update_settings(updated_settings)

            def on_settings_destroyed():
                self._settings_window = None

            self._settings_window.settings_saved.connect(on_settings_saved)
            self._settings_window.appearance_changed.connect(
                lambda: c.pet_window.reload_appearance()
            )
            self._settings_window.destroyed.connect(on_settings_destroyed)

            try:
                self._settings_window.show()
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "Settings showEvent failed: %s", e, exc_info=True
                )
                QMessageBox.critical(None, "Error", f"Failed to show settings: {e}")
                self._settings_window = None

        def on_pet_settings_requested():
            from ui.pet_settings_panel import PetSettingsPanel

            dialog = PetSettingsPanel(
                c.pet_appearance,
                c.pet_window,
                data_dir=c.settings.data_dir,
            )
            dialog.appearance_changed.connect(lambda: c.pet_window.reload_appearance())
            if dialog.exec() == QDialog.DialogCode.Accepted:
                c.pet_window.reload_appearance()
                c.pet_window.set_pet_state(TaskStatus.IDLE)

        def on_codex_pet_library_requested():
            from core.models.appearance import get_appearance, save_appearance
            from core.services.codex_pet_service import (
                CodexPetService,
                apply_codex_pet_appearance,
            )
            from core.services.pet_asset_service import PetAssetService
            from ui.asset_manager import AssetManager
            from ui.codex_pet_library_dialog import CodexPetLibraryDialog

            dialog = CodexPetLibraryDialog(
                CodexPetService(c.settings.data_dir),
                c.pet_window,
                initial_source="online",
            )
            if dialog.exec() != QDialog.DialogCode.Accepted or dialog.selected_result is None:
                return

            result = dialog.selected_result
            appearance = get_appearance()
            previous_path = appearance.custom_asset_path
            if previous_path and appearance.custom_asset_source != "codex":
                PetAssetService(c.settings.data_dir).remove_asset(Path(previous_path))
            apply_codex_pet_appearance(appearance, result)
            save_appearance(appearance)
            c.pet_appearance = appearance
            AssetManager.invalidate_pet_cache()
            c.pet_window.reload_appearance()
            c.pet_window.set_pet_state(TaskStatus.IDLE)
            c.pet_window.show_speech_bubble(
                f"{result.pet.display_name} 已经来到桌面，我会陪你一起完成接下来的事。",
                4200,
            )

        def on_about_requested():
            print("About requested (not yet implemented)")

        def on_observability_requested():
            svc = c.services
            if svc.observability is None:
                QMessageBox.information(None, "工作记录", "暂无运行数据")
                return
            try:
                from ui.observability_panel import ObservabilityPanel

                panel = ObservabilityPanel(svc.observability)
                panel.exec()
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "Observability panel failed: %s", e, exc_info=True
                )
                QMessageBox.warning(None, "工作记录", f"无法打开工作记录: {e}")

        def on_memory_console_requested():
            if not c.settings.memory_console_enabled:
                QMessageBox.information(None, "记忆控制台", "记忆控制台已在设置中禁用")
                return
            if self._memory_console_window is not None and self._memory_console_window.isVisible():
                self._memory_console_window.raise_()
                self._memory_console_window.activateWindow()
                return
            svc = c.services
            if svc.memory_control is None:
                QMessageBox.information(None, "记忆控制台", "记忆服务未初始化")
                return
            try:
                from ui.memory_console_window import MemoryConsoleWindow

                self._memory_console_window = MemoryConsoleWindow(
                    svc.memory_control,
                    session_id_provider=lambda: c.task_panel.current_session_id or "default",
                )
            except Exception as e:
                logging.getLogger(__name__).warning("Memory console failed: %s", e, exc_info=True)
                QMessageBox.critical(None, "错误", f"无法打开记忆控制台: {e}")
                return

            def on_memory_console_destroyed():
                self._memory_console_window = None

            self._memory_console_window.destroyed.connect(on_memory_console_destroyed)
            if (
                self._relationship_rhythm_dialog is not None
                and self._relationship_rhythm_dialog.isVisible()
            ):
                self._memory_console_window.memory_changed.connect(
                    self._relationship_rhythm_dialog.refresh
                )
            self._memory_console_window.show()

        def on_relationship_rhythm_requested():
            if (
                self._relationship_rhythm_dialog is not None
                and self._relationship_rhythm_dialog.isVisible()
            ):
                self._relationship_rhythm_dialog.refresh()
                self._relationship_rhythm_dialog.raise_()
                self._relationship_rhythm_dialog.activateWindow()
                return
            service = c.services.relationship_rhythm
            if service is None:
                QMessageBox.information(None, "相处节奏", "关系节奏服务尚未初始化")
                return
            try:
                from ui.relationship_rhythm_dialog import RelationshipRhythmDialog

                self._relationship_rhythm_dialog = RelationshipRhythmDialog(
                    service,
                    parent=c.task_panel,
                    session_id_provider=lambda: c.task_panel.current_session_id or "default",
                    personality_evolution=c.services.personality_evolution,
                )
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Relationship Rhythm failed: %s",
                    exc,
                    exc_info=True,
                )
                QMessageBox.critical(None, "错误", f"无法打开我们的相处节奏：{exc}")
                return

            def on_relationship_destroyed():
                self._relationship_rhythm_dialog = None

            def on_relationship_check_in():
                c.pet_window.companion_check_in_requested.emit()
                if self._relationship_rhythm_dialog is not None:
                    self._relationship_rhythm_dialog.refresh()

            self._relationship_rhythm_dialog.memory_requested.connect(on_memory_console_requested)
            self._relationship_rhythm_dialog.check_in_requested.connect(on_relationship_check_in)
            if self._memory_console_window is not None and self._memory_console_window.isVisible():
                self._memory_console_window.memory_changed.connect(
                    self._relationship_rhythm_dialog.refresh
                )
            self._relationship_rhythm_dialog.destroyed.connect(on_relationship_destroyed)
            self._relationship_rhythm_dialog.show()

        def on_skill_lab_requested():
            if not c.settings.skill_lab_enabled:
                QMessageBox.information(None, "能力进化", "能力进化实验室已在设置中禁用")
                return
            if self._skill_lab_window is not None and self._skill_lab_window.isVisible():
                self._skill_lab_window.raise_()
                self._skill_lab_window.activateWindow()
                return
            manager = c.services.skill_manager
            if manager is None:
                QMessageBox.information(None, "能力进化", "技能服务尚未初始化")
                return
            try:
                from ui.skill_lab_panel import SkillLabPanel

                self._skill_lab_window = SkillLabPanel(
                    manager,
                    c.settings,
                    parent=c.task_panel,
                )
            except Exception as exc:
                logging.getLogger(__name__).warning("Skill Lab failed: %s", exc, exc_info=True)
                QMessageBox.critical(None, "错误", f"无法打开能力进化实验室: {exc}")
                return

            def on_skill_lab_destroyed():
                self._skill_lab_window = None

            self._skill_lab_window.proposals_changed.connect(
                c.task_panel.update_skill_candidate_count
            )
            self._skill_lab_window.destroyed.connect(on_skill_lab_destroyed)
            self._skill_lab_window.show()

        def on_data_control_requested():
            session_id = c.task_panel.current_session_id or "default"
            if self._data_control_dialog is not None and self._data_control_dialog.isVisible():
                self._data_control_dialog.set_session(session_id)
                self._data_control_dialog.raise_()
                self._data_control_dialog.activateWindow()
                return
            control = c.services.data_control
            if control is None:
                QMessageBox.information(None, "数据与权限", "数据控制服务尚未初始化")
                return
            try:
                from ui.data_control_dialog import DataControlDialog

                self._data_control_dialog = DataControlDialog(
                    control,
                    session_id,
                    parent=c.task_panel,
                )
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Data Control failed: %s",
                    exc,
                    exc_info=True,
                )
                QMessageBox.critical(None, "错误", f"无法打开数据与权限：{exc}")
                return

            def on_data_control_destroyed():
                self._data_control_dialog = None

            def on_chat_cleared(cleared_session_id: str):
                if c.task_panel.current_session_id == cleared_session_id:
                    c.task_panel._load_session_messages(cleared_session_id)

            self._data_control_dialog.settings_requested.connect(on_settings_requested)
            self._data_control_dialog.memory_requested.connect(on_memory_console_requested)
            self._data_control_dialog.skills_requested.connect(on_skill_lab_requested)
            self._data_control_dialog.chat_cleared.connect(on_chat_cleared)
            self._data_control_dialog.destroyed.connect(on_data_control_destroyed)
            self._data_control_dialog.show()

        c.task_panel.history_requested.connect(on_history_requested)
        c.task_panel.settings_requested.connect(on_settings_requested)
        c.task_panel.skill_lab_requested.connect(on_skill_lab_requested)
        c.task_panel.data_control_requested.connect(on_data_control_requested)
        c.pet_window.settings_requested.connect(on_settings_requested)
        c.pet_window.pet_settings_requested.connect(on_pet_settings_requested)
        c.pet_window.codex_pet_library_requested.connect(on_codex_pet_library_requested)
        c.pet_window.memory_console_requested.connect(on_memory_console_requested)
        c.pet_window.relationship_rhythm_requested.connect(on_relationship_rhythm_requested)
        c.pet_window.data_control_requested.connect(on_data_control_requested)
        c.system_tray.settings_requested.connect(on_settings_requested)
        c.system_tray.about_requested.connect(on_about_requested)
        c.system_tray.observability_requested.connect(on_observability_requested)

    def _wire_exit_signals(self) -> None:
        c = self.c

        def on_exit_requested():
            if getattr(on_exit_requested, "_armed", False):
                return
            on_exit_requested._armed = True
            system_log.info("Shutdown initiated")
            _ = self.c  # noqa: F841
            c.system_tray.hide()
            c.pet_window.force_close()
            c.task_panel.close()
            c.task_card_panel.close()
            if self._skill_lab_window is not None:
                self._skill_lab_window.close()
            if self._data_control_dialog is not None:
                self._data_control_dialog.close()
            c.app.exit(0)

        def on_close_requested():
            on_exit_requested()

        c.system_tray.show_requested.connect(c.pet_window.show)
        c.system_tray.exit_requested.connect(on_exit_requested)
        c.pet_window.close_requested.connect(on_close_requested)

    def _wire_privacy_indicator(self) -> None:
        c = self.c
        svc = c.services
        if svc.privacy_manager is None:
            return

        def _on_privacy_changed(session_id: str, is_active: bool):
            if not getattr(c.settings, "privacy_mode_show_indicator", True):
                c.pet_window.show_privacy_indicator(False)
                return
            current_session = getattr(c.task_panel, "current_session_id", "")
            if session_id == current_session:
                c.pet_window.show_privacy_indicator(is_active)

        svc.privacy_manager.add_listener(_on_privacy_changed)

        current_session = getattr(c.task_panel, "current_session_id", "")
        if current_session:
            is_active = svc.privacy_manager.is_privacy_active(current_session)
            c.pet_window.show_privacy_indicator(is_active)

    def _register_console_handler(self) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        @PHANDLER_ROUTINE
        def _console_ctrl_handler(ctrl_type):
            if ctrl_type in (2, 5, 6):
                self.c.app.quit()
                return True
            return False

        kernel32.SetConsoleCtrlHandler(_console_ctrl_handler, True)
