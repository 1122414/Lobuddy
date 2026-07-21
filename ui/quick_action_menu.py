"""Quick action menu for Lobuddy pet widget."""

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui.theme import ThemeManager


class QuickActionMenu(QWidget):
    """Compact action sheet shown next to the desktop companion."""

    chat_clicked = Signal()
    pet_clicked = Signal()
    settings_clicked = Signal()
    close_clicked = Signal()
    focus_clicked = Signal()
    check_in_clicked = Signal()
    codex_pet_clicked = Signal()
    relationship_rhythm_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._app_filter = None
        self._init_ui()
        self._setup_window()
        self.refresh_theme()

    def _init_ui(self):
        self.setFixedSize(216, 359)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(0)

        self._card = QWidget(self)
        self._card.setObjectName("quickActionCard")
        root.addWidget(self._card)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(7)

        eyebrow = QLabel("LOBUDDY")
        eyebrow.setObjectName("quickActionEyebrow")
        layout.addWidget(eyebrow)

        title = QLabel("现在想做什么？")
        title.setObjectName("quickActionTitle")
        layout.addWidget(title)

        self.check_in_btn = self._create_btn("说说现在的状态", "告诉 Lobuddy 此刻需要怎样的陪伴")
        self.check_in_btn.setObjectName("quickActionCheckIn")
        self.check_in_btn.clicked.connect(self.check_in_clicked.emit)
        layout.addWidget(self.check_in_btn)

        self.relationship_rhythm_btn = self._create_btn(
            "我们的相处节奏",
            "查看我记得的偏好、关怀边界与成长证据",
        )
        self.relationship_rhythm_btn.setObjectName("quickActionRelationship")
        self.relationship_rhythm_btn.clicked.connect(self.relationship_rhythm_clicked.emit)
        layout.addWidget(self.relationship_rhythm_btn)

        self.chat_btn = self._create_btn("打开对话", "和 Lobuddy 聊聊或交代任务")
        self.chat_btn.clicked.connect(self.chat_clicked.emit)
        layout.addWidget(self.chat_btn)

        self.focus_btn = self._create_btn("开始专注陪伴", "启动专注计时")
        self.focus_btn.setCheckable(True)
        self.focus_btn.clicked.connect(self.focus_clicked.emit)
        layout.addWidget(self.focus_btn)

        self.codex_pet_btn = self._create_btn(
            "Codex 伙伴库",
            "从 codex-pets.net 领养伙伴并立即使用",
        )
        self.codex_pet_btn.setObjectName("quickActionCodexPets")
        self.codex_pet_btn.clicked.connect(self.codex_pet_clicked.emit)
        layout.addWidget(self.codex_pet_btn)

        self.pet_btn = self._create_btn("外观与名字", "调整桌宠形象")
        self.pet_btn.clicked.connect(self.pet_clicked.emit)
        layout.addWidget(self.pet_btn)

        footer = QHBoxLayout()
        footer.setSpacing(6)

        self.settings_btn = QPushButton("全部设置")
        self.settings_btn.setObjectName("quickActionSecondary")
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        footer.addWidget(self.settings_btn, stretch=1)

        self.close_btn = QPushButton("收起")
        self.close_btn.setObjectName("quickActionClose")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.close_clicked.emit)
        footer.addWidget(self.close_btn)
        layout.addLayout(footer)

    @staticmethod
    def _create_btn(text: str, tooltip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("quickActionPrimary")
        btn.setFixedHeight(34)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def set_focus_state(self, state: str):
        if state == "focusing":
            self.focus_btn.setText("暂停专注")
            self.focus_btn.setToolTip("暂停当前专注计时")
        elif state == "paused":
            self.focus_btn.setText("继续专注")
            self.focus_btn.setToolTip("继续当前专注计时")
        else:
            self.focus_btn.setText("开始专注陪伴")
            self.focus_btn.setToolTip("启动专注计时")

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

    def refresh_theme(self):
        theme = ThemeManager.instance().current
        self._card.setStyleSheet(
            f"""
            QWidget#quickActionCard {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_md}px;
            }}
            QLabel#quickActionEyebrow {{
                color: {theme.primary};
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QLabel#quickActionTitle {{
                color: {theme.text};
                font-size: 14px;
                font-weight: 700;
                padding-bottom: 2px;
            }}
            QPushButton#quickActionPrimary,
            QPushButton#quickActionRelationship,
            QPushButton#quickActionCodexPets {{
                background: {theme.surface_soft};
                color: {theme.text};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
                text-align: left;
                padding: 0 12px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton#quickActionPrimary:hover,
            QPushButton#quickActionRelationship:hover,
            QPushButton#quickActionCodexPets:hover,
            QPushButton#quickActionPrimary:checked {{
                background: {theme.primary_soft};
                border-color: {theme.primary};
            }}
            QPushButton#quickActionCodexPets {{
                color: {theme.primary};
                font-weight: 700;
            }}
            QPushButton#quickActionRelationship {{
                color: {theme.secondary};
                font-weight: 700;
            }}
            QPushButton#quickActionCheckIn {{
                min-height: 34px;
                color: {theme.primary};
                background: {theme.primary_soft};
                border: 1px solid {theme.border_focus};
                border-radius: {theme.radius_sm}px;
                text-align: left;
                padding: 0 12px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton#quickActionCheckIn:hover {{
                background: {theme.surface};
                border-color: {theme.primary};
            }}
            QPushButton#quickActionSecondary {{
                background: transparent;
                color: {theme.text_secondary};
                border: none;
                text-align: left;
                font-size: 11px;
            }}
            QPushButton#quickActionSecondary:hover {{
                color: {theme.primary};
            }}
            QPushButton#quickActionClose {{
                background: transparent;
                color: {theme.text_muted};
                border: none;
                font-size: 11px;
            }}
            QPushButton#quickActionClose:hover {{
                color: {theme.danger};
            }}
            """
        )

    def show_near(self, x: int, y: int, pet_width: int, pet_height: int):
        menu_x = x + (pet_width - self.width()) // 2
        menu_y = y + pet_height + 8
        screen = QApplication.screenAt(QPoint(x, y)) or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            menu_x = min(max(menu_x, available.left()), available.right() - self.width())
            if menu_y + self.height() > available.bottom():
                menu_y = y - self.height() - 8
            menu_y = min(max(menu_y, available.top()), available.bottom() - self.height())
        self.move(menu_x, menu_y)
        self._install_outside_click_filter()
        self.show()
        self.raise_()

    def _install_outside_click_filter(self):
        if self._app_filter is None:
            self._app_filter = _OutsideClickFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._app_filter)

    def _remove_outside_click_filter(self):
        app = QApplication.instance()
        if self._app_filter is not None and app is not None:
            app.removeEventFilter(self._app_filter)

    def hideEvent(self, event):
        self._remove_outside_click_filter()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._remove_outside_click_filter()
        self.setGraphicsEffect(None)
        super().closeEvent(event)


class _OutsideClickFilter(QObject):
    def __init__(self, menu: QuickActionMenu):
        super().__init__(menu)
        self._menu = menu

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            pos = event.globalPosition().toPoint()
            if not self._menu.geometry().contains(pos):
                self._menu.hide()
        return super().eventFilter(watched, event)
