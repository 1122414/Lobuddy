"""Compact, user-governed state input for companion behavior."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.companion.models import (
    COMPANION_ENERGY_LABELS,
    COMPANION_MOOD_LABELS,
    COMPANION_SUPPORT_LABELS,
    CompanionCheckIn,
    CompanionEnergy,
    CompanionMood,
    CompanionSupportMode,
    companion_energy_label,
    companion_mood_label,
    companion_support_label,
)
from ui.theme import ThemeManager


class CompanionCheckInDialog(QDialog):
    """Ask for explicit state without collecting free-form personal content."""

    clear_requested = Signal()

    def __init__(
        self,
        parent: QWidget,
        *,
        active_check_in: CompanionCheckIn | None = None,
        privacy_active: bool = False,
        duration_minutes: int = 120,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("companionCheckInDialog")
        self.setWindowTitle("和 Lobuddy 说说现在")
        self.setModal(True)
        self.setFixedWidth(448)
        self._active_check_in = active_check_in
        self._privacy_active = privacy_active
        self._duration_minutes = duration_minutes
        self._build_ui()
        ThemeManager.instance().theme_changed.connect(self.refresh_theme)
        self.refresh_theme()

    def _build_ui(self) -> None:
        self.active_card: QWidget | None
        self.clear_button: QPushButton | None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(13)

        eyebrow = QLabel("COMPANION CHECK-IN", self)
        eyebrow.setObjectName("checkInEyebrow")
        root.addWidget(eyebrow)

        title = QLabel("现在的你，希望我怎么陪？", self)
        title.setObjectName("checkInTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "这是你主动告诉我的近况，不会根据应用活动猜测你的情绪。",
            self,
        )
        subtitle.setObjectName("checkInSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        if self._active_check_in is not None:
            self.active_card = QWidget(self)
            self.active_card.setObjectName("checkInActiveCard")
            active_layout = QHBoxLayout(self.active_card)
            active_layout.setContentsMargins(12, 9, 10, 9)
            active_layout.setSpacing(8)
            active_text = QLabel(
                "当前 · "
                f"{companion_mood_label(self._active_check_in.mood)} / "
                f"{companion_support_label(self._active_check_in.support_mode)}"
                f" · {self._active_check_in.expires_at:%H:%M} 前有效",
                self.active_card,
            )
            active_text.setObjectName("checkInActiveText")
            active_layout.addWidget(active_text, stretch=1)
            self.clear_button = QPushButton("清除", self.active_card)
            self.clear_button.setObjectName("checkInClearButton")
            self.clear_button.clicked.connect(self._clear_and_close)
            active_layout.addWidget(self.clear_button)
            root.addWidget(self.active_card)
        else:
            self.active_card = None
            self.clear_button = None

        self.mood_group = self._add_choice_section(
            root,
            "此刻更接近哪种状态？",
            COMPANION_MOOD_LABELS.items(),
            (
                self._active_check_in.mood.value
                if self._active_check_in is not None
                else CompanionMood.STEADY.value
            ),
        )
        self.energy_group = self._add_choice_section(
            root,
            "现在的精力",
            COMPANION_ENERGY_LABELS.items(),
            (
                self._active_check_in.energy.value
                if self._active_check_in is not None
                else CompanionEnergy.MEDIUM.value
            ),
        )
        self.support_group = self._add_choice_section(
            root,
            "希望我怎么陪",
            COMPANION_SUPPORT_LABELS.items(),
            (
                self._active_check_in.support_mode.value
                if self._active_check_in is not None
                else CompanionSupportMode.ENCOURAGE.value
            ),
        )

        privacy_text = (
            "隐私模式已开启：本次选择只保留在当前运行内，重启后不会恢复。"
            if self._privacy_active
            else (
                "只保留这三个选择和过期时间；不保存自由文本、窗口标题或屏幕画面。"
                f" {self._duration_minutes} 分钟后自动删除。"
            )
        )
        privacy_label = QLabel(privacy_text, self)
        privacy_label.setObjectName("checkInPrivacy")
        privacy_label.setWordWrap(True)
        root.addWidget(privacy_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()
        cancel_button = QPushButton("取消", self)
        cancel_button.setObjectName("checkInCancelButton")
        cancel_button.clicked.connect(self.reject)
        actions.addWidget(cancel_button)
        self.save_button = QPushButton("告诉 Lobuddy", self)
        self.save_button.setObjectName("checkInSaveButton")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.accept)
        actions.addWidget(self.save_button)
        root.addLayout(actions)

    def _add_choice_section(
        self,
        root: QVBoxLayout,
        title: str,
        choices: Iterable[tuple[Enum, str]],
        selected_value: str,
    ) -> QButtonGroup:
        label = QLabel(title, self)
        label.setObjectName("checkInSectionLabel")
        root.addWidget(label)

        row = QHBoxLayout()
        row.setSpacing(7)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for enum_value, text in choices:
            button = QPushButton(text, self)
            button.setObjectName("checkInChoice")
            button.setProperty("choiceValue", enum_value.value)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(enum_value.value == selected_value)
            group.addButton(button)
            row.addWidget(button, stretch=1)
        root.addLayout(row)
        return group

    def selected_values(
        self,
    ) -> tuple[CompanionMood, CompanionEnergy, CompanionSupportMode]:
        mood_button = self.mood_group.checkedButton()
        energy_button = self.energy_group.checkedButton()
        support_button = self.support_group.checkedButton()
        if mood_button is None or energy_button is None or support_button is None:
            raise ValueError("Companion Check-in requires one choice from each section")
        return (
            CompanionMood(mood_button.property("choiceValue")),
            CompanionEnergy(energy_button.property("choiceValue")),
            CompanionSupportMode(support_button.property("choiceValue")),
        )

    def _clear_and_close(self) -> None:
        self.clear_requested.emit()
        self.reject()

    def refresh_theme(self, _theme: object | None = None) -> None:
        theme = ThemeManager.instance().current
        self.setStyleSheet(
            f"""
            QDialog#companionCheckInDialog {{
                background: {theme.background};
            }}
            QLabel#checkInEyebrow {{
                color: {theme.primary};
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QLabel#checkInTitle {{
                color: {theme.text};
                font-size: 19px;
                font-weight: 750;
            }}
            QLabel#checkInSubtitle {{
                color: {theme.text_secondary};
                font-size: 11px;
            }}
            QLabel#checkInSectionLabel {{
                color: {theme.text};
                font-size: 11px;
                font-weight: 650;
                padding-top: 3px;
            }}
            QWidget#checkInActiveCard {{
                background: {theme.primary_soft};
                border: 1px solid {theme.border_focus};
                border-radius: {theme.radius_sm}px;
            }}
            QLabel#checkInActiveText {{
                color: {theme.text_secondary};
                font-size: 10px;
            }}
            QPushButton#checkInChoice {{
                min-height: 32px;
                padding: 0 8px;
                color: {theme.text_secondary};
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
                font-size: 10px;
                font-weight: 600;
            }}
            QPushButton#checkInChoice:hover {{
                color: {theme.text};
                border-color: {theme.border_focus};
            }}
            QPushButton#checkInChoice:checked {{
                color: {theme.primary};
                background: {theme.primary_soft};
                border-color: {theme.primary};
            }}
            QLabel#checkInPrivacy {{
                color: {theme.text_muted};
                background: {theme.surface_soft};
                border: 1px solid {theme.divider};
                border-radius: {theme.radius_sm}px;
                padding: 8px 10px;
                font-size: 9px;
            }}
            QPushButton#checkInSaveButton {{
                min-height: 34px;
                padding: 0 16px;
                color: {theme.on_primary};
                background: {theme.primary};
                border: 1px solid {theme.primary};
                border-radius: {theme.radius_sm}px;
                font-size: 11px;
                font-weight: 700;
            }}
            QPushButton#checkInSaveButton:hover {{
                background: {theme.primary_hover};
            }}
            QPushButton#checkInCancelButton,
            QPushButton#checkInClearButton {{
                min-height: 32px;
                padding: 0 12px;
                color: {theme.text_secondary};
                background: transparent;
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
                font-size: 10px;
            }}
            QPushButton#checkInCancelButton:hover,
            QPushButton#checkInClearButton:hover {{
                color: {theme.text};
                background: {theme.surface_soft};
            }}
            """
        )
