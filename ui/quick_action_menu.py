"""Quick action menu for Lobuddy pet widget."""

from PySide6.QtCore import Qt, Signal, QObject, QEvent
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QGraphicsDropShadowEffect, QApplication

from ui.styles import QUICK_MENU_BG, QUICK_MENU_BTN, QUICK_MENU_BTN_CLOSE


class QuickActionMenu(QWidget):
    """Floating quick action menu around the pet."""

    chat_clicked = Signal()
    pet_clicked = Signal()
    settings_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._setup_window()
        self._app_filter = None

    def _init_ui(self):
        self.setFixedSize(140, 180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        top_layout = QHBoxLayout()
        top_layout.addStretch()
        self.chat_btn = self._create_btn("💬", "Chat")
        self.chat_btn.clicked.connect(self.chat_clicked.emit)
        top_layout.addWidget(self.chat_btn)
        top_layout.addStretch()
        layout.addLayout(top_layout)

        mid_layout = QHBoxLayout()
        mid_layout.setSpacing(12)
        self.pet_btn = self._create_btn("🐱", "Pet")
        self.pet_btn.clicked.connect(self.pet_clicked.emit)
        mid_layout.addStretch()
        mid_layout.addWidget(self.pet_btn)
        mid_layout.addWidget(self._create_spacer())
        self.settings_btn = self._create_btn("⚙️", "Settings")
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        mid_layout.addWidget(self.settings_btn)
        mid_layout.addStretch()
        layout.addLayout(mid_layout)

        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        self.close_btn = self._create_btn("✕", "Close", is_close=True)
        self.close_btn.clicked.connect(self.close_clicked.emit)
        bottom_layout.addWidget(self.close_btn)
        bottom_layout.addStretch()
        layout.addLayout(bottom_layout)

        layout.addStretch()

    def _create_btn(self, icon: str, tooltip: str, is_close: bool = False) -> QPushButton:
        btn = QPushButton(icon)
        btn.setFixedSize(40, 40)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if is_close:
            btn.setStyleSheet(QUICK_MENU_BTN_CLOSE)
        else:
            btn.setStyleSheet(QUICK_MENU_BTN)
        return btn

    def _create_spacer(self) -> QWidget:
        spacer = QWidget()
        spacer.setFixedSize(40, 40)
        return spacer

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(QUICK_MENU_BG)

        # Shadow disabled to prevent UpdateLayeredWindowIndirect errors on Windows
        # with WA_TranslucentBackground frameless windows. The border-radius
        # and background styling provide sufficient visual depth.

    def show_near(self, x: int, y: int, pet_width: int, pet_height: int):
        menu_x = x + (pet_width - self.width()) // 2
        menu_y = y + pet_height + 8
        self.move(menu_x, menu_y)
        self._install_outside_click_filter()
        self.show()
        self.raise_()

    def _install_outside_click_filter(self):
        if self._app_filter is None:
            self._app_filter = _OutsideClickFilter(self)
        QApplication.instance().installEventFilter(self._app_filter)

    def _remove_outside_click_filter(self):
        if self._app_filter is not None:
            QApplication.instance().removeEventFilter(self._app_filter)

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
