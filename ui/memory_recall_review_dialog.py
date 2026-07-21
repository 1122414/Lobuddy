"""Review explicit feedback for memories used by one Task Run."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.memory.memory_control_service import MemoryControlService, MemoryRecallReview
from core.memory.memory_schema import MemoryRecallFeedback
from ui.styles import current_theme
from ui.theme import ThemeManager, generate_button_style


_FEEDBACK_LABELS = {
    MemoryRecallFeedback.UNREVIEWED: "等待反馈",
    MemoryRecallFeedback.HELPFUL: "有帮助",
    MemoryRecallFeedback.NOT_RELEVANT: "这次不相关",
    MemoryRecallFeedback.INACCURATE: "内容不对",
}


class MemoryRecallReviewDialog(QDialog):
    """Content-aware review over content-free recall receipts."""

    memory_changed = Signal(str)

    def __init__(
        self,
        control: MemoryControlService,
        task_id: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._control = control
        self._task_id = task_id
        self._reviews: list[MemoryRecallReview] = []
        self._current: MemoryRecallReview | None = None
        self.setWindowTitle("这次记忆有帮到你吗？")
        self.setModal(False)
        self.resize(780, 570)
        self.setMinimumSize(680, 500)
        self._init_ui()
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self._apply_theme(current_theme())
        self.refresh()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title_row = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(3)
        title = QLabel("这次记忆有帮到你吗？")
        title.setObjectName("pageTitle")
        subtitle = QLabel("反馈只关联这次 Task Run，不保存你的提问或助手回答。")
        subtitle.setObjectName("pageSubtitle")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        title_row.addLayout(title_column, 1)
        privacy = QLabel("本地 · 内容最小化")
        privacy.setObjectName("privacyBadge")
        title_row.addWidget(privacy, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(title_row)

        hint = QLabel("“这次不相关”只记录反馈，不会改写记忆；“内容不对”会暂停该记忆，" "等待你在记忆档案中校正或确认。")
        hint.setObjectName("hintText")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["这次参考的记忆", "调用原因", "你的反馈"])
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self._table, 2)

        detail = QFrame()
        detail.setObjectName("detailCard")
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(16, 14, 16, 14)
        detail_layout.setSpacing(7)
        self._detail_title = QLabel("选择一条记忆")
        self._detail_title.setObjectName("detailTitle")
        detail_layout.addWidget(self._detail_title)
        self._detail_content = QLabel("查看它为什么被调用，并留下这一次的反馈。")
        self._detail_content.setObjectName("detailContent")
        self._detail_content.setWordWrap(True)
        self._detail_content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_layout.addWidget(self._detail_content)
        self._detail_reason = QLabel()
        self._detail_reason.setObjectName("detailReason")
        self._detail_reason.setWordWrap(True)
        detail_layout.addWidget(self._detail_reason)

        feedback_row = QHBoxLayout()
        feedback_row.setSpacing(8)
        self._helpful_btn = QPushButton("有帮助")
        self._helpful_btn.clicked.connect(
            lambda: self._submit_feedback(MemoryRecallFeedback.HELPFUL)
        )
        feedback_row.addWidget(self._helpful_btn)
        self._irrelevant_btn = QPushButton("这次不相关")
        self._irrelevant_btn.clicked.connect(
            lambda: self._submit_feedback(MemoryRecallFeedback.NOT_RELEVANT)
        )
        feedback_row.addWidget(self._irrelevant_btn)
        self._inaccurate_btn = QPushButton("内容不对")
        self._inaccurate_btn.clicked.connect(
            lambda: self._submit_feedback(MemoryRecallFeedback.INACCURATE)
        )
        feedback_row.addWidget(self._inaccurate_btn)
        feedback_row.addStretch(1)
        self._feedback_status = QLabel()
        self._feedback_status.setObjectName("feedbackStatus")
        feedback_row.addWidget(self._feedback_status)
        detail_layout.addLayout(feedback_row)
        root.addWidget(detail)

        footer = QHBoxLayout()
        self._summary = QLabel()
        self._summary.setObjectName("footerText")
        footer.addWidget(self._summary, 1)
        self._close_btn = QPushButton("完成")
        self._close_btn.clicked.connect(self.close)
        footer.addWidget(self._close_btn)
        root.addLayout(footer)
        self._set_feedback_enabled(False)

    def refresh(self, selected_memory_id: str = "") -> None:
        self._reviews = self._control.list_recall_review(self._task_id)
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._reviews))
        selected_row = 0
        for row, review in enumerate(self._reviews):
            title = QTableWidgetItem(f"{review.title}\n{review.type_label}")
            title.setData(Qt.ItemDataRole.UserRole, review.memory_id)
            reason = QTableWidgetItem(review.reason)
            feedback_text = _FEEDBACK_LABELS[review.feedback]
            if review.feedback == MemoryRecallFeedback.UNREVIEWED and not review.is_current:
                feedback_text = "版本已更新"
            feedback = QTableWidgetItem(feedback_text)
            feedback.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 0, title)
            self._table.setItem(row, 1, reason)
            self._table.setItem(row, 2, feedback)
            self._table.setRowHeight(row, 52)
            if review.memory_id == selected_memory_id:
                selected_row = row
        self._table.blockSignals(False)
        reviewed = sum(
            review.feedback != MemoryRecallFeedback.UNREVIEWED for review in self._reviews
        )
        self._summary.setText(f"已反馈 {reviewed} / {len(self._reviews)} 条")
        if self._reviews:
            self._table.selectRow(selected_row)
            self._on_selection_changed()
        else:
            self._current = None
            self._detail_title.setText("没有可反馈的结构化记忆")
            self._detail_content.setText("这次可能只使用了会话摘要，或相关记忆已被永久忘记。")
            self._detail_reason.clear()
            self._feedback_status.clear()
            self._set_feedback_enabled(False)

    def _on_selection_changed(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._reviews):
            self._current = None
            self._set_feedback_enabled(False)
            return
        self._current = self._reviews[row]
        review = self._current
        self._detail_title.setText(f"{review.title} · {review.type_label}")
        self._detail_content.setText(review.content_preview)
        self._detail_reason.setText(f"调用原因：{review.reason}")
        already_reviewed = review.feedback != MemoryRecallFeedback.UNREVIEWED
        if already_reviewed:
            status = f"已记录：{_FEEDBACK_LABELS[review.feedback]}"
        elif not review.is_current:
            status = "这条记忆已更新，旧版本反馈入口已关闭"
        else:
            status = "等待你的反馈"
        self._feedback_status.setText(status)
        self._set_feedback_enabled(not already_reviewed and review.is_current)

    def _submit_feedback(self, feedback: MemoryRecallFeedback) -> None:
        review = self._current
        if review is None:
            return
        if feedback == MemoryRecallFeedback.INACCURATE:
            answer = QMessageBox.question(
                self,
                "暂停这条记忆？",
                "这会把该记忆标记为“等待确认”，立即停止用于后续回答。\n" "你可以稍后在记忆档案中校正或重新确认。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            recorded, _paused = self._control.record_recall_feedback(
                self._task_id,
                review.memory_id,
                feedback,
            )
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "无法记录反馈", str(exc))
            return
        if not recorded:
            QMessageBox.information(self, "反馈已存在", "这条召回反馈已经提交，不能重复覆盖。")
            self.refresh(review.memory_id)
            return
        self.memory_changed.emit(review.memory_id)
        self.refresh(review.memory_id)

    def _set_feedback_enabled(self, enabled: bool) -> None:
        self._helpful_btn.setEnabled(enabled)
        self._irrelevant_btn.setEnabled(enabled)
        self._inaccurate_btn.setEnabled(enabled)

    def _apply_theme(self, theme) -> None:
        secondary = generate_button_style(theme, size="sm", variant="secondary")
        self._helpful_btn.setStyleSheet(generate_button_style(theme, size="sm", variant="primary"))
        self._irrelevant_btn.setStyleSheet(secondary)
        self._inaccurate_btn.setStyleSheet(secondary)
        self._close_btn.setStyleSheet(secondary)
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {theme.background};
                color: {theme.text};
                font-size: 13px;
            }}
            QLabel#pageTitle {{
                color: {theme.text};
                font-size: 22px;
                font-weight: 700;
            }}
            QLabel#pageSubtitle, QLabel#hintText, QLabel#footerText {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QLabel#privacyBadge {{
                background: {theme.surface_soft};
                color: {theme.text_secondary};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
                padding: 6px 9px;
                font-size: 11px;
                font-weight: 600;
            }}
            QTableWidget {{
                background: {theme.surface};
                alternate-background-color: {theme.surface_soft};
                color: {theme.text};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_md}px;
                selection-background-color: {theme.primary_soft};
            }}
            QTableWidget::item {{
                border-bottom: 1px solid {theme.divider};
                padding: 7px 9px;
            }}
            QHeaderView::section {{
                background: {theme.surface_soft};
                color: {theme.text_secondary};
                border: none;
                border-bottom: 1px solid {theme.border};
                padding: 8px;
                font-size: 11px;
                font-weight: 700;
            }}
            QFrame#detailCard {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_md}px;
            }}
            QLabel#detailTitle {{
                color: {theme.text};
                font-size: 14px;
                font-weight: 700;
            }}
            QLabel#detailContent {{
                color: {theme.text};
                font-size: 13px;
            }}
            QLabel#detailReason, QLabel#feedbackStatus {{
                color: {theme.text_secondary};
                font-size: 11px;
            }}
            """
        )
