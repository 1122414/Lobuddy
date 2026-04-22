"""Result popup for Lobuddy."""

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)
from ui.styles import (
    POPUP_STATUS_DEFAULT,
    POPUP_STATUS_SUCCESS,
    POPUP_STATUS_FAILURE,
    POPUP_FRAME,
)


class ResultPopup(QFrame):
    """Auto-closing result notification popup."""

    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_close_timer = None
        self._close_duration = 5000
        self._init_ui()
        self._setup_window()

    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        header_layout = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setStyleSheet(POPUP_STATUS_DEFAULT)
        header_layout.addWidget(self.status_label)
        header_layout.addStretch()

        self.close_button = QPushButton("x")
        self.close_button.setFixedSize(20, 20)
        self.close_button.clicked.connect(self._on_close)
        header_layout.addWidget(self.close_button)

        layout.addLayout(header_layout)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setMaximumWidth(300)
        layout.addWidget(self.message_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(self._close_duration)
        self.progress_bar.setValue(self._close_duration)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumHeight(3)
        layout.addWidget(self.progress_bar)

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
        )
        self.setStyleSheet(POPUP_FRAME)
        self.setMinimumWidth(250)

    def show_result(self, success: bool, summary: str, duration_ms: int = 5000):
        """Show result popup with auto-close."""
        self._close_duration = duration_ms

        if success:
            self.status_label.setText("[OK] Success")
            self.status_label.setStyleSheet(POPUP_STATUS_SUCCESS)
        else:
            self.status_label.setText("[FAIL] Error")
            self.status_label.setStyleSheet(POPUP_STATUS_FAILURE)

        self.message_label.setText(summary)
        self.progress_bar.setMaximum(duration_ms)
        self.progress_bar.setValue(duration_ms)

        self.show()
        self._start_auto_close()

    def _start_auto_close(self):
        """Start auto-close timer with progress."""
        if self._auto_close_timer is None:
            self._auto_close_timer = QTimer(self)
            self._auto_close_timer.timeout.connect(self._update_progress)
        self._auto_close_timer.stop()
        self._auto_close_timer.start(50)
        self._remaining_time = self._close_duration

    def _update_progress(self):
        """Update progress bar and check for close."""
        self._remaining_time -= 50
        self.progress_bar.setValue(self._remaining_time)

        if self._remaining_time <= 0:
            self._auto_close_timer.stop()
            self._on_close()

    def _on_close(self):
        """Handle close action."""
        if self._auto_close_timer:
            self._auto_close_timer.stop()
        self.hide()
        self.closed.emit()

    def set_position_near(self, x: int, y: int):
        """Position popup near given coordinates."""
        self.adjustSize()
        popup_x = x + 140
        popup_y = y + 50
        self.move(popup_x, popup_y)

    def mousePressEvent(self, event):
        """Handle mouse press to dismiss."""
        self._on_close()
