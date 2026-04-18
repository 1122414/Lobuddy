"""Main pet window for Lobuddy."""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent, QMovie, QPixmap
from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget, QProgressBar, QHBoxLayout

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
        self._force_close = False
        self._current_movie = None
        self._init_ui()
        self._setup_window()

    def _init_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        layout = QVBoxLayout(self.central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.pet_label = QLabel(self.central_widget)
        self.pet_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.pet_label, stretch=1)

        self.exp_container = QWidget(self.central_widget)
        self.exp_container.setFixedHeight(20)
        self.exp_container.setMaximumWidth(100)
        layout.addWidget(self.exp_container, alignment=Qt.AlignmentFlag.AlignCenter)

        exp_layout = QHBoxLayout(self.exp_container)
        exp_layout.setContentsMargins(2, 2, 2, 2)
        exp_layout.setSpacing(4)

        self.level_label = QLabel("Lv1")
        self.level_label.setStyleSheet("color: white; font-size: 10px; font-weight: bold;")
        exp_layout.addWidget(self.level_label)

        self.exp_bar = QProgressBar()
        self.exp_bar.setMaximum(100)
        self.exp_bar.setValue(0)
        self.exp_bar.setTextVisible(False)
        self.exp_bar.setFixedHeight(12)
        self.exp_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555;
                border-radius: 6px;
                background-color: #2a2a2a;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4a9eff, stop:1 #7ec8ff);
                border-radius: 5px;
            }
        """)
        exp_layout.addWidget(self.exp_bar, stretch=1)

        self.set_pet_state(TaskStatus.CREATED)

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.central_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.central_widget.setStyleSheet("background: transparent; border: none;")
        self.central_widget.setAutoFillBackground(False)
        self.pet_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.pet_label.setStyleSheet("background: transparent; border: none;")
        self.pet_label.setAutoFillBackground(False)
        self.exp_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.exp_container.setStyleSheet("background: transparent; border: none;")
        self.exp_container.setAutoFillBackground(False)

        self.resize(155, 155)
        self.move(100, 100)

    def _stop_current_movie(self):
        if self._current_movie is not None:
            self._current_movie.stop()
            self._current_movie.frameChanged.disconnect(self._on_movie_frame)
            self._current_movie.deleteLater()
            self._current_movie = None

    def set_pet_state(self, state: TaskStatus):
        """Update pet display state."""
        self._stop_current_movie()
        self.pet_label.clear()

        movie = self._asset_manager.get_pet_movie(state)
        if movie is not None:
            self._current_movie = movie
            movie.setParent(self.pet_label)
            movie.frameChanged.connect(self._on_movie_frame)
            movie.start()
            self._on_movie_frame()
        else:
            pixmap = self._asset_manager.get_pet_pixmap(state)
            self.pet_label.setPixmap(pixmap)

    def _on_movie_frame(self):
        if self._current_movie is None:
            return
        self.pet_label.setPixmap(self._current_movie.currentPixmap())

    def update_exp_display(self, current_exp: int, required_exp: int, level: int):
        """Update EXP progress display."""
        self.level_label.setText(f"Lv{level}")
        percentage = min(100, int((current_exp / required_exp) * 100)) if required_exp > 0 else 0
        self.exp_bar.setValue(percentage)

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
        self._stop_current_movie()
        if self._force_close:
            event.accept()
            return
        self.close_requested.emit()
        event.ignore()

    def force_close(self):
        """Force close the window, bypassing the close interception."""
        self._force_close = True
        self.close()
