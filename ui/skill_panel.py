"""Skill panel - displays available skills with examples."""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.skills.skill_registry import SkillDefinition, SkillRegistry
from ui.theme import ThemeManager, ThemeColors


def _card_style(t: ThemeColors) -> str:
    return (
        f"QFrame {{ background: {t.surface}; border: 1px solid {t.border}; "
        f"border-radius: {t.radius_md}px; padding: 12px; margin: 4px; }}"
        f"QFrame:hover {{ border-color: {t.primary}; }}"
    )


def _example_btn_style(t: ThemeColors) -> str:
    return (
        f"QPushButton {{ background: {t.surface_soft}; border: 1px solid {t.border}; "
        f"border-radius: {t.radius_sm}px; padding: 6px 12px; text-align: left; "
        f"color: {t.text}; font-size: 11px; }}"
        f"QPushButton:hover {{ background: {t.primary}; color: {t.primary_text}; }}"
    )


def _close_btn_style(t: ThemeColors) -> str:
    return (
        f"QPushButton {{ background: {t.surface_soft}; color: {t.text}; "
        f"border: 1px solid {t.border}; border-radius: {t.radius_sm}px; "
        f"font-size: 13px; }}"
        f"QPushButton:hover {{ background: {t.border}; }}"
    )


def _badge_style(t: ThemeColors) -> str:
    return (
        f"QLabel {{ background: {t.primary_soft}; color: {t.primary}; "
        f"padding: 2px 8px; border-radius: {t.radius_sm - 4}px; font-size: 10px; }}"
    )


def _scroll_style(t: ThemeColors) -> str:
    return (
        f"QScrollArea {{ border: none; background: transparent; }}"
        f"QScrollBar:vertical {{ background: {t.border}; width: 8px; }}"
        f"QScrollBar::handle:vertical {{ background: {t.primary}; border-radius: 4px; }}"
    )


class SkillCard(QFrame):
    """A single skill card widget."""

    example_clicked = Signal(str)

    def __init__(
        self,
        skill: SkillDefinition,
        settings,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._skill = skill
        self._settings = settings
        self._init_ui()

    def _init_ui(self):
        t = ThemeManager.instance().current
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(_card_style(t))

        self._collapsed = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header = QHBoxLayout()
        icon_label = QLabel(self._skill.icon)
        icon_label.setFont(QFont("Segoe UI Emoji", 16))
        header.addWidget(icon_label)

        name_label = QLabel(self._skill.name)
        name_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        name_label.setStyleSheet(f"color: {t.text};")
        header.addWidget(name_label)

        header.addStretch()

        if self._settings.skill_panel_show_permission_badge:
            if self._skill.requires_model == "multimodal":
                badge = QLabel("需要多模态模型")
                badge.setStyleSheet(_badge_style(t))
                header.addWidget(badge)

        self._toggle_btn = QLabel("\u25bc")
        self._toggle_btn.setFont(QFont("Segoe UI Emoji", 14))
        self._toggle_btn.setStyleSheet(f"color: {t.text_muted};")
        header.addWidget(self._toggle_btn)

        layout.addLayout(header)

        self._detail_widget = QWidget()
        self._detail_widget.setVisible(False)
        detail_layout = QVBoxLayout(self._detail_widget)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(6)

        desc_label = QLabel(self._skill.description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"color: {t.text_secondary}; font-size: 12px;")
        detail_layout.addWidget(desc_label)

        if self._settings.skill_panel_show_examples and self._skill.examples:
            examples_label = QLabel("示例：")
            examples_label.setStyleSheet(f"color: {t.text_muted}; font-size: 11px;")
            detail_layout.addWidget(examples_label)

            for example in self._skill.examples[:3]:
                btn = QPushButton(f'  "{example}"')
                btn.setStyleSheet(_example_btn_style(t))
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(
                    lambda checked, ex=example: self.example_clicked.emit(ex)
                )
                detail_layout.addWidget(btn)

        layout.addWidget(self._detail_widget)

        self.mousePressEvent = lambda e: self._toggle()

    def _toggle(self):
        self._collapsed = not self._collapsed
        self._detail_widget.setVisible(not self._collapsed)
        if self._collapsed:
            self._toggle_btn.setText("\u25bc")
        else:
            self._toggle_btn.setText("\u25b2")


class SkillPanel(QDialog):
    """Skill panel dialog."""

    example_selected = Signal(str)

    def __init__(
        self,
        registry: SkillRegistry,
        settings,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._registry = registry
        self._settings = settings
        self._init_ui()

    def _init_ui(self):
        t = ThemeManager.instance().current
        self.setWindowTitle("技能面板")
        self.setMinimumWidth(400)
        self.setMinimumHeight(500)

        self.setStyleSheet(f"QDialog {{ background: {t.background}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("\U0001f3af 我能做什么？")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {t.primary};")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(_scroll_style(t))

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(8)

        for skill in self._registry.get_enabled():
            if self._registry.is_available(skill.id, self._settings):
                card = SkillCard(skill, self._settings)
                card.example_clicked.connect(self._on_example_clicked)
                container_layout.addWidget(card)

        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        close_btn = QPushButton("关闭")
        close_btn.setFixedSize(100, 36)
        close_btn.setStyleSheet(_close_btn_style(t))
        close_btn.clicked.connect(self.close)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _on_example_clicked(self, example: str):
        self.example_selected.emit(example)
        if self._settings.skill_panel_click_to_fill_input:
            self.close()
