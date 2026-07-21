"""Task card panel for Lobuddy."""

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.models.task_card import TaskCardModel, TaskCardStatus
from ui.theme import ThemeManager


class TaskCardPanel(QWidget):
    """Floating, theme-aware summary for the task currently being handled."""

    continue_clicked = Signal(str)
    screenshot_clicked = Signal(str)
    open_web_clicked = Signal(str)
    retry_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_card = None
        self._status_color = ThemeManager.instance().current.primary
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.timeout.connect(self.hide)
        self._init_ui()
        self._setup_window()
        self.refresh_theme()

    def enterEvent(self, event):
        self._auto_close_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._current_card and self._current_card.status in (
            "success",
            "failed",
            "cancelled",
        ):
            self._auto_close_timer.start(3000)
        super().leaveEvent(event)

    def _init_ui(self):
        self.setFixedSize(312, 204)

        root = QVBoxLayout(self)
        root.setContentsMargins(7, 7, 7, 7)
        root.setSpacing(0)

        self._card = QWidget(self)
        self._card.setObjectName("taskCard")
        root.addWidget(self._card)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._eyebrow = QLabel("当前任务")
        self._eyebrow.setObjectName("taskCardEyebrow")
        header.addWidget(self._eyebrow)
        header.addStretch()

        self.close_btn = QPushButton("收起")
        self.close_btn.setObjectName("taskCardClose")
        self.close_btn.setFixedHeight(22)
        self.close_btn.clicked.connect(self.hide)
        header.addWidget(self.close_btn)
        layout.addLayout(header)

        self.title_label = QLabel("任务")
        self.title_label.setObjectName("taskCardTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.status_label = QLabel("●  准备中")
        self.status_label.setObjectName("taskCardStatus")
        layout.addWidget(self.status_label)

        self.steps_widget = QWidget(self._card)
        self.steps_widget.setObjectName("taskCardSteps")
        self.steps_layout = QVBoxLayout(self.steps_widget)
        self.steps_layout.setContentsMargins(0, 2, 0, 2)
        self.steps_layout.setSpacing(5)
        self.steps_widget.hide()
        layout.addWidget(self.steps_widget)

        self.result_label = QLabel("")
        self.result_label.setObjectName("taskCardResult")
        self.result_label.setWordWrap(True)
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.result_label, stretch=1)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("taskCardMeta")
        layout.addWidget(self.meta_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("taskCardProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(5)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.exp_label = QLabel("")
        self.exp_label.setObjectName("taskCardExp")
        layout.addWidget(self.exp_label)

        self.details_area = QTextEdit()
        self.details_area.setObjectName("taskCardDetails")
        self.details_area.setReadOnly(True)
        self.details_area.hide()
        layout.addWidget(self.details_area)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        self.details_btn = QPushButton("查看详情")
        self.details_btn.setObjectName("taskCardLink")
        self.details_btn.clicked.connect(self._toggle_details)
        btn_layout.addWidget(self.details_btn)
        btn_layout.addStretch()

        self.screenshot_btn = self._action_button("查看截图", self._on_screenshot)
        self.screenshot_btn.hide()
        btn_layout.addWidget(self.screenshot_btn)

        self.open_web_btn = self._action_button("打开网页", self._on_open_web)
        self.open_web_btn.hide()
        btn_layout.addWidget(self.open_web_btn)

        self.retry_btn = self._action_button(
            "查看并重试",
            self._on_retry,
            primary=True,
        )
        self.retry_btn.hide()
        btn_layout.addWidget(self.retry_btn)

        self.continue_btn = self._action_button("继续处理", self._on_continue, primary=True)
        btn_layout.addWidget(self.continue_btn)
        layout.addLayout(btn_layout)

    @staticmethod
    def _action_button(text: str, handler, *, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("taskCardPrimary" if primary else "taskCardAction")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(handler)
        return button

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
            QWidget#taskCard {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_md}px;
            }}
            QLabel#taskCardEyebrow {{
                color: {theme.text_muted};
                font-size: 10px;
                font-weight: 600;
            }}
            QLabel#taskCardTitle {{
                color: {theme.text};
                font-size: 15px;
                font-weight: 700;
            }}
            QLabel#taskCardStatus {{
                color: {self._status_color};
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#taskCardResult {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QWidget#taskCardSteps {{
                background: {theme.surface_soft};
                border: 1px solid {theme.divider};
                border-radius: {theme.radius_sm}px;
            }}
            QLabel#taskStepText {{
                color: {theme.text_secondary};
                font-size: 11px;
                font-weight: 600;
                background: transparent;
                border: none;
            }}
            QLabel#taskStepDetail,
            QLabel#taskStepWaiting,
            QLabel#taskStepDuration,
            QLabel#taskStepMore {{
                color: {theme.text_muted};
                font-size: 9px;
                background: transparent;
                border: none;
            }}
            QLabel#taskStepWaiting {{
                color: {theme.warning};
                font-weight: 600;
            }}
            QLabel#taskStepCritical {{
                background: {theme.primary_soft};
                color: {theme.primary_active};
                border: 1px solid {theme.border_focus};
                border-radius: 7px;
                padding: 1px 5px;
                font-size: 8px;
                font-weight: 700;
            }}
            QLabel#taskStageSummary {{
                color: {theme.text_secondary};
                font-size: 9px;
                font-weight: 600;
                background: transparent;
                border: none;
                padding: 1px 8px 3px 8px;
            }}
            QLabel#taskCardExp {{
                color: {theme.primary};
                font-size: 11px;
                font-weight: 700;
            }}
            QLabel#taskCardMeta {{
                color: {theme.text_muted};
                font-size: 10px;
                font-weight: 600;
            }}
            QProgressBar#taskCardProgress {{
                background: {theme.surface_soft};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar#taskCardProgress::chunk {{
                background: {theme.primary};
                border-radius: 2px;
            }}
            QPushButton#taskCardClose,
            QPushButton#taskCardLink {{
                background: transparent;
                color: {theme.text_muted};
                border: none;
                font-size: 11px;
            }}
            QPushButton#taskCardClose:hover,
            QPushButton#taskCardLink:hover {{
                color: {theme.primary};
            }}
            QPushButton#taskCardAction {{
                background: {theme.surface_soft};
                color: {theme.text_secondary};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
                padding: 5px 9px;
                font-size: 11px;
            }}
            QPushButton#taskCardPrimary {{
                background: {theme.primary};
                color: {theme.primary_text};
                border: none;
                border-radius: {theme.radius_sm}px;
                padding: 6px 11px;
                font-size: 11px;
                font-weight: 700;
            }}
            QPushButton#taskCardAction:hover,
            QPushButton#taskCardPrimary:hover {{
                background: {theme.primary_soft};
                color: {theme.text};
            }}
            QTextEdit#taskCardDetails {{
                background: {theme.surface_soft};
                color: {theme.text_secondary};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
                padding: 8px;
                font-size: 11px;
            }}
            """
        )
        if self._current_card is not None and self._current_card.steps:
            self._render_steps(self._current_card)

    def _toggle_details(self):
        if self.details_area.isVisible():
            self.details_area.hide()
            self.details_btn.setText("查看详情")
            self.setFixedHeight(self._collapsed_height())
        else:
            self.details_area.show()
            self.details_btn.setText("收起详情")
            self.setFixedHeight(self._collapsed_height() + 188)

    def _on_continue(self):
        if self._current_card:
            self.continue_clicked.emit(self._current_card.task_id)

    def _on_screenshot(self):
        if self._current_card:
            self.screenshot_clicked.emit(self._current_card.task_id)

    def _on_open_web(self):
        if self._current_card:
            self.open_web_clicked.emit(self._current_card.task_id)

    def _on_retry(self):
        if self._current_card:
            self.retry_clicked.emit(self._current_card.task_id)

    def show_card(self, card: TaskCardModel):
        self._auto_close_timer.stop()
        self._current_card = card
        self.title_label.setText(card.title)
        self._update_status(card.status)
        self.result_label.setText(card.short_result)
        self.meta_label.setText(card.meta_text)
        self.meta_label.setVisible(bool(card.meta_text))
        progress = max(0.0, min(1.0, card.progress))
        self.progress_bar.setValue(round(progress * 100))
        self.progress_bar.setVisible(
            card.status in {"pending", "running", "warning"} and progress > 0
        )
        self.exp_label.setText(f"成长值 +{card.exp_reward}" if card.exp_reward > 0 else "")
        self.details_area.setText(card.details)
        self.details_area.hide()
        self.details_btn.setText("查看详情")
        self.details_btn.setVisible(bool(card.details.strip()))
        self._sync_action_buttons(card)
        self.setFixedHeight(self._collapsed_height())
        self.show()
        self.raise_()
        if card.status in ("success", "failed", "cancelled"):
            self._auto_close_timer.start(8000)

    def _render_steps(self, card: TaskCardModel) -> None:
        while self.steps_layout.count():
            item = self.steps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not card.steps:
            self.steps_widget.hide()
            return

        theme = ThemeManager.instance().current
        if card.stage_summary:
            summary = QLabel(card.stage_summary)
            summary.setObjectName("taskStageSummary")
            summary.setWordWrap(True)
            self.steps_layout.addWidget(summary)
        status_colors = {
            "pending": theme.text_muted,
            "running": theme.primary,
            "success": theme.success,
            "warning": theme.warning,
            "failed": theme.danger,
            "cancelled": theme.warning,
        }
        visible_steps = card.steps[-4:]
        for step in visible_steps:
            row = QWidget(self.steps_widget)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 4, 8, 4)
            row_layout.setSpacing(7)

            marker = QLabel("●")
            marker.setFixedWidth(10)
            marker.setStyleSheet(
                f"color: {status_colors.get(step.status, theme.text_muted)}; "
                "font-size: 9px; background: transparent; border: none;"
            )
            row_layout.addWidget(marker, alignment=Qt.AlignmentFlag.AlignTop)

            copy = QVBoxLayout()
            copy.setContentsMargins(0, 0, 0, 0)
            copy.setSpacing(1)
            text = QLabel(step.text)
            text.setObjectName("taskStepText")
            text.setWordWrap(True)
            copy.addWidget(text)
            if step.detail:
                detail = QLabel(step.detail)
                detail.setObjectName("taskStepDetail")
                detail.setWordWrap(True)
                copy.addWidget(detail)
            if step.waiting_text:
                waiting = QLabel(step.waiting_text)
                waiting.setObjectName("taskStepWaiting")
                waiting.setWordWrap(True)
                copy.addWidget(waiting)
            row_layout.addLayout(copy, stretch=1)

            stage_meta = QVBoxLayout()
            stage_meta.setContentsMargins(0, 0, 0, 0)
            stage_meta.setSpacing(3)
            stage_meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            if step.critical:
                critical = QLabel("关键")
                critical.setObjectName("taskStepCritical")
                critical.setAlignment(Qt.AlignmentFlag.AlignCenter)
                stage_meta.addWidget(critical)
            if step.duration_text:
                duration = QLabel(step.duration_text)
                duration.setObjectName("taskStepDuration")
                duration.setAlignment(Qt.AlignmentFlag.AlignRight)
                stage_meta.addWidget(duration)
            row_layout.addLayout(stage_meta)
            self.steps_layout.addWidget(row)

        if len(card.steps) > len(visible_steps):
            more = QLabel(f"还有 {len(card.steps) - len(visible_steps)} 个较早步骤")
            more.setObjectName("taskStepMore")
            more.setContentsMargins(8, 0, 8, 4)
            self.steps_layout.addWidget(more)
        self.steps_widget.show()

    def _collapsed_height(self) -> int:
        if self._current_card is None:
            return 204
        run_meta_height = 0
        if self._current_card.meta_text:
            run_meta_height += 16
        if (
            self._current_card.status in {"pending", "running", "warning"}
            and self._current_card.progress > 0
        ):
            run_meta_height += 9
        if not self._current_card.steps:
            return 204 + run_meta_height
        visible_count = min(4, len(self._current_card.steps))
        detail_count = sum(bool(step.detail) for step in self._current_card.steps[-visible_count:])
        waiting_count = sum(
            bool(step.waiting_text) for step in self._current_card.steps[-visible_count:]
        )
        overflow = len(self._current_card.steps) > visible_count
        return min(
            390,
            218
            + run_meta_height
            + (20 if self._current_card.stage_summary else 0)
            + visible_count * 27
            + (detail_count + waiting_count) * 7
            + (14 if overflow else 0),
        )

    def _sync_action_buttons(self, card: TaskCardModel) -> None:
        actions = set(card.available_actions)
        self.screenshot_btn.setVisible("screenshot" in actions)
        self.open_web_btn.setVisible("open_web" in actions)
        self.retry_btn.setVisible("retry" in actions)
        self.continue_btn.setVisible("retry" not in actions)

    def _update_status(self, status: TaskCardStatus):
        theme = ThemeManager.instance().current
        status_map = {
            "pending": ("●  等待开始", theme.text_muted),
            "running": ("●  正在替你处理", theme.primary),
            "success": ("●  已完成", theme.success),
            "warning": ("●  需要你确认", theme.warning),
            "failed": ("●  没能完成", theme.danger),
            "cancelled": ("●  已安全暂停", theme.warning),
        }
        text, self._status_color = status_map.get(status, ("●  状态未知", theme.text_muted))
        self.status_label.setText(text)
        self.refresh_theme()

    def show_at_corner(self):
        from PySide6.QtWidgets import QApplication

        screen = QApplication.primaryScreen().availableGeometry()
        margin = 20
        self.move(
            screen.right() - self.width() - margin,
            screen.bottom() - self.height() - margin,
        )

    def closeEvent(self, event):
        self.setGraphicsEffect(None)
        super().closeEvent(event)
