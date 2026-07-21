"""Explainable, low-pressure card for proactive companion care."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.companion.models import CompanionFeedbackAction, CompanionIntervention
from ui.theme import ThemeManager


class CompanionInterventionCard(QFrame):
    """Show one care intervention with its reason and explicit feedback actions."""

    feedback_selected = Signal(int, str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("companionInterventionCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(336)
        self._event_id: int | None = None

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.hide)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 8)
        self.setGraphicsEffect(shadow)
        self._shadow = shadow

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.eyebrow_label = QLabel("主动关怀")
        self.eyebrow_label.setObjectName("companionEyebrow")
        header.addWidget(self.eyebrow_label)
        header.addStretch()
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("companionCloseButton")
        self.close_button.setFixedSize(24, 24)
        self.close_button.setToolTip("关闭这次提醒")
        self.close_button.clicked.connect(self.hide)
        header.addWidget(self.close_button)
        root.addLayout(header)

        self.title_label = QLabel("温柔提醒")
        self.title_label.setObjectName("companionTitle")
        root.addWidget(self.title_label)

        self.message_label = QLabel()
        self.message_label.setObjectName("companionMessage")
        self.message_label.setWordWrap(True)
        root.addWidget(self.message_label)

        self.reason_label = QLabel()
        self.reason_label.setObjectName("companionReason")
        self.reason_label.setWordWrap(True)
        root.addWidget(self.reason_label)

        self.feedback_row = QWidget(self)
        feedback_layout = QHBoxLayout(self.feedback_row)
        feedback_layout.setContentsMargins(0, 4, 0, 0)
        feedback_layout.setSpacing(7)

        self.helpful_button = QPushButton("有帮助")
        self.helpful_button.setObjectName("companionHelpfulButton")
        self.helpful_button.clicked.connect(
            lambda: self._submit_feedback(CompanionFeedbackAction.HELPFUL)
        )
        feedback_layout.addWidget(self.helpful_button)

        self.later_button = QPushButton("稍后再说")
        self.later_button.setObjectName("companionLaterButton")
        self.later_button.clicked.connect(
            lambda: self._submit_feedback(CompanionFeedbackAction.LATER)
        )
        feedback_layout.addWidget(self.later_button)

        self.mute_button = QPushButton("不再提醒此类")
        self.mute_button.setObjectName("companionMuteButton")
        self.mute_button.clicked.connect(
            lambda: self._submit_feedback(CompanionFeedbackAction.MUTE_KIND)
        )
        feedback_layout.addWidget(self.mute_button)
        root.addWidget(self.feedback_row)

        ThemeManager.instance().theme_changed.connect(self.refresh_theme)
        self.refresh_theme()

    def show_intervention(self, intervention: CompanionIntervention, anchor: QWidget) -> None:
        self._event_id = intervention.event_id
        self.eyebrow_label.setText("主动关怀 · 可解释")
        self.title_label.setText(intervention.title)
        self.message_label.setText(intervention.message)
        reason = intervention.reason or "根据你启用的本地陪伴偏好触发。"
        self.reason_label.setText(f"为什么现在 · {reason}")
        self.feedback_row.setVisible(intervention.event_id is not None)
        self.adjustSize()
        self._move_near(anchor)
        self.show()
        self.raise_()
        self._dismiss_timer.start(max(9000, intervention.duration_ms))

    def reposition(self, anchor: QWidget) -> None:
        if self.isVisible():
            self._move_near(anchor)

    def refresh_theme(self, _theme=None) -> None:
        theme = ThemeManager.instance().current
        shadow_color = QColor(theme.text)
        shadow_color.setAlpha(45)
        self._shadow.setColor(shadow_color)
        self.setStyleSheet(
            f"""
            QFrame#companionInterventionCard {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_lg}px;
            }}
            QLabel#companionEyebrow {{
                color: {theme.primary};
                font-size: 10px;
                font-weight: 700;
                background: transparent;
                border: none;
            }}
            QLabel#companionTitle {{
                color: {theme.text};
                font-size: 15px;
                font-weight: 700;
                background: transparent;
                border: none;
            }}
            QLabel#companionMessage {{
                color: {theme.text_secondary};
                font-size: 12px;
                background: transparent;
                border: none;
            }}
            QLabel#companionReason {{
                color: {theme.text_muted};
                background: {theme.surface_soft};
                border: 1px solid {theme.divider};
                border-radius: {theme.radius_sm}px;
                padding: 7px 9px;
                font-size: 10px;
            }}
            QPushButton {{
                min-height: 28px;
                padding: 0 9px;
                border-radius: {theme.radius_sm}px;
                font-size: 10px;
                font-weight: 600;
            }}
            QPushButton#companionHelpfulButton {{
                color: {theme.on_primary};
                background: {theme.primary};
                border: 1px solid {theme.primary};
            }}
            QPushButton#companionHelpfulButton:hover {{
                background: {theme.primary_hover};
            }}
            QPushButton#companionLaterButton {{
                color: {theme.text_secondary};
                background: {theme.surface_soft};
                border: 1px solid {theme.border};
            }}
            QPushButton#companionLaterButton:hover {{
                color: {theme.text};
                border-color: {theme.border_focus};
            }}
            QPushButton#companionMuteButton {{
                color: {theme.text_muted};
                background: transparent;
                border: 1px solid transparent;
            }}
            QPushButton#companionMuteButton:hover {{
                color: {theme.text_secondary};
                background: {theme.surface_soft};
            }}
            QPushButton#companionCloseButton {{
                color: {theme.text_muted};
                background: transparent;
                border: none;
                font-size: 16px;
                font-weight: 500;
                padding: 0;
            }}
            QPushButton#companionCloseButton:hover {{
                color: {theme.text};
                background: {theme.surface_soft};
            }}
            """
        )

    def enterEvent(self, event) -> None:
        self._dismiss_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._dismiss_timer.start(4500)
        super().leaveEvent(event)

    def _submit_feedback(self, action: CompanionFeedbackAction) -> None:
        if self._event_id is None:
            return
        event_id = self._event_id
        self._event_id = None
        self._dismiss_timer.stop()
        self.hide()
        self.feedback_selected.emit(event_id, action.value)

    def _move_near(self, anchor: QWidget) -> None:
        screen = QGuiApplication.screenAt(anchor.frameGeometry().center())
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:
            self.move(anchor.x() + anchor.width() + 12, anchor.y())
            return
        available = screen.availableGeometry()
        preferred_x = anchor.x() - self.width() - 12
        if preferred_x < available.left():
            preferred_x = anchor.x() + anchor.width() + 12
        x = min(max(preferred_x, available.left() + 8), available.right() - self.width() - 8)
        y = min(
            max(anchor.y() + 8, available.top() + 8),
            available.bottom() - self.height() - 8,
        )
        self.move(x, y)
