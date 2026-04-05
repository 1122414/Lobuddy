"""Main pet window for Lobuddy."""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget

from core.models.pet import TaskStatus
from ui.asset_manager import AssetManager


class PetWindow(QMainWindow):
    """Main frameless pet window."""

    task_requested = Signal()
    settings_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_pos = None
        self._asset_manager = AssetManager()
        self._init_ui()
        self._setup_window()

    def _init_ui(self):
        """Initialize UI components."""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        layout = QVBoxLayout(self.central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.pet_label = QLabel(self.central_widget)
        self.pet_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.pet_label)

        self.set_pet_state(TaskStatus.CREATED)

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self.resize(128, 128)
        self.move(100, 100)

    def set_pet_state(self, state: TaskStatus):
        """Update pet display state."""
        pixmap = self._asset_manager.get_pet_pixmap(state)
        self.pet_label.setPixmap(pixmap)

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press for drag and click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        elif event.button() == Qt.MouseButton.RightButton:
            self.settings_requested.emit()

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move for dragging."""
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release for click detection."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._drag_pos:
                delta = (event.globalPosition().toPoint() - self._drag_pos).manhattanLength()
                if delta < 5:
                    self.task_requested.emit()
            self._drag_pos = None

    def closeEvent(self, event):
        """Handle close event."""
        self.close_requested.emit()
        event.ignore()
