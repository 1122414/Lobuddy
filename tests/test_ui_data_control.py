"""Offscreen UI tests for the Data Control dialog and entry point."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from core.data_control import (
    DataControlAction,
    DataControlCard,
    DataControlFact,
    DataControlResult,
    DataControlSnapshot,
    DataControlTone,
)
from ui.data_control_dialog import DataControlDialog


def _ensure_qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


class _Control:
    def __init__(self) -> None:
        self.privacy_active = False
        self.actions: list[DataControlAction] = []

    def snapshot(self, session_id: str) -> DataControlSnapshot:
        return DataControlSnapshot(
            session_id=session_id,
            privacy_active=self.privacy_active,
            headline=("本次对话受隐私模式保护" if self.privacy_active else "本次对话使用你的常规数据设置"),
            detail="每种数据都有独立的说明和撤销边界。",
            cards=[
                DataControlCard(
                    key="chat_history",
                    group="本次对话",
                    title="对话记录",
                    state_label="本机保存 · 2 条",
                    summary="当前对话消息保存在本机。",
                    tone=DataControlTone.ACTIVE,
                    facts=[
                        DataControlFact(label="保存", value="仅本机 SQLite"),
                    ],
                    action=DataControlAction.CLEAR_SESSION_CHAT,
                    action_label="清除当前对话",
                    requires_confirmation=True,
                ),
                DataControlCard(
                    key="model_sharing",
                    group="学习与模型",
                    title="模型服务",
                    state_label="已配置",
                    summary="任务发起时才发送必要上下文。",
                    tone=DataControlTone.ACTIVE,
                    facts=[
                        DataControlFact(label="不外发", value="API 密钥"),
                    ],
                    secondary_route="settings",
                    secondary_label="管理模型设置",
                ),
            ],
        )

    def execute(
        self,
        action: DataControlAction,
        session_id: str,
    ) -> DataControlResult:
        self.actions.append(action)
        if action == DataControlAction.ENABLE_SESSION_PRIVACY:
            self.privacy_active = True
        elif action == DataControlAction.DISABLE_SESSION_PRIVACY:
            self.privacy_active = False
        return DataControlResult(
            action=action,
            changed_count=1,
            message="状态已更新",
            snapshot=self.snapshot(session_id),
        )


def test_dialog_renders_plain_language_sections_and_enables_privacy():
    _ensure_qapp()
    control = _Control()
    dialog = DataControlDialog(control, "session-a")

    labels = {label.text() for label in dialog.findChildren(QLabel)}
    assert "数据与权限" in labels
    assert "本次对话" in labels
    assert "学习与模型" in labels
    assert "对话记录" in labels
    assert "模型服务" in labels

    privacy_button = next(
        button for button in dialog.findChildren(QPushButton) if button.text() == "开启本次隐私"
    )
    privacy_button.click()

    assert control.actions == [DataControlAction.ENABLE_SESSION_PRIVACY]
    assert dialog._snapshot is not None
    assert dialog._snapshot.privacy_active is True
    assert dialog._privacy_btn.text() == "退出隐私模式"
    dialog.close()


def test_dialog_routes_configuration_without_exposing_session_id():
    _ensure_qapp()
    dialog = DataControlDialog(_Control(), "private-session-id")
    requested: list[bool] = []
    dialog.settings_requested.connect(lambda: requested.append(True))

    route_button = next(
        button for button in dialog.findChildren(QPushButton) if button.text() == "管理模型设置"
    )
    route_button.click()

    visible_text = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert requested == [True]
    assert "private-session-id" not in visible_text
    dialog.close()
