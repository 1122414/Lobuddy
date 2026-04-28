"""Main pet window for Lobuddy."""

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QPoint, QEasingCurve, QTimer, QSize
from PySide6.QtGui import QMouseEvent, QAction
from PySide6.QtWidgets import (
    QLabel, QMainWindow, QVBoxLayout, QWidget, QProgressBar, QHBoxLayout, QMenu,
    QGraphicsOpacityEffect,
)

from core.models.pet import TaskStatus
from core.models.appearance import get_appearance, save_appearance
from ui.asset_manager import AssetManager
from ui.quick_action_menu import QuickActionMenu
from ui.styles import PET_LEVEL_LABEL, PET_EXP_BAR, PET_TRANSPARENT, PET_STATUS_LABEL
from ui.theme import ThemeManager, ThemeColors, generate_context_menu_style


class PetWindow(QMainWindow):
    """Main frameless pet window with quick action menu."""

    task_requested = Signal()
    settings_requested = Signal()
    close_requested = Signal()
    chat_requested = Signal()
    pet_settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_pos = None
        self._press_pos = None
        self._asset_manager = AssetManager()
        self._force_close = False
        self._current_movie = None
        self._quick_menu = None
        self._click_count = 0
        self._click_cooldown = False
        self._settings = None
        self._init_ui()
        self._setup_window()
        self._setup_quick_menu()
        self._setup_context_menu()
        self._setup_clock()

    def _init_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        layout = QVBoxLayout(self.central_widget)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(4)

        self._speech_bubble = QLabel(self.central_widget)
        self._speech_bubble.setStyleSheet(
            "QLabel { background: #FFFFFF; color: #1F2937; "
            "border-radius: 12px; padding: 6px 12px; font-size: 12px; }"
        )
        self._speech_bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._speech_bubble.hide()

        self._speech_opacity = QGraphicsOpacityEffect(self._speech_bubble)
        self._speech_opacity.setOpacity(1.0)
        self._speech_bubble.setGraphicsEffect(self._speech_opacity)

        self._speech_triangle = QLabel(self._speech_bubble)
        self._speech_triangle.setStyleSheet(
            "QLabel { background: #FFFFFF; border: none; }"
        )
        self._speech_triangle.setFixedSize(12, 8)
        self._speech_triangle.hide()

        self._speech_timer = QTimer(self)
        self._speech_timer.setSingleShot(True)
        self._speech_timer.timeout.connect(self._hide_speech_bubble)

        self._speech_anim = QPropertyAnimation(self._speech_opacity, b"opacity")
        self._speech_anim.setDuration(500)

        self.mood_label = QLabel(self.central_widget)
        self.mood_label.setText("今天也要一起加油哦～")
        self.mood_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mood_label.setStyleSheet(
            "color: #8A6F5A; font-size: 10px; padding: 2px 6px; "
            "background: rgba(255,241,223,0.7); border-radius: 8px;"
        )
        self.mood_label.setWordWrap(True)
        self.mood_label.hide()
        layout.addWidget(self.mood_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._mood_messages = [
            "今天也要一起加油哦～",
            "我在这里陪你",
            "要不要和我聊聊？",
            "工作辛苦啦～",
            "今天天气怎么样？",
            "记得喝水哦",
        ]
        self._mood_index = 0
        self._mood_timer = QTimer(self)
        self._mood_timer.setInterval(12000)
        self._mood_timer.timeout.connect(self._cycle_mood)

        self.pet_label = QLabel(self.central_widget)
        self.pet_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pet_label.setFixedSize(120, 120)
        self.pet_label.setScaledContents(False)
        layout.addWidget(self.pet_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.name_label = QLabel(self.central_widget)
        self.name_label.setText("Lobuddy")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setStyleSheet(
            "color: #4A2E1F; font-size: 12px; font-weight: bold; "
            "padding: 2px 4px;"
        )
        layout.addWidget(self.name_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._bottom_row = QWidget(self.central_widget)
        self._bottom_row.setFixedHeight(18)
        bottom_layout = QHBoxLayout(self._bottom_row)
        bottom_layout.setContentsMargins(4, 0, 4, 0)
        bottom_layout.setSpacing(0)

        self._status_capsule = QWidget(self._bottom_row)
        exp_inner = QHBoxLayout(self._status_capsule)
        exp_inner.setContentsMargins(4, 0, 0, 0)
        exp_inner.setSpacing(4)

        self.level_label = QLabel("Lv1")
        self.level_label.setStyleSheet(
            "color: #1F2937; font-size: 9px; font-weight: bold;"
        )
        exp_inner.addWidget(self.level_label)

        self.exp_bar = QProgressBar()
        self.exp_bar.setMaximum(100)
        self.exp_bar.setValue(0)
        self.exp_bar.setTextVisible(False)
        self.exp_bar.setFixedHeight(6)
        self.exp_bar.setStyleSheet(
            "QProgressBar { border: none; border-radius: 3px; "
            "background-color: #F1D9C0; } "
            "QProgressBar::chunk { background-color: qlineargradient("
            "x1:0, y1:0, x2:1, y2:0, stop:0 #FF8A3D, stop:1 #FFD8B8); "
            "border-radius: 2px; }"
        )
        exp_inner.addWidget(self.exp_bar, stretch=1)
        bottom_layout.addWidget(self._status_capsule, 48)

        self._clock_label = QLabel(self._bottom_row)
        self._clock_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._clock_label.setStyleSheet(
            "color: #A0846C; font-size: 8px; padding: 0px 6px;"
        )
        self._clock_label.hide()
        bottom_layout.addWidget(self._clock_label, 48)

        layout.addWidget(self._bottom_row)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)

        self.status_label = QLabel(self.central_widget)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.hide()

        self._floating_label = QLabel(self.central_widget)
        self._floating_label.setStyleSheet(
            "color: #FFD700; font-size: 14px; font-weight: bold; background: transparent;"
        )
        self._floating_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._floating_label.hide()
        self._float_anim = QPropertyAnimation(self._floating_label, b"pos")
        self._float_anim.setDuration(1500)
        self._float_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._float_anim.finished.connect(self._floating_label.hide)

        self.set_pet_state(TaskStatus.CREATED)

    def _setup_window(self):
        app = self._asset_manager.appearance
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if getattr(app, "always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.central_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.central_widget.setStyleSheet(PET_TRANSPARENT)
        self.central_widget.setAutoFillBackground(False)
        self.pet_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.pet_label.setStyleSheet(PET_TRANSPARENT)
        self.pet_label.setAutoFillBackground(False)
        self._bottom_row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._bottom_row.setStyleSheet(PET_TRANSPARENT)
        self._bottom_row.setAutoFillBackground(False)

        self._apply_appearance()

    def _setup_quick_menu(self):
        self._quick_menu = QuickActionMenu(self)
        self._quick_menu.chat_clicked.connect(self.chat_requested.emit)
        self._quick_menu.pet_clicked.connect(self.pet_settings_requested.emit)
        self._quick_menu.settings_clicked.connect(self.settings_requested.emit)
        self._quick_menu.close_clicked.connect(self._hide_quick_menu)

    def _setup_context_menu(self):
        self._context_menu = QMenu(self)
        self._context_menu.setStyleSheet("QMenu { background: #FFFFFF; border: 1px solid #F3D9B1; border-radius: 8px; padding: 4px; } QMenu::item { padding: 8px 16px; border-radius: 6px; } QMenu::item:selected { background: #FFF7ED; color: #F97316; }")

        chat_action = QAction("Open Chat", self)
        chat_action.triggered.connect(self.chat_requested.emit)
        self._context_menu.addAction(chat_action)

        pet_action = QAction("Pet Settings", self)
        pet_action.triggered.connect(self.pet_settings_requested.emit)
        self._context_menu.addAction(pet_action)

        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.settings_requested.emit)
        self._context_menu.addAction(settings_action)

        self._context_menu.addSeparator()

        self._top_action = QAction("Always on Top", self)
        self._top_action.setCheckable(True)
        self._top_action.setChecked(getattr(self._asset_manager.appearance, "always_on_top", True))
        self._top_action.triggered.connect(self._toggle_always_on_top)
        self._context_menu.addAction(self._top_action)

        self._context_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close_requested.emit)
        self._context_menu.addAction(exit_action)

    def _hide_quick_menu(self):
        if self._quick_menu:
            self._quick_menu.hide()

    def _show_quick_menu(self):
        if self._quick_menu:
            if self._quick_menu.isVisible():
                self._quick_menu.hide()
            else:
                self._quick_menu.show_near(self.x(), self.y(), self.width(), self.height())

    def _toggle_always_on_top(self, checked: bool):
        flags = self.windowFlags()
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

        app = get_appearance()
        app.always_on_top = checked
        save_appearance(app)

    def _stop_current_movie(self):
        if self._current_movie is not None:
            try:
                self._current_movie.stop()
                self._current_movie.frameChanged.disconnect(self._on_movie_frame)
                self._current_movie.deleteLater()
            except RuntimeError:
                pass
            self._current_movie = None

    def set_pet_state(self, state: TaskStatus):
        self._stop_current_movie()
        self.pet_label.clear()

        target_size = self.pet_label.width()
        movie = self._asset_manager.get_pet_movie(state, target_size)
        if movie is not None:
            self._current_movie = movie
            movie.setParent(self.pet_label)
            movie.frameChanged.connect(self._on_movie_frame)
            movie.start()
            self._on_movie_frame()
        else:
            pixmap = self._asset_manager.get_pet_pixmap(state, target_size)
            self.pet_label.setPixmap(pixmap)

        self._update_status_label(state)

    def _update_status_label(self, state: TaskStatus):
        speech_map = {
            TaskStatus.IDLE: "What can I do for you?",
            TaskStatus.CREATED: "",
            TaskStatus.QUEUED: "",
            TaskStatus.RUNNING: "正在努力帮你做～",
            TaskStatus.SUCCESS: "做好啦！✨",
            TaskStatus.FAILED: "唔...好像遇到点问题",
            TaskStatus.CANCELLED: "",
        }
        text = speech_map.get(state, "")
        if text:
            self.show_speech_bubble(text)
        else:
            self._hide_speech_bubble()

    def show_speech_bubble(self, text: str, duration_ms: int = 3000):
        self._speech_timer.stop()
        self._speech_anim.stop()
        self._speech_opacity.setOpacity(1.0)
        self._speech_bubble.setText(text)
        self._speech_bubble.adjustSize()

        x = (self.central_widget.width() - self._speech_bubble.width()) // 2
        y = self.pet_label.y() - self._speech_bubble.height() - 8
        self._speech_bubble.move(x, max(0, y))

        tri_x = self._speech_bubble.width() // 2 - 6
        tri_y = self._speech_bubble.height() - 2
        self._speech_triangle.move(tri_x, tri_y)

        self.mood_label.hide()
        self._speech_triangle.show()
        self._speech_bubble.show()
        self._speech_timer.start(duration_ms)

    def _hide_speech_bubble(self):
        self._speech_timer.stop()
        self._speech_anim.setStartValue(1.0)
        self._speech_anim.setEndValue(0.0)
        self._speech_anim.finished.connect(self._speech_bubble.hide)
        self._speech_anim.finished.connect(self._restore_mood_after_speech)
        self._speech_anim.start()

    def _restore_mood_after_speech(self):
        self._speech_anim.finished.disconnect(self._speech_bubble.hide)
        self._speech_anim.finished.disconnect(self._restore_mood_after_speech)
        if self._mood_timer.isActive():
            self.mood_label.show()

    def _on_movie_frame(self):
        if self._current_movie is None:
            return
        self.pet_label.setPixmap(self._current_movie.currentPixmap())

    def reload_appearance(self):
        self._asset_manager.appearance = get_appearance()
        self._apply_appearance()
        self._apply_always_on_top()
        self.set_pet_state(TaskStatus.IDLE)

    def refresh_theme(self):
        """Re-apply theme styles when theme changes."""
        theme = ThemeManager.instance().current
        self._speech_bubble.setStyleSheet(
            f"QLabel {{ background: {theme.surface}; color: {theme.text}; "
            f"border-radius: 12px; padding: 6px 12px; font-size: 12px; }}"
        )
        self._speech_triangle.setStyleSheet(
            f"QLabel {{ background: {theme.surface}; border: none; }}"
        )
        self._context_menu.setStyleSheet(
            generate_context_menu_style(theme)
        )
        self.mood_label.setStyleSheet(
            f"color: {theme.text_muted}; font-size: 10px; padding: 2px 6px; "
            f"background: {theme.surface_soft}; border-radius: 8px;"
        )
        self.name_label.setStyleSheet(
            f"color: {theme.text}; font-size: 12px; font-weight: bold; padding: 2px 4px;"
        )
        self.level_label.setStyleSheet(
            f"color: {theme.text}; font-size: 9px; font-weight: bold;"
        )
        exp_bar_style = (
            f"QProgressBar {{ border: none; border-radius: 3px; "
            f"background-color: {theme.border}; }} "
            f"QProgressBar::chunk {{ background-color: qlineargradient("
            f"x1:0, y1:0, x2:1, y2:0, stop:0 {theme.primary}, stop:1 {theme.primary_soft}); "
            f"border-radius: 2px; }}"
        )
        self.exp_bar.setStyleSheet(exp_bar_style)

    def _apply_appearance(self):
        app = self._asset_manager.appearance
        base_size = 155
        scaled_size = int(base_size * app.scale)
        self.resize(scaled_size, scaled_size)
        pet_img_size = int(120 * app.scale)
        self.pet_label.setFixedSize(pet_img_size, pet_img_size)
        self.setWindowOpacity(app.opacity)
        self.move(app.position_x, app.position_y)

    def _apply_always_on_top(self):
        app = self._asset_manager.appearance
        flags = self.windowFlags()
        if getattr(app, "always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        if self._top_action:
            self._top_action.setChecked(getattr(app, "always_on_top", True))

    def update_exp_display(self, current_exp: int, required_exp: int, level: int):
        self.level_label.setText(f"Lv{level}")
        percentage = min(100, int((current_exp / required_exp) * 100)) if required_exp > 0 else 0
        self.exp_bar.setValue(percentage)

    def set_pet_name(self, name: str):
        self.name_label.setText(name)

    def set_mood(self, text: str):
        self.mood_label.setText(text)
        self.mood_label.setMinimumWidth(self.width() - 20)
        self.mood_label.show()

    def set_mood_enabled(self, enabled: bool):
        if enabled:
            self._mood_timer.start()
            self.mood_label.show()
        else:
            self._mood_timer.stop()
            self.mood_label.hide()

    def show_exp_gained(self, amount: int):
        self._floating_label.setText(f"+{amount} EXP")
        self._floating_label.adjustSize()
        start_pos = QPoint(
            (self.central_widget.width() - self._floating_label.width()) // 2,
            self.central_widget.height() // 2 - 20,
        )
        end_pos = QPoint(start_pos.x(), start_pos.y() - 60)
        self._floating_label.move(start_pos)
        self._floating_label.show()
        self._floating_label.raise_()
        self._float_anim.setStartValue(start_pos)
        self._float_anim.setEndValue(end_pos)
        self._float_anim.start()

    def _cycle_mood(self):
        self._mood_index = (self._mood_index + 1) % len(self._mood_messages)
        self.set_mood(self._mood_messages[self._mood_index])

    def start_breathing(self):
        pass

    def stop_breathing(self):
        if hasattr(self, '_breath_anim') and self._breath_anim:
            self._breath_anim.stop()
            self._breath_anim = None

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
            self._press_pos = self._drag_pos
            self._hide_quick_menu()
        elif event.button() == Qt.MouseButton.RightButton:
            self._context_menu.exec(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
            self._hide_quick_menu()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if hasattr(self, '_press_pos') and self._press_pos:
                delta = (event.globalPosition().toPoint() - self._press_pos).manhattanLength()
                if delta < 5:
                    self._show_quick_menu()
                    self._on_click_feedback()
                elif delta >= 5:
                    app = get_appearance()
                    app.position_x = self.x()
                    app.position_y = self.y()
                    save_appearance(app)
            self._drag_pos = None
            self._press_pos = None

    def closeEvent(self, event):
        self._stop_current_movie()
        if self._force_close:
            event.accept()
            return
        self.close_requested.emit()
        event.ignore()

    def force_close(self):
        self._force_close = True
        self.close()

    def set_settings(self, settings):
        self._settings = settings
        self._apply_clock_visibility()

    def _setup_clock(self):
        self._apply_clock_visibility()

    def _apply_clock_visibility(self):
        if self._settings and getattr(self._settings, 'pet_clock_enabled', False):
            refresh = getattr(self._settings, 'pet_clock_refresh_ms', 30000)
            show_sec = getattr(self._settings, 'pet_clock_show_seconds', False)
            if show_sec:
                refresh = 1000
            self._clock_timer.start(refresh)
            self._update_clock()
            self._clock_label.show()
        else:
            self._clock_timer.stop()
            self._clock_label.hide()

    def _update_clock(self):
        from core.time_format import format_clock_time, format_full_datetime
        from datetime import datetime
        now = datetime.now()
        show_sec = getattr(self._settings, 'pet_clock_show_seconds', False) if self._settings else False
        self._clock_label.setText(format_clock_time(now, show_sec))
        if self._settings and getattr(self._settings, 'pet_clock_hover_full_format', True):
            self._clock_label.setToolTip(format_full_datetime(now))

    def _on_click_feedback(self):
        if not self._settings or not getattr(self._settings, 'pet_click_feedback_enabled', True):
            return
        if self._click_cooldown:
            return
        self._click_cooldown = True
        cooldown = getattr(self._settings, 'pet_click_cooldown_ms', 350)
        QTimer.singleShot(cooldown, self._reset_click_cooldown)

        self._click_count += 1
        import random

        if hasattr(self, '_state_mgr'):
            self._state_mgr.on_pet_clicked()

        messages_str = getattr(self._settings, 'pet_click_messages', '我在呢～|摸摸头！')
        messages = [m.strip() for m in messages_str.split('|') if m.strip()]
        max_clicks = getattr(self._settings, 'pet_click_easter_egg_count', 5)
        if self._click_count >= max_clicks:
            egg = getattr(self._settings, 'pet_click_easter_egg_message', '别戳啦！')
            self.show_speech_bubble(egg, getattr(self._settings, 'pet_bubble_duration_ms', 2200))
            self._click_count = 0
        elif messages:
            msg = random.choice(messages)
            self.show_speech_bubble(msg, getattr(self._settings, 'pet_bubble_duration_ms', 2200))

    def _reset_click_cooldown(self):
        self._click_cooldown = False

    def set_pet_state_override(self, text: str):
        self.mood_label.hide()
        self.mood_label.setText(text)
        self.mood_label.show()
