"""Warm, explainable control surface for current-session data and permissions."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.data_control import (
    DataControlAction,
    DataControlCard,
    DataControlCenter,
    DataControlSnapshot,
)
from ui.styles import current_theme
from ui.theme import ThemeManager, generate_button_style

logger = logging.getLogger(__name__)


_CONFIRMATIONS = {
    DataControlAction.DISABLE_SESSION_PRIVACY: (
        "退出本次隐私模式？",
        "之后的请求将恢复常规记忆和学习设置；已经被隐私模式跳过的数据不会补写。",
    ),
    DataControlAction.REVOKE_COMPUTER_USE: (
        "立即撤销电脑操作授权？",
        "正在进行的计划会安全暂停，已有动作记录会保留，之后需要重新授权才能继续。",
    ),
    DataControlAction.CLEAR_SCREEN_REGIONS: (
        "删除临时屏幕选区？",
        "尚未完成的视觉提问可能无法继续，删除的像素不会保留。",
    ),
    DataControlAction.CLEAR_SESSION_CHAT: (
        "清除当前对话？",
        "本机保存的消息会被永久删除。结构化记忆是独立数据，不会被连带删除。",
    ),
}


class DataControlDialog(QDialog):
    """Render and execute the Data Control Interface for one current session."""

    settings_requested = Signal()
    memory_requested = Signal()
    skills_requested = Signal()
    chat_cleared = Signal(str)

    def __init__(
        self,
        control: DataControlCenter,
        session_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._control = control
        self._session_id = session_id
        self._snapshot: DataControlSnapshot | None = None
        self._theme = current_theme()
        self._init_ui()
        self._apply_theme(self._theme)
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self.refresh()

    def set_session(self, session_id: str) -> None:
        self._session_id = session_id
        self.refresh()

    def _init_ui(self) -> None:
        self.setWindowTitle("数据与权限")
        self.setMinimumSize(860, 660)
        self.resize(940, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(16)
        heading = QVBoxLayout()
        heading.setSpacing(3)
        title = QLabel("数据与权限")
        title.setObjectName("pageTitle")
        heading.addWidget(title)
        subtitle = QLabel("看清 Lobuddy 此刻能观察、保存、发送和执行什么，并随时收回。")
        subtitle.setObjectName("pageSubtitle")
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)

        self._session_chip = QLabel("当前对话")
        self._session_chip.setObjectName("sessionChip")
        header.addWidget(self._session_chip)
        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self._refresh_btn)
        root.addLayout(header)

        self._privacy_card = QWidget()
        self._privacy_card.setObjectName("privacyHero")
        privacy_layout = QHBoxLayout(self._privacy_card)
        privacy_layout.setContentsMargins(18, 15, 16, 15)
        privacy_layout.setSpacing(16)
        privacy_text = QVBoxLayout()
        privacy_text.setSpacing(4)
        self._privacy_title = QLabel()
        self._privacy_title.setObjectName("privacyTitle")
        privacy_text.addWidget(self._privacy_title)
        self._privacy_detail = QLabel()
        self._privacy_detail.setObjectName("privacyDetail")
        self._privacy_detail.setWordWrap(True)
        privacy_text.addWidget(self._privacy_detail)
        privacy_layout.addLayout(privacy_text, 1)
        self._privacy_btn = QPushButton()
        self._privacy_btn.clicked.connect(self._toggle_privacy)
        privacy_layout.addWidget(self._privacy_btn)
        root.addWidget(self._privacy_card)

        scroll = QScrollArea()
        scroll.setObjectName("controlScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._content = QWidget()
        self._content.setObjectName("controlContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 6, 0)
        self._content_layout.setSpacing(14)
        self._content_layout.addStretch(1)
        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        self._result_label = QLabel("状态按当前对话实时计算；这里不会展示你的内容。")
        self._result_label.setObjectName("resultLabel")
        self._result_label.setWordWrap(True)
        footer.addWidget(self._result_label, 1)
        close_btn = QPushButton("完成")
        close_btn.clicked.connect(self.close)
        footer.addWidget(close_btn)
        self._close_btn = close_btn
        root.addLayout(footer)

    def refresh(self) -> None:
        try:
            snapshot = self._control.snapshot(self._session_id)
        except Exception as exc:
            logger.warning("Data Control refresh failed: %s", exc, exc_info=True)
            self._result_label.setText(f"暂时无法读取数据状态：{exc}")
            return
        self._snapshot = snapshot
        self._privacy_title.setText(snapshot.headline)
        self._privacy_detail.setText(snapshot.detail)
        self._privacy_card.setProperty(
            "protected",
            "true" if snapshot.privacy_active else "false",
        )
        self._privacy_card.style().unpolish(self._privacy_card)
        self._privacy_card.style().polish(self._privacy_card)
        self._privacy_btn.setText("退出隐私模式" if snapshot.privacy_active else "开启本次隐私")
        self._render_cards(snapshot.cards)
        self._style_buttons()

    def _render_cards(self, cards: list[DataControlCard]) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        groups: dict[str, list[DataControlCard]] = {}
        for card in cards:
            groups.setdefault(card.group, []).append(card)

        for group_name, group_cards in groups.items():
            section = QWidget()
            section.setObjectName("controlSection")
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(8)
            section_title = QLabel(group_name)
            section_title.setObjectName("sectionTitle")
            section_layout.addWidget(section_title)

            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)
            for index, card in enumerate(group_cards):
                is_last_odd = len(group_cards) % 2 == 1 and index == len(group_cards) - 1
                grid.addWidget(
                    self._build_card(card),
                    index // 2,
                    index % 2,
                    1,
                    2 if is_last_odd else 1,
                )
            section_layout.addLayout(grid)
            self._content_layout.addWidget(section)
        self._content_layout.addStretch(1)

    def _build_card(self, card: DataControlCard) -> QWidget:
        widget = QWidget()
        widget.setObjectName("dataCard")
        widget.setProperty("tone", card.tone.value)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 13, 15, 13)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel(card.title)
        title.setObjectName("cardTitle")
        title_row.addWidget(title, 1)
        state = QLabel(card.state_label)
        state.setObjectName("stateChip")
        state.setProperty("tone", card.tone.value)
        title_row.addWidget(state)
        layout.addLayout(title_row)

        summary = QLabel(card.summary)
        summary.setObjectName("cardSummary")
        summary.setWordWrap(True)
        summary.setMinimumHeight(34)
        layout.addWidget(summary)

        for fact in card.facts:
            fact_row = QHBoxLayout()
            fact_row.setSpacing(8)
            label = QLabel(fact.label)
            label.setObjectName("factLabel")
            label.setFixedWidth(42)
            fact_row.addWidget(label)
            value = QLabel(fact.value)
            value.setObjectName("factValue")
            value.setWordWrap(True)
            fact_row.addWidget(value, 1)
            layout.addLayout(fact_row)

        layout.addStretch(1)
        if card.action is not None or card.secondary_route:
            actions = QHBoxLayout()
            actions.setSpacing(8)
            if card.secondary_route:
                secondary = QPushButton(card.secondary_label)
                secondary.setProperty("controlVariant", "secondary")
                secondary.clicked.connect(
                    lambda _checked=False, route=card.secondary_route: self._route(route)
                )
                actions.addWidget(secondary)
            actions.addStretch(1)
            if card.action is not None:
                action_btn = QPushButton(card.action_label)
                action_btn.setProperty(
                    "controlVariant",
                    "danger" if card.requires_confirmation else "primary",
                )
                action_btn.clicked.connect(
                    lambda _checked=False, action=card.action: self._execute(action)
                )
                actions.addWidget(action_btn)
            layout.addLayout(actions)
        return widget

    def _toggle_privacy(self) -> None:
        if self._snapshot is None:
            return
        action = (
            DataControlAction.DISABLE_SESSION_PRIVACY
            if self._snapshot.privacy_active
            else DataControlAction.ENABLE_SESSION_PRIVACY
        )
        self._execute(action)

    def _execute(self, action: DataControlAction) -> None:
        confirmation = _CONFIRMATIONS.get(action)
        if confirmation is not None:
            answer = QMessageBox.question(
                self,
                confirmation[0],
                confirmation[1],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            result = self._control.execute(action, self._session_id)
        except Exception as exc:
            logger.warning("Data Control action failed: %s", exc, exc_info=True)
            QMessageBox.warning(self, "操作未完成", str(exc))
            return
        self._snapshot = result.snapshot
        self._result_label.setText(result.message)
        if action == DataControlAction.CLEAR_SESSION_CHAT and result.changed_count:
            self.chat_cleared.emit(self._session_id)
        self.refresh()

    def _route(self, route: str) -> None:
        if route == "memory":
            self.memory_requested.emit()
        elif route == "skills":
            self.skills_requested.emit()
        else:
            self.settings_requested.emit()

    def _style_buttons(self) -> None:
        theme = self._theme
        for button in self.findChildren(QPushButton):
            variant = button.property("controlVariant")
            if variant == "danger":
                button.setStyleSheet(
                    f"""
                    QPushButton {{
                        background: transparent;
                        color: {theme.danger};
                        border: 1px solid {theme.danger};
                        border-radius: {theme.radius_sm}px;
                        padding: 7px 11px;
                        font-size: 12px;
                        font-weight: 700;
                    }}
                    QPushButton:hover {{ background: {theme.surface_soft}; }}
                    """
                )
            elif variant == "secondary":
                button.setStyleSheet(generate_button_style(theme, size="sm", variant="ghost"))
            elif button is self._privacy_btn or variant == "primary":
                button.setStyleSheet(generate_button_style(theme, size="sm", variant="primary"))
        self._refresh_btn.setStyleSheet(
            generate_button_style(theme, size="sm", variant="secondary")
        )
        self._close_btn.setStyleSheet(generate_button_style(theme, size="sm", variant="primary"))

    def _apply_theme(self, theme) -> None:
        self._theme = theme
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {theme.background};
                color: {theme.text};
                font-family: "Microsoft YaHei UI";
                font-size: 13px;
            }}
            QLabel#pageTitle {{
                color: {theme.text};
                font-size: 25px;
                font-weight: 700;
            }}
            QLabel#pageSubtitle, QLabel#resultLabel {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QLabel#sessionChip {{
                background: {theme.surface_soft};
                color: {theme.text_secondary};
                border: 1px solid {theme.border};
                border-radius: 10px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: 700;
            }}
            QWidget#privacyHero {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_lg}px;
            }}
            QWidget#privacyHero[protected="true"] {{
                background: {theme.surface_soft};
                border: 1px solid {theme.success};
            }}
            QLabel#privacyTitle {{
                color: {theme.text};
                font-size: 16px;
                font-weight: 700;
            }}
            QLabel#privacyDetail {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QScrollArea#controlScroll {{
                background: transparent;
                border: none;
            }}
            QWidget#controlContent {{
                background: transparent;
            }}
            QLabel#sectionTitle {{
                color: {theme.text_secondary};
                font-size: 12px;
                font-weight: 700;
                padding: 2px 2px;
            }}
            QWidget#dataCard {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_md}px;
            }}
            QWidget#dataCard[tone="attention"] {{
                border: 1px solid {theme.warning};
            }}
            QWidget#dataCard[tone="protected"] {{
                border: 1px solid {theme.success};
            }}
            QLabel#cardTitle {{
                color: {theme.text};
                font-size: 14px;
                font-weight: 700;
            }}
            QLabel#cardSummary {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QLabel#stateChip {{
                background: {theme.surface_soft};
                color: {theme.text_secondary};
                border-radius: 9px;
                padding: 4px 8px;
                font-size: 10px;
                font-weight: 700;
            }}
            QLabel#stateChip[tone="active"] {{
                color: {theme.info};
            }}
            QLabel#stateChip[tone="protected"] {{
                color: {theme.success};
            }}
            QLabel#stateChip[tone="attention"] {{
                color: {theme.warning};
            }}
            QLabel#factLabel {{
                color: {theme.text_muted};
                font-size: 10px;
                font-weight: 700;
            }}
            QLabel#factValue {{
                color: {theme.text_secondary};
                font-size: 11px;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 4px 0;
            }}
            QScrollBar::handle:vertical {{
                background: {theme.border};
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            """
        )
        self._style_buttons()
