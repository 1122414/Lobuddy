"""Regression tests for the companion command-center UI."""

import os
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton, QWidget

from app.config import Settings
from core.companion.models import (
    CompanionCheckIn,
    CompanionEnergy,
    CompanionFeedbackAction,
    CompanionIntervention,
    CompanionMood,
    CompanionSupportMode,
    InterventionKind,
)
from core.models.pet import TaskStatus
from core.models.task_card import TaskCardModel, TaskStep
from core.models.personality import PersonalityDimension
from core.personality.evolution_models import PersonalityExpression
from core.events import MemoryContextPrepared
from core.storage import db as db_module
from core.storage.chat_repo import ChatRepository
from core.storage.db import Database
from ui.asset_manager import AssetManager
from ui.companion_checkin_dialog import CompanionCheckInDialog
from ui.quick_action_menu import QuickActionMenu
from ui.pet_window import PetWindow
from ui.settings_window import SettingsWindow
from ui.task_card_panel import TaskCardPanel
from ui.task_panel import TaskPanel


def _ensure_qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_original_mascot_has_clean_transparent_corners():
    path = Path(__file__).parent.parent / "ui" / "assets" / "lobuddy_mascot.png"
    image = Image.open(path)

    assert image.mode == "RGBA"
    assert image.width <= 512
    assert image.height <= 512
    alpha = image.getchannel("A")
    assert alpha.getextrema() == (0, 255)
    assert [
        alpha.getpixel((0, 0)),
        alpha.getpixel((image.width - 1, 0)),
        alpha.getpixel((0, image.height - 1)),
        alpha.getpixel((image.width - 1, image.height - 1)),
    ] == [0, 0, 0, 0]


def test_default_pet_states_resolve_to_original_mascot(monkeypatch):
    _ensure_qapp()
    monkeypatch.setattr(AssetManager, "_instance", None)
    monkeypatch.setattr(AssetManager, "_pixmap_cache", {})
    manager = AssetManager()
    monkeypatch.setattr(manager.appearance, "custom_asset_path", None)
    monkeypatch.setattr(manager.appearance, "custom_asset_type", "default")

    assert manager._resolve_pet_image_path(TaskStatus.IDLE).name == "lobuddy_mascot.png"
    assert manager._resolve_pet_image_path(TaskStatus.RUNNING).name == "lobuddy_mascot.png"


def test_quick_menu_and_task_card_use_clear_chinese_states():
    _ensure_qapp()
    menu = QuickActionMenu()
    menu.set_focus_state("focusing")
    assert menu.chat_btn.text() == "打开对话"
    assert menu.focus_btn.text() == "暂停专注"
    assert menu.check_in_btn.text() == "说说现在的状态"
    assert menu.relationship_rhythm_btn.text() == "我们的相处节奏"
    assert menu.codex_pet_btn.text() == "Codex 伙伴库"
    requested: list[bool] = []
    menu.codex_pet_clicked.connect(lambda: requested.append(True))
    menu.codex_pet_btn.click()
    assert requested == [True]

    card_panel = TaskCardPanel()
    retried: list[str] = []
    card_panel.retry_clicked.connect(retried.append)
    card_panel.show_card(
        TaskCardModel(
            title="整理发布清单",
            status="running",
            task_id="run-1",
            short_result="正在核对测试",
            meta_text="第 2 次尝试 · 已用 18 秒 · 预计还需 42 秒",
            progress=0.42,
            stage_summary="工作阶段 1/2 · 关键路径约 8 秒",
            available_actions=["retry"],
            steps=[
                TaskStep(
                    text="观察并定位当前界面",
                    status="success",
                    detail="融合视觉与原生控件",
                    duration_text="6.5 秒",
                    critical=True,
                ),
                TaskStep(
                    text="验证执行结果",
                    status="running",
                    detail="保存成功提示可见",
                    duration_text="已用 1.2 秒",
                    waiting_text="等待：执行输入动作",
                    critical=True,
                ),
            ],
        )
    )
    assert card_panel.status_label.text() == "●  正在替你处理"
    assert card_panel.meta_label.text() == "第 2 次尝试 · 已用 18 秒 · 预计还需 42 秒"
    assert card_panel.findChild(QProgressBar).value() == 42
    assert card_panel.retry_btn.isVisible()
    assert not card_panel.continue_btn.isVisible()
    assert card_panel.steps_widget.isVisible()
    assert card_panel.height() > 204
    step_copy = {label.text() for label in card_panel.steps_widget.findChildren(QLabel)}
    assert "观察并定位当前界面" in step_copy
    assert "保存成功提示可见" in step_copy
    assert "工作阶段 1/2 · 关键路径约 8 秒" in step_copy
    assert "等待：执行输入动作" in step_copy
    assert "6.5 秒" in step_copy
    assert sum(label.text() == "关键" for label in card_panel.findChildren(QLabel)) == 2
    card_panel.retry_btn.click()
    assert retried == ["run-1"]

    card_panel.show_card(
        TaskCardModel(
            title="这项工作已安全暂停",
            status="cancelled",
            task_id="run-paused",
            short_result="任务已安全暂停",
        )
    )
    assert card_panel.status_label.text() == "●  已安全暂停"
    assert card_panel._current_card.status == "cancelled"

    menu.close()
    card_panel.close()


def test_pet_window_exposes_direct_codex_pet_library_action(monkeypatch):
    app = _ensure_qapp()
    monkeypatch.setattr(AssetManager, "_instance", None)
    monkeypatch.setattr(AssetManager, "_pixmap_cache", {})
    window = PetWindow()
    requested: list[bool] = []
    window.codex_pet_library_requested.connect(lambda: requested.append(True))

    window._quick_menu.codex_pet_btn.click()
    app.processEvents()

    assert requested == [True]
    assert not window._quick_menu.isVisible()
    window.close()


def test_pet_window_exposes_relationship_rhythm_action(monkeypatch):
    app = _ensure_qapp()
    monkeypatch.setattr(AssetManager, "_instance", None)
    monkeypatch.setattr(AssetManager, "_pixmap_cache", {})
    window = PetWindow()
    requested: list[bool] = []
    window.relationship_rhythm_requested.connect(lambda: requested.append(True))
    action = next(action for action in window._context_menu.actions() if action.text() == "我们的相处节奏")

    action.trigger()

    assert requested == [True]
    window._quick_menu.show()
    window._quick_menu.relationship_rhythm_btn.click()
    app.processEvents()
    assert requested == [True, True]
    assert not window._quick_menu.isVisible()
    window.close()


def test_pet_window_shows_task_grounded_personality_expression(monkeypatch):
    app = _ensure_qapp()
    monkeypatch.setattr(AssetManager, "_instance", None)
    monkeypatch.setattr(AssetManager, "_pixmap_cache", {})
    window = PetWindow()

    window.show_personality_expression(
        PersonalityExpression(
            dominant_dimension=PersonalityDimension.TECHNICAL_SKILL,
            badge_text="技术协作 +1",
            message="刚才这次技术协作，让我更熟悉一起解决问题的节奏了。",
        )
    )
    app.processEvents()

    assert not window._growth_badge.isHidden()
    assert window._growth_badge.text() == "技术协作 +1"
    assert not window._speech_bubble.isHidden()
    assert "技术协作" in window._speech_bubble.text()
    window.close()


def test_pet_window_plays_codex_action_without_changing_task_state(monkeypatch):
    app = _ensure_qapp()
    monkeypatch.setattr(AssetManager, "_instance", None)
    monkeypatch.setattr(AssetManager, "_pixmap_cache", {})
    window = PetWindow()
    window._asset_manager.appearance.custom_state_asset_paths = {"waving": "unused.gif"}
    rendered: list[TaskStatus | str] = []
    monkeypatch.setattr(window, "_set_pet_animation", rendered.append)

    window.set_pet_state(TaskStatus.RUNNING)
    window.play_pet_action("waving", 500)
    window._restore_task_animation()
    app.processEvents()

    assert rendered == [TaskStatus.RUNNING, "waving", TaskStatus.RUNNING]
    assert window._current_task_state == TaskStatus.RUNNING
    window.close()


def test_settings_expose_proactive_companion_and_computer_use(tmp_path):
    _ensure_qapp()
    settings = Settings(llm_api_key="test", data_dir=tmp_path / "data")
    db_module._db = Database(settings)
    db_module._db.init_database()
    try:
        window = SettingsWindow(settings)
        assert window.findChild(QPushButton, "codexPetLibraryButton") is not None
        assert window.findChild(QPushButton, "resetCompanionFeedbackButton") is not None
        assert window._feedback_snooze_spin.value() == settings.companion_feedback_snooze_minutes
        assert window._checkin_duration_spin.value() == settings.companion_checkin_duration_minutes
        assert window._observation_check.isChecked() is settings.observation_enabled
        assert window._proactive_companion_check.isChecked() is settings.proactive_companion_enabled
        assert window._screen_region_check.isChecked() is settings.screen_region_enabled
        assert window._screen_region_ttl_spin.value() == settings.screen_region_ttl_seconds
        assert window._computer_use_check.isChecked() is settings.computer_use_enabled
        assert (
            window._computer_use_observation_ttl_spin.value()
            == settings.computer_use_observation_ttl_seconds
        )
        assert (
            window._computer_use_high_impact_check.isChecked()
            is settings.computer_use_high_impact_confirmation
        )
        window.close()
    finally:
        db_module._db = None


def test_explainable_companion_card_emits_explicit_feedback(monkeypatch):
    app = _ensure_qapp()
    monkeypatch.setattr(AssetManager, "_instance", None)
    monkeypatch.setattr(AssetManager, "_pixmap_cache", {})
    window = PetWindow()
    feedback: list[tuple[int, str]] = []
    window.companion_feedback_requested.connect(
        lambda event_id, action: feedback.append((event_id, action))
    )

    window.show_companion_intervention(
        CompanionIntervention(
            event_id=42,
            kind=InterventionKind.REST,
            title="休息一下",
            message="活动一下肩颈、喝口水吧。",
            reason="检测到你已连续活跃约 51 分钟。",
        )
    )
    app.processEvents()

    card = window._companion_card
    assert card.isVisible()
    assert card.title_label.text() == "休息一下"
    assert "为什么现在" in card.reason_label.text()
    card.helpful_button.click()
    app.processEvents()

    assert feedback == [(42, CompanionFeedbackAction.HELPFUL.value)]
    assert not card.isVisible()
    window.close()


def test_check_in_dialog_is_explicit_revocable_and_privacy_clear():
    _ensure_qapp()
    parent = QWidget()
    now = datetime(2026, 7, 19, 10)
    active = CompanionCheckIn(
        mood=CompanionMood.TIRED,
        energy=CompanionEnergy.LOW,
        support_mode=CompanionSupportMode.LISTEN,
        created_at=now,
        expires_at=now + timedelta(hours=2),
    )
    dialog = CompanionCheckInDialog(
        parent,
        active_check_in=active,
        privacy_active=True,
        duration_minutes=120,
    )

    assert dialog.selected_values() == (
        CompanionMood.TIRED,
        CompanionEnergy.LOW,
        CompanionSupportMode.LISTEN,
    )
    assert dialog.active_card is not None
    assert dialog.clear_button is not None
    privacy_labels = [
        label.text()
        for label in dialog.findChildren(QLabel)
        if label.objectName() == "checkInPrivacy"
    ]
    assert privacy_labels and "只保留在当前运行内" in privacy_labels[0]

    cleared: list[bool] = []
    dialog.clear_requested.connect(lambda: cleared.append(True))
    dialog.clear_button.click()
    assert cleared == [True]
    dialog.close()
    parent.close()


def test_user_initiated_check_in_card_has_no_proactive_feedback_controls(monkeypatch):
    app = _ensure_qapp()
    monkeypatch.setattr(AssetManager, "_instance", None)
    monkeypatch.setattr(AssetManager, "_pixmap_cache", {})
    window = PetWindow()

    window.show_companion_intervention(
        CompanionIntervention(
            kind=InterventionKind.CHECK_IN,
            title="我在听",
            message="你可以慢慢说。",
            reason="根据你刚刚主动选择的状态回应。",
        )
    )
    app.processEvents()

    assert window._companion_card.isVisible()
    assert not window._companion_card.feedback_row.isVisible()
    window.close()


def test_command_center_button_styles_are_balanced_qss(tmp_path):
    _ensure_qapp()
    settings = Settings(llm_api_key="test", data_dir=tmp_path / "data")
    db_module._db = Database(settings)
    db_module._db.init_database()
    try:
        panel = TaskPanel(ChatRepository())
        panel.set_settings(settings)
        buttons = (
            *panel._header_buttons,
            panel._new_chat_btn,
            *panel._capability_buttons,
        )

        for button in buttons:
            style = button.styleSheet()
            assert style.count("{") == style.count("}")

        panel.close()
    finally:
        db_module._db = None


def test_task_panel_shows_content_minimized_memory_evidence(tmp_path):
    _ensure_qapp()
    settings = Settings(llm_api_key="test", data_dir=tmp_path / "data")
    db_module._db = Database(settings)
    db_module._db.init_database()
    try:
        panel = TaskPanel(ChatRepository())
        panel.set_settings(settings)
        panel.current_session_id = "session-a"
        event = MemoryContextPrepared(
            task_id="task-a",
            session_id="session-a",
            selected_count=3,
            reviewable_count=2,
            type_counts={"user_profile": 1, "episodic_memory": 2},
            total_chars=420,
        )
        requested = []
        panel.memory_context_requested.connect(requested.append)

        panel.update_memory_context(event)

        assert panel._memory_context_badge.text() == "记忆 · 3"
        assert not panel._memory_context_badge.isHidden()
        assert "用户偏好 1" in panel._memory_context_badge.toolTip()
        assert "情景记忆 2" in panel._memory_context_badge.toolTip()
        assert "420" not in panel._memory_context_badge.toolTip()
        assert "2 条可点击查看并反馈" in panel._memory_context_badge.toolTip()
        panel._memory_context_badge.click()
        assert requested == ["task-a"]

        panel.update_memory_context(
            MemoryContextPrepared(
                task_id="task-b",
                session_id="session-a",
                selected_count=0,
                privacy_active=True,
            )
        )
        assert panel._memory_context_badge.text() == "隐私 · 0"
        assert "未调用长期记忆" in panel._memory_context_badge.toolTip()
        panel.close()
    finally:
        db_module._db = None
