"""Task card panel for Lobuddy."""

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QTextEdit,
)

from core.models.task_card import TaskCardModel, TaskCardStatus
from ui.styles import TASKCARD_BG, TASKCARD_TITLE, TASKCARD_STATUS, TASKCARD_CLOSE_BTN, TASKCARD_ACTION_BTN


class TaskCardPanel(QWidget):
    """Floating task card panel showing task execution status."""

    continue_clicked = Signal(str)
    screenshot_clicked = Signal(str)
    open_web_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_card = None
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.timeout.connect(self.hide)
        self._init_ui()
        self._setup_window()

    def enterEvent(self, event):
        self._auto_close_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._current_card and self._current_card.status in ("success", "failed"):
            self._auto_close_timer.start(3000)
        super().leaveEvent(event)

    def _init_ui(self):
        self.setFixedSize(280, 160)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.title_label = QLabel("Task")
        self.title_label.setStyleSheet(TASKCARD_TITLE)
        header.addWidget(self.title_label)
        header.addStretch()

        self.close_btn = QPushButton("x")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setStyleSheet(TASKCARD_CLOSE_BTN)
        self.close_btn.clicked.connect(self.hide)
        header.addWidget(self.close_btn)
        layout.addLayout(header)

        self.status_label = QLabel("Running...")
        self.status_label.setStyleSheet(TASKCARD_STATUS)
        layout.addWidget(self.status_label)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("color: #1F2937; font-size: 12px;")
        layout.addWidget(self.result_label)

        self.exp_label = QLabel("")
        self.exp_label.setStyleSheet("color: #F97316; font-size: 13px; font-weight: bold;")
        layout.addWidget(self.exp_label)

        self.details_area = QTextEdit()
        self.details_area.setReadOnly(True)
        self.details_area.setStyleSheet(
            "QTextEdit { background: #FFF7ED; border: 1px solid #F3D9B1; border-radius: 8px; "
            "font-size: 11px; color: #6B7280; padding: 8px; }"
        )
        self.details_area.hide()
        layout.addWidget(self.details_area)

        btn_layout = QHBoxLayout()
        self.details_btn = QPushButton("查看详情")
        self.details_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #6B7280; border: none; font-size: 12px; }"
            "QPushButton:hover { color: #F97316; }"
        )
        self.details_btn.clicked.connect(self._toggle_details)
        btn_layout.addWidget(self.details_btn)
        btn_layout.addStretch()

        self.screenshot_btn = QPushButton("截图")
        self.screenshot_btn.setStyleSheet(TASKCARD_ACTION_BTN)
        self.screenshot_btn.clicked.connect(self._on_screenshot)
        self.screenshot_btn.hide()
        btn_layout.addWidget(self.screenshot_btn)

        self.open_web_btn = QPushButton("打开网页")
        self.open_web_btn.setStyleSheet(TASKCARD_ACTION_BTN)
        self.open_web_btn.clicked.connect(self._on_open_web)
        self.open_web_btn.hide()
        btn_layout.addWidget(self.open_web_btn)

        self.continue_btn = QPushButton("继续操作")
        self.continue_btn.setStyleSheet(
            "QPushButton { background: #F97316; color: white; border: none; border-radius: 8px; "
            "padding: 6px 12px; font-size: 12px; } "
            "QPushButton:hover { background: #EA580C; }"
        )
        self.continue_btn.clicked.connect(self._on_continue)
        btn_layout.addWidget(self.continue_btn)
        layout.addLayout(btn_layout)

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(TASKCARD_BG)

        # Shadow disabled to prevent UpdateLayeredWindowIndirect errors on Windows
        # with WA_TranslucentBackground frameless windows.

    def _toggle_details(self):
        if self.details_area.isVisible():
            self.details_area.hide()
            self.details_btn.setText("查看详情")
            self.setFixedHeight(180)
        else:
            self.details_area.show()
            self.details_btn.setText("收起详情")
            self.setFixedHeight(380)

    def _on_continue(self):
        if self._current_card:
            self.continue_clicked.emit(self._current_card.task_id)

    def _on_screenshot(self):
        if self._current_card:
            self.screenshot_clicked.emit(self._current_card.task_id)

    def _on_open_web(self):
        if self._current_card:
            self.open_web_clicked.emit(self._current_card.task_id)

    def show_card(self, card: TaskCardModel):
        self._auto_close_timer.stop()
        self._current_card = card
        self.title_label.setText(card.title)
        self._update_status(card.status)
        self.result_label.setText(card.short_result)
        self.exp_label.setText(f"+{card.exp_reward} EXP" if card.exp_reward > 0 else "")
        self.details_area.setText(card.details)
        self.details_area.hide()
        self.details_btn.setText("查看详情")
        self.details_btn.setVisible(bool(card.details.strip()))
        self._sync_action_buttons(card)
        self.setFixedHeight(180)
        self.show()
        self.raise_()
        if card.status in ("success", "failed"):
            self._auto_close_timer.start(8000)

    def _sync_action_buttons(self, card: TaskCardModel) -> None:
        actions = set(card.available_actions)
        self.screenshot_btn.setVisible("screenshot" in actions)
        self.open_web_btn.setVisible("open_web" in actions)

    def _update_status(self, status: TaskCardStatus):
        status_map = {
            "pending": ("⏳ Pending", "#6B7280"),
            "running": ("🏃 Running...", "#F97316"),
            "success": ("✅ Success", "#22C55E"),
            "warning": ("⚠️ Warning", "#F59E0B"),
            "failed": ("❌ Failed", "#EF4444"),
        }
        text, color = status_map.get(status, ("Unknown", "#6B7280"))
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")

    def show_at_corner(self):
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        margin = 20
        self.move(
            screen.width() - self.width() - margin,
            screen.height() - self.height() - margin,
        )

    def closeEvent(self, event):
        self.setGraphicsEffect(None)
        super().closeEvent(event)
