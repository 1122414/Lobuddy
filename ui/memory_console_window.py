"""User-governed relationship memory console."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_schema import MemoryItem, MemoryStatus, MemoryType
from ui.memory_portability_dialog import MemoryImportReviewDialog
from ui.styles import current_theme
from ui.theme import (
    ThemeManager,
    generate_button_style,
    generate_card_style,
    generate_input_style,
)

logger = logging.getLogger(__name__)


_MEMORY_TYPE_LABELS = {
    MemoryType.USER_PROFILE: "关于你",
    MemoryType.SYSTEM_PROFILE: "伙伴身份",
    MemoryType.PROJECT_MEMORY: "项目",
    MemoryType.CONVERSATION_SUMMARY: "会话摘要",
    MemoryType.EPISODIC_MEMORY: "共同经历",
    MemoryType.PROCEDURAL_MEMORY: "做事方法",
}

_STATUS_LABELS = {
    MemoryStatus.ACTIVE: "正在使用",
    MemoryStatus.NEEDS_REVIEW: "等待确认",
    MemoryStatus.DEPRECATED: "已停用",
}

_MANUAL_MEMORY_OPTIONS = (
    ("偏好与边界", MemoryType.USER_PROFILE, 0.9),
    ("共同瞬间", MemoryType.EPISODIC_MEMORY, 0.85),
    ("协作方式", MemoryType.PROCEDURAL_MEMORY, 0.85),
    ("项目约定", MemoryType.PROJECT_MEMORY, 0.8),
)


class ManualMemoryDialog(QDialog):
    """Small explicit form for one user-authored Structured Memory."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("主动告诉 Lobuddy")
        self.setModal(True)
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        title = QLabel("这件事，我希望你记住")
        title.setObjectName("detailTitle")
        root.addWidget(title)
        hint = QLabel(
            "内容会保存为可管理的结构化记忆，并留下来源与变更原因。"
            "同类别、同标题会校正已有记忆。"
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)
        self.kind_combo = QComboBox()
        for label, memory_type, importance in _MANUAL_MEMORY_OPTIONS:
            self.kind_combo.addItem(label, (memory_type, importance))
        form.addRow("它属于", self.kind_combo)

        self.title_input = QLineEdit()
        self.title_input.setMaxLength(120)
        self.title_input.setPlaceholderText("例如：沟通节奏、第一次一起发布")
        form.addRow("一句标题", self.title_input)

        self.content_input = QTextEdit()
        self.content_input.setMinimumHeight(120)
        self.content_input.setPlaceholderText(
            "写下希望 Lobuddy 在以后相关时刻记得的内容。请不要填写密码、密钥或令牌。"
        )
        form.addRow("具体内容", self.content_input)
        root.addLayout(form)

        privacy_note = QLabel("隐私模式开启时，这次长期记忆写入会被拒绝。")
        privacy_note.setObjectName("provenanceText")
        privacy_note.setWordWrap(True)
        root.addWidget(privacy_note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("记住这件事")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._validate_and_accept)
        root.addWidget(buttons)
        theme = current_theme()
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(
            generate_button_style(theme, size="sm", variant="secondary")
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setStyleSheet(
            generate_button_style(theme, size="sm", variant="primary")
        )

    def values(self) -> tuple[MemoryType, float, str, str]:
        memory_type, importance = self.kind_combo.currentData()
        return (
            memory_type,
            float(importance),
            self.title_input.text().strip(),
            self.content_input.toPlainText().strip(),
        )

    def _validate_and_accept(self) -> None:
        _memory_type, _importance, title, content = self.values()
        if not title:
            QMessageBox.warning(self, "还差一个标题", "请用一句短标题说明这件事。")
            self.title_input.setFocus()
            return
        if not content:
            QMessageBox.warning(self, "还差具体内容", "请写下希望 Lobuddy 记住的内容。")
            self.content_input.setFocus()
            return
        if len(content) > 2000:
            QMessageBox.warning(self, "内容有点长", "请将这条记忆控制在 2000 字以内。")
            self.content_input.setFocus()
            return
        self.accept()


class MemoryConsoleWindow(QDialog):
    """A warm, explainable control surface for Lobuddy's relationship memory."""

    memory_changed = Signal()

    def __init__(
        self,
        control_service: MemoryControlService,
        parent=None,
        *,
        session_id_provider: Callable[[], str] | None = None,
    ):
        super().__init__(parent)
        self._control = control_service
        self._session_id_provider = session_id_provider or (lambda: "")
        self._current_item: MemoryItem | None = None
        self._show_full = getattr(
            control_service._settings,
            "memory_console_show_sensitive_content",
            False,
        )
        self._items_per_page = getattr(
            control_service._settings,
            "memory_console_items_per_page",
            20,
        )
        self._conflict_items: list[dict] = []
        self._init_ui()
        self._apply_theme(current_theme())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self._load_memories()

    def _init_ui(self) -> None:
        self.setWindowTitle("我们一起记住的事")
        self.setMinimumSize(1080, 700)
        self.resize(1220, 790)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(16)
        heading = QVBoxLayout()
        heading.setSpacing(3)
        self._title_label = QLabel("我们一起记住的事")
        self._title_label.setObjectName("pageTitle")
        heading.addWidget(self._title_label)
        self._subtitle_label = QLabel("你可以确认、校正或忘记任何内容。Lobuddy 只在相关时刻使用仍有效的记忆。")
        self._subtitle_label.setObjectName("pageSubtitle")
        heading.addWidget(self._subtitle_label)
        header.addLayout(heading, 1)

        self._remember_btn = QPushButton("主动告诉我")
        self._remember_btn.clicked.connect(self._on_remember_manual)
        header.addWidget(self._remember_btn)
        self._active_count_label = self._make_summary_chip("正在使用 0")
        self._review_count_label = self._make_summary_chip("等待确认 0")
        self._conflict_count_label = self._make_summary_chip("待裁决 0")
        header.addWidget(self._active_count_label)
        header.addWidget(self._review_count_label)
        header.addWidget(self._conflict_count_label)
        root.addLayout(header)

        filter_card = QWidget()
        filter_card.setObjectName("card")
        filters = QHBoxLayout(filter_card)
        filters.setContentsMargins(14, 12, 14, 12)
        filters.setSpacing(10)

        self._search_input = QLineEdit()
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setPlaceholderText("搜索名字、偏好、经历或项目…")
        self._search_input.returnPressed.connect(self._on_search)
        filters.addWidget(self._search_input, 1)

        self._type_filter = QComboBox()
        self._type_filter.setMinimumWidth(132)
        self._type_filter.addItem("全部类别", None)
        for memory_type, label in _MEMORY_TYPE_LABELS.items():
            self._type_filter.addItem(label, memory_type)
        self._type_filter.currentIndexChanged.connect(self._load_memories)
        filters.addWidget(self._type_filter)

        self._status_filter = QComboBox()
        self._status_filter.setMinimumWidth(132)
        self._status_filter.addItem("全部状态", None)
        for status, label in _STATUS_LABELS.items():
            self._status_filter.addItem(label, status)
        self._status_filter.currentIndexChanged.connect(self._load_memories)
        filters.addWidget(self._status_filter)

        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.clicked.connect(self._load_memories)
        filters.addWidget(self._refresh_btn)

        self._export_btn = QPushButton("导出记忆")
        self._export_btn.setToolTip("把可迁移的结构化记忆保存为本地 JSON 包")
        self._export_btn.clicked.connect(self._on_export_memories)
        filters.addWidget(self._export_btn)

        self._import_btn = QPushButton("导入记忆")
        self._import_btn.setToolTip("检查迁移包，导入内容会先等待你的确认")
        self._import_btn.clicked.connect(self._on_import_memories)
        filters.addWidget(self._import_btn)
        root.addWidget(filter_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        list_card = QWidget()
        list_card.setObjectName("card")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(16, 14, 16, 14)
        list_layout.setSpacing(10)
        list_title = QLabel("记忆清单")
        list_title.setObjectName("sectionTitle")
        list_layout.addWidget(list_title)

        self._table = QTableWidget()
        self._table.setObjectName("memoryTable")
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["记忆", "类别", "来源", "状态"])
        self._table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        list_layout.addWidget(self._table, 1)

        self._summary_label = QLabel()
        self._summary_label.setObjectName("mutedText")
        list_layout.addWidget(self._summary_label)
        splitter.addWidget(list_card)

        detail_card = QWidget()
        detail_card.setObjectName("card")
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(18, 16, 18, 16)
        detail_layout.setSpacing(10)

        detail_header = QHBoxLayout()
        detail_heading = QVBoxLayout()
        detail_heading.setSpacing(2)
        self._detail_title = QLabel("选择一条记忆")
        self._detail_title.setObjectName("detailTitle")
        detail_heading.addWidget(self._detail_title)
        self._detail_meta = QLabel("查看它为什么被记住，以及 Lobuddy 会怎样使用它")
        self._detail_meta.setObjectName("mutedText")
        detail_heading.addWidget(self._detail_meta)
        detail_header.addLayout(detail_heading, 1)

        self._trust_badge = QLabel("等待选择")
        self._trust_badge.setObjectName("trustBadge")
        self._trust_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_header.addWidget(self._trust_badge)
        detail_layout.addLayout(detail_header)

        self._content_edit = QTextEdit()
        self._content_edit.setObjectName("memoryEditor")
        self._content_edit.setPlaceholderText("选择记忆后，可以在这里校正内容")
        self._content_edit.setMinimumHeight(108)
        self._content_edit.setMaximumHeight(148)
        self._content_edit.textChanged.connect(self._sync_action_state)
        detail_layout.addWidget(self._content_edit)

        why_label = QLabel("为什么记住")
        why_label.setObjectName("eyebrow")
        detail_layout.addWidget(why_label)
        self._why_label = QLabel("选择记忆后显示来源与用途")
        self._why_label.setObjectName("explanationText")
        self._why_label.setWordWrap(True)
        detail_layout.addWidget(self._why_label)

        provenance_label = QLabel("关系脉络")
        provenance_label.setObjectName("eyebrow")
        detail_layout.addWidget(provenance_label)
        self._prov_label = QLabel("还没有选中内容")
        self._prov_label.setObjectName("provenanceText")
        self._prov_label.setWordWrap(True)
        detail_layout.addWidget(self._prov_label)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self._confirm_btn = QPushButton("确认准确")
        self._confirm_btn.clicked.connect(self._on_confirm)
        action_row.addWidget(self._confirm_btn)

        self._save_btn = QPushButton("保存校正")
        self._save_btn.clicked.connect(self._on_save)
        action_row.addWidget(self._save_btn)

        self._deprecate_btn = QPushButton("暂时不用")
        self._deprecate_btn.clicked.connect(self._on_toggle_retired)
        action_row.addWidget(self._deprecate_btn)

        self._delete_btn = QPushButton("永久忘记")
        self._delete_btn.clicked.connect(self._on_delete)
        action_row.addWidget(self._delete_btn)
        detail_layout.addLayout(action_row)

        self._show_full_check = QCheckBox("显示完整内容")
        self._show_full_check.setChecked(self._show_full)
        self._show_full_check.stateChanged.connect(self._on_toggle_full)
        detail_layout.addWidget(self._show_full_check)
        detail_layout.addStretch(1)

        splitter.addWidget(detail_card)
        splitter.setSizes([650, 470])
        root.addWidget(splitter, 3)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("memoryTabs")

        timeline_widget = QWidget()
        timeline_layout = QVBoxLayout(timeline_widget)
        timeline_layout.setContentsMargins(10, 12, 10, 10)
        timeline_layout.setSpacing(8)
        self._timeline_scope_label = QLabel("最近的关系变化")
        self._timeline_scope_label.setObjectName("mutedText")
        timeline_layout.addWidget(self._timeline_scope_label)
        self._timeline_table = QTableWidget()
        self._timeline_table.setColumnCount(5)
        self._timeline_table.setHorizontalHeaderLabels(["时间", "变化", "记忆", "由谁", "原因"])
        self._timeline_table.horizontalHeader().setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Stretch,
        )
        self._timeline_table.horizontalHeader().setSectionResizeMode(
            4,
            QHeaderView.ResizeMode.Stretch,
        )
        self._timeline_table.verticalHeader().setVisible(False)
        self._timeline_table.setShowGrid(False)
        self._timeline_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._timeline_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        timeline_layout.addWidget(self._timeline_table)
        self._tabs.addTab(timeline_widget, "关系时间线")

        self._conflict_widget = QWidget()
        conflict_layout = QVBoxLayout(self._conflict_widget)
        conflict_layout.setContentsMargins(10, 12, 10, 10)
        conflict_layout.setSpacing(8)
        self._conflict_label = QLabel("没有等待你确认的冲突")
        self._conflict_label.setObjectName("mutedText")
        conflict_layout.addWidget(self._conflict_label)

        self._conflict_table = QTableWidget()
        self._conflict_table.setColumnCount(4)
        self._conflict_table.setHorizontalHeaderLabels(["发现时间", "冲突类型", "原来的理解", "新的理解"])
        self._conflict_table.horizontalHeader().setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Stretch,
        )
        self._conflict_table.horizontalHeader().setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.Stretch,
        )
        self._conflict_table.verticalHeader().setVisible(False)
        self._conflict_table.setShowGrid(False)
        self._conflict_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._conflict_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._conflict_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._conflict_table.itemSelectionChanged.connect(self._on_conflict_selection_changed)
        conflict_layout.addWidget(self._conflict_table)

        conflict_actions = QHBoxLayout()
        self._accept_conflict_btn = QPushButton("采用新的理解")
        self._accept_conflict_btn.clicked.connect(lambda: self._on_resolve_conflict(True))
        conflict_actions.addWidget(self._accept_conflict_btn)
        self._reject_conflict_btn = QPushButton("保留原来的理解")
        self._reject_conflict_btn.clicked.connect(lambda: self._on_resolve_conflict(False))
        conflict_actions.addWidget(self._reject_conflict_btn)
        conflict_actions.addStretch()
        conflict_layout.addLayout(conflict_actions)
        self._tabs.addTab(self._conflict_widget, "需要我确认")
        root.addWidget(self._tabs, 2)

        self._conflict_btn = QPushButton("查看冲突")
        self._conflict_btn.setVisible(False)
        self._set_detail_enabled(False)

    @staticmethod
    def _make_summary_chip(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("summaryChip")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def _apply_theme(self, theme) -> None:
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {theme.background};
                color: {theme.text};
                font-size: 13px;
            }}
            QLabel#pageTitle {{
                color: {theme.text};
                font-size: 25px;
                font-weight: 700;
            }}
            QLabel#pageSubtitle, QLabel#mutedText {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QLabel#summaryChip {{
                background: {theme.surface_soft};
                color: {theme.text_secondary};
                border: 1px solid {theme.border};
                border-radius: 12px;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: 600;
            }}
            QLabel#sectionTitle {{
                color: {theme.text};
                font-size: 15px;
                font-weight: 700;
            }}
            QLabel#detailTitle {{
                color: {theme.text};
                font-size: 18px;
                font-weight: 700;
            }}
            QLabel#trustBadge {{
                background: {theme.primary_soft};
                color: {theme.primary_active};
                border: 1px solid {theme.border_focus};
                border-radius: 12px;
                padding: 5px 10px;
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#eyebrow {{
                color: {theme.text_secondary};
                font-size: 11px;
                font-weight: 700;
            }}
            QLabel#explanationText {{
                background: {theme.surface_soft};
                color: {theme.text};
                border-radius: 10px;
                padding: 10px 12px;
            }}
            QLabel#provenanceText {{
                color: {theme.text_secondary};
                line-height: 1.35;
            }}
            QTextEdit#memoryEditor {{
                background: {theme.input_bg};
                color: {theme.text};
                border: 1px solid {theme.input_border};
                border-radius: {theme.radius_sm}px;
                padding: 10px 12px;
                selection-background-color: {theme.primary_soft};
            }}
            QTextEdit#memoryEditor:focus {{
                border-color: {theme.input_focus_border};
            }}
            QComboBox {{
                background: {theme.input_bg};
                color: {theme.text};
                border: 1px solid {theme.input_border};
                border-radius: {theme.radius_sm}px;
                padding: 8px 12px;
            }}
            QComboBox:focus {{
                border-color: {theme.input_focus_border};
            }}
            QComboBox QAbstractItemView {{
                background: {theme.surface};
                color: {theme.text};
                border: 1px solid {theme.border};
                selection-background-color: {theme.primary_soft};
            }}
            QTableWidget {{
                background: {theme.surface};
                alternate-background-color: {theme.surface_soft};
                color: {theme.text};
                border: none;
                border-radius: 10px;
                selection-background-color: {theme.primary_soft};
                selection-color: {theme.text};
            }}
            QTableWidget::item {{
                border-bottom: 1px solid {theme.divider};
                padding: 7px;
            }}
            QHeaderView::section {{
                background: {theme.surface};
                color: {theme.text_muted};
                border: none;
                border-bottom: 1px solid {theme.border};
                padding: 7px;
                font-size: 11px;
                font-weight: 700;
            }}
            QTabWidget::pane {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_md}px;
                top: -1px;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {theme.text_secondary};
                padding: 8px 16px;
                margin-right: 4px;
            }}
            QTabBar::tab:selected {{
                color: {theme.primary};
                border-bottom: 2px solid {theme.primary};
                font-weight: 700;
            }}
            QCheckBox {{
                color: {theme.text_secondary};
                spacing: 7px;
            }}
            """
            + generate_card_style(theme)
            + generate_input_style(theme)
        )
        self._refresh_btn.setStyleSheet(
            generate_button_style(theme, size="sm", variant="secondary")
        )
        self._export_btn.setStyleSheet(
            generate_button_style(theme, size="sm", variant="secondary")
        )
        self._import_btn.setStyleSheet(
            generate_button_style(theme, size="sm", variant="secondary")
        )
        self._remember_btn.setStyleSheet(
            generate_button_style(theme, size="sm", variant="primary")
        )
        self._confirm_btn.setStyleSheet(
            generate_button_style(theme, size="sm", variant="secondary")
        )
        self._save_btn.setStyleSheet(generate_button_style(theme, size="sm", variant="primary"))
        self._deprecate_btn.setStyleSheet(generate_button_style(theme, size="sm", variant="ghost"))
        self._delete_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                color: {theme.danger};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
                padding: 8px 12px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: {theme.surface_soft};
                border-color: {theme.danger};
            }}
            """
        )
        self._accept_conflict_btn.setStyleSheet(
            generate_button_style(theme, size="sm", variant="primary")
        )
        self._reject_conflict_btn.setStyleSheet(
            generate_button_style(theme, size="sm", variant="secondary")
        )

    def _load_memories(self, *_args) -> None:
        selected_id = self._current_item.id if self._current_item else None
        try:
            memory_type = self._combo_value(self._type_filter, MemoryType)
            status = self._combo_value(self._status_filter, MemoryStatus)
            keyword = self._search_input.text().strip()
            if keyword:
                items = self._control.search_memories(
                    keyword,
                    memory_type=memory_type,
                    limit=max(50, self._items_per_page),
                    status=status,
                )
            else:
                items = self._control.list_memories(
                    memory_type=memory_type,
                    status=status,
                    limit=self._items_per_page,
                )
            self._populate_table(items, selected_id)
            self._refresh_summary(len(items), keyword)
            self._load_conflicts()
            if self._current_item is None:
                self._load_timeline()
        except Exception as exc:
            logger.warning("Failed to load memories: %s", exc)
            QMessageBox.warning(self, "加载失败", f"暂时无法读取记忆：{exc}")

    @staticmethod
    def _combo_value(combo: QComboBox, expected_type):
        value = combo.currentData()
        return value if isinstance(value, expected_type) else None

    def _populate_table(
        self,
        items: list[MemoryItem],
        selected_id: str | None = None,
    ) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(len(items))
        selected_row = -1
        for row, item in enumerate(items):
            explanation = self._control.explain_memory(item)
            content = self._control.get_sanitized_content(item, self._show_full)
            preview = self._compact_preview(content, 76)
            title = item.title.strip() or _MEMORY_TYPE_LABELS[item.memory_type]
            memory_cell = QTableWidgetItem(f"{title}\n{preview}")
            memory_cell.setData(Qt.ItemDataRole.UserRole, item)
            memory_cell.setToolTip(content)
            self._table.setItem(row, 0, memory_cell)
            self._table.setItem(
                row,
                1,
                QTableWidgetItem(_MEMORY_TYPE_LABELS[item.memory_type]),
            )
            self._table.setItem(
                row,
                2,
                QTableWidgetItem(explanation.source_label),
            )
            self._table.setItem(
                row,
                3,
                QTableWidgetItem(_STATUS_LABELS[item.status]),
            )
            self._table.setRowHeight(row, 54)
            if item.id == selected_id:
                selected_row = row
        self._table.blockSignals(False)

        if selected_row >= 0:
            self._table.selectRow(selected_row)
        elif items:
            self._table.selectRow(0)
        else:
            self._clear_detail()

    def _refresh_summary(self, visible_count: int, keyword: str) -> None:
        summary = self._control.get_status_summary()
        if not isinstance(summary, dict):
            summary = {}
        active = int(summary.get(MemoryStatus.ACTIVE.value, 0))
        review = int(summary.get(MemoryStatus.NEEDS_REVIEW.value, 0))
        retired = int(summary.get(MemoryStatus.DEPRECATED.value, 0))
        conflicts = self._control.count_pending_conflicts()
        conflicts = conflicts if isinstance(conflicts, int) else 0

        self._active_count_label.setText(f"正在使用 {active}")
        self._review_count_label.setText(f"等待确认 {review}")
        self._conflict_count_label.setText(f"待裁决 {conflicts}")
        if keyword:
            self._summary_label.setText(f"找到 {visible_count} 条与“{keyword}”相关的记忆")
        else:
            self._summary_label.setText(f"当前显示 {visible_count} 条 · 另有 {retired} 条已停用")
        self._tabs.setTabText(1, f"需要我确认 ({conflicts + review})")

    def _on_selection_changed(self) -> None:
        selected = self._table.selectedItems()
        if not selected:
            self._clear_detail()
            return
        row = selected[0].row()
        first_cell = self._table.item(row, 0)
        item = first_cell.data(Qt.ItemDataRole.UserRole) if first_cell else None
        if not isinstance(item, MemoryItem):
            self._clear_detail()
            return

        self._current_item = item
        self._detail_title.setText(item.title.strip() or _MEMORY_TYPE_LABELS[item.memory_type])
        self._detail_meta.setText(
            f"{_MEMORY_TYPE_LABELS[item.memory_type]} · {_STATUS_LABELS[item.status]}"
        )
        self._content_edit.blockSignals(True)
        self._content_edit.setPlainText(self._control.get_sanitized_content(item, self._show_full))
        self._content_edit.blockSignals(False)
        self._update_explanation(item)
        self._set_detail_enabled(True)
        self._sync_action_state()
        self._load_timeline(item.id)

    def _update_explanation(self, item: MemoryItem) -> None:
        explanation = self._control.explain_memory(item)
        self._trust_badge.setText(explanation.trust_label)
        feedback_parts = [f"用于回答 {explanation.recall_count} 次"]
        if explanation.helpful_count:
            feedback_parts.append(f"有帮助 {explanation.helpful_count}")
        if explanation.not_relevant_count:
            feedback_parts.append(f"不相关 {explanation.not_relevant_count}")
        if explanation.inaccurate_count:
            feedback_parts.append(f"内容不对 {explanation.inaccurate_count}")
        self._why_label.setText(
            f"{explanation.why_remembered}。{explanation.usage_label}。\n"
            + " · ".join(feedback_parts)
        )
        provenance = explanation.provenance
        precision = "可追溯到具体会话" if provenance.has_precise_source else "无精确会话定位"
        self._prov_label.setText(
            f"{explanation.source_label} · {precision}\n"
            f"记住于 {provenance.created_at:%Y-%m-%d %H:%M} · "
            f"最近变化 {provenance.updated_at:%Y-%m-%d %H:%M}"
        )

    def _clear_detail(self) -> None:
        self._current_item = None
        self._detail_title.setText("选择一条记忆")
        self._detail_meta.setText("查看它为什么被记住，以及 Lobuddy 会怎样使用它")
        self._trust_badge.setText("等待选择")
        self._content_edit.clear()
        self._why_label.setText("选择记忆后显示来源与用途")
        self._prov_label.setText("还没有选中内容")
        self._set_detail_enabled(False)
        self._load_timeline()

    def _set_detail_enabled(self, enabled: bool) -> None:
        self._content_edit.setEnabled(enabled)
        self._confirm_btn.setEnabled(enabled)
        self._save_btn.setEnabled(False)
        self._deprecate_btn.setEnabled(enabled)
        self._delete_btn.setEnabled(enabled)

    def _sync_action_state(self) -> None:
        item = self._current_item
        if item is None:
            self._set_detail_enabled(False)
            return
        edited = self._content_edit.toPlainText().strip()
        original = self._control.get_sanitized_content(item, self._show_full).strip()
        self._save_btn.setEnabled(bool(edited) and edited != original)
        self._confirm_btn.setEnabled(True)
        is_retired = item.status == MemoryStatus.DEPRECATED
        self._deprecate_btn.setText("恢复使用" if is_retired else "暂时不用")

    def _on_search(self) -> None:
        self._load_memories()

    def refresh(self) -> None:
        """Reload the user-visible memory archive after an external mutation."""
        self._load_memories()

    def _on_remember_manual(self) -> None:
        dialog = ManualMemoryDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        memory_type, importance, title, content = dialog.values()
        try:
            saved = self._control.remember_manual(
                memory_type=memory_type,
                title=title,
                content=content,
                session_id=self._session_id_provider(),
                importance=importance,
            )
        except ValueError as exc:
            QMessageBox.information(self, "这次没有写入", str(exc))
            return
        except Exception as exc:
            self._show_action_error("记忆失败", exc)
            return
        self._current_item = saved
        self._after_mutation("已经记住，并标注为你主动留下的内容")

    def _on_export_memories(self) -> None:
        suggested = Path.home() / f"Lobuddy-记忆-{datetime.now():%Y%m%d}.json"
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出结构化记忆",
            str(suggested),
            "Lobuddy 记忆迁移包 (*.json)",
        )
        if not file_path:
            return
        try:
            result = self._control.export_memory_package(file_path)
        except Exception as exc:
            self._show_action_error("导出失败", exc)
            return
        QMessageBox.information(
            self,
            "记忆已导出",
            f"已保存 {result.exported_count} 条可迁移记忆。\n\n"
            "文件可能包含你的偏好、经历和项目约定，请像保管私人资料一样妥善保存。",
        )

    def _on_import_memories(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择记忆迁移包",
            str(Path.home()),
            "Lobuddy 记忆迁移包 (*.json)",
        )
        if not file_path:
            return
        try:
            preview = self._control.inspect_memory_package(file_path)
        except Exception as exc:
            self._show_action_error("无法检查迁移包", exc)
            return
        dialog = MemoryImportReviewDialog(preview, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            result = self._control.import_memory_package(
                file_path,
                expected_file_digest=preview.file_digest,
                session_id=self._session_id_provider(),
            )
        except ValueError as exc:
            QMessageBox.information(self, "这次没有导入", str(exc))
            return
        except Exception as exc:
            self._show_action_error("导入失败", exc)
            return
        self._status_filter.setCurrentIndex(
            self._status_filter.findData(MemoryStatus.NEEDS_REVIEW)
        )
        self._after_mutation(
            f"已导入 {result.imported_count} 条，全部等待确认；"
            f"另有 {result.duplicate_count} 条重复内容已跳过"
        )

    def _on_confirm(self) -> None:
        if self._current_item is None:
            return
        reply = QMessageBox.question(
            self,
            "确认这条记忆",
            "确认后，Lobuddy 会把它视为你亲自核对过的信息。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            if self._control.confirm_memory(self._current_item.id) is not None:
                self._after_mutation("已标记为你亲自确认")
        except Exception as exc:
            self._show_action_error("确认失败", exc)

    def _on_save(self) -> None:
        if self._current_item is None:
            return
        content = self._content_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "无法保存", "记忆内容不能为空。")
            return
        reason, ok = QInputDialog.getText(
            self,
            "保存校正",
            "为什么需要这样修正？",
            QLineEdit.EchoMode.Normal,
            "这份表述现在更准确",
        )
        if not ok:
            return
        try:
            revised = self._control.revise_memory(
                self._current_item.id,
                content,
                reason.strip() or "你在记忆控制台修正了内容",
            )
            if revised is not None:
                self._after_mutation("已按你的校正更新")
        except Exception as exc:
            self._show_action_error("校正失败", exc)

    def _on_toggle_retired(self) -> None:
        if self._current_item is None:
            return
        is_retired = self._current_item.status == MemoryStatus.DEPRECATED
        if is_retired:
            reasons = ["重新变得相关", "之前只是暂时停用", "需要继续用于后续协作"]
            title = "恢复使用"
        else:
            reasons = ["近期不再相关", "信息可能已经过时", "暂时不希望用于后续对话"]
            title = "暂时不用"
        reason, ok = QInputDialog.getItem(
            self,
            title,
            "选择一个原因：",
            reasons,
            0,
            False,
        )
        if not ok:
            return
        try:
            if is_retired:
                success = self._control.restore_memory(self._current_item.id, reason)
                message = "这条记忆已恢复使用"
            else:
                success = self._control.retire_memory(self._current_item.id, reason)
                message = "这条记忆已停用，但仍可恢复"
            if success:
                self._after_mutation(message)
        except Exception as exc:
            self._show_action_error(f"{title}失败", exc)

    def _on_deprecate(self) -> None:
        """Backward-compatible action alias."""
        self._on_toggle_retired()

    def _on_delete(self) -> None:
        if self._current_item is None:
            return
        reasons = [
            "信息已经过时",
            "这是错误信息",
            "项目已经结束",
            "我不希望保存这类信息",
            "其他隐私原因",
        ]
        reason, ok = QInputDialog.getItem(
            self,
            "永久忘记",
            "选择遗忘原因（不会保留原文）：",
            reasons,
            0,
            False,
        )
        if not ok:
            return
        reply = QMessageBox.warning(
            self,
            "确认永久忘记",
            "正文会从数据库和本地记忆投影中永久清除，之后无法恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            if self._control.forget_memory(self._current_item.id, reason):
                self._after_mutation("已永久忘记正文，只保留不含内容的操作记录")
        except Exception as exc:
            self._show_action_error("遗忘失败", exc)

    def _after_mutation(self, message: str) -> None:
        self.memory_changed.emit()
        self._load_memories()
        QMessageBox.information(self, "已完成", message)

    @staticmethod
    def _show_action_error(title: str, exc: Exception) -> None:
        logger.warning("%s: %s", title, exc)
        QMessageBox.warning(None, title, f"{title}：{exc}")

    def _on_toggle_full(self, state) -> None:
        self._show_full = bool(state)
        selected_id = self._current_item.id if self._current_item else None
        self._load_memories()
        if selected_id and self._current_item and self._current_item.id == selected_id:
            self._content_edit.setPlainText(
                self._control.get_sanitized_content(
                    self._current_item,
                    self._show_full,
                )
            )

    def _populate_table_with_current(self) -> None:
        """Backward-compatible refresh helper."""
        self._load_memories()

    def _load_timeline(self, memory_id: str | None = None) -> None:
        try:
            entries = self._control.list_timeline(memory_id=memory_id, limit=80)
            self._timeline_table.setRowCount(len(entries))
            for row, entry in enumerate(entries):
                self._timeline_table.setItem(
                    row,
                    0,
                    QTableWidgetItem(entry.occurred_at.strftime("%m-%d %H:%M")),
                )
                self._timeline_table.setItem(
                    row,
                    1,
                    QTableWidgetItem(entry.event_label),
                )
                memory_text = entry.title
                if entry.content_preview:
                    memory_text += f"\n{entry.content_preview}"
                self._timeline_table.setItem(row, 2, QTableWidgetItem(memory_text))
                self._timeline_table.setItem(
                    row,
                    3,
                    QTableWidgetItem(entry.actor_label),
                )
                self._timeline_table.setItem(
                    row,
                    4,
                    QTableWidgetItem(entry.reason),
                )
                self._timeline_table.setRowHeight(row, 44)
            if memory_id and self._current_item:
                self._timeline_scope_label.setText(f"“{self._current_item.title or '这条记忆'}”的变化")
            else:
                self._timeline_scope_label.setText("最近的关系变化")
        except Exception as exc:
            logger.warning("Failed to load memory timeline: %s", exc)

    def _on_toggle_conflicts(self) -> None:
        """Backward-compatible shortcut that opens the conflict tab."""
        self._tabs.setCurrentIndex(1)
        self._load_conflicts()

    def _load_conflicts(self) -> None:
        try:
            conflicts = self._control.list_conflicts()
            self._populate_conflict_table(conflicts)
            pending = self._control.count_pending_conflicts()
            pending = pending if isinstance(pending, int) else 0
            if pending:
                self._conflict_label.setText(f"有 {pending} 组理解不一致，需要你决定采用哪一个。")
            else:
                self._conflict_label.setText("没有等待你确认的冲突。")
        except Exception as exc:
            logger.warning("Failed to load conflicts: %s", exc)

    def _populate_conflict_table(self, conflicts: list[dict]) -> None:
        self._conflict_items = list(conflicts)
        self._conflict_table.setRowCount(len(conflicts))
        for row, conflict in enumerate(conflicts):
            existing = conflict.get("existing_item")
            new_item = conflict.get("new_item")
            created_at = str(conflict.get("created_at", ""))[:16].replace("T", " ")
            conflict_type = str(conflict.get("conflict_type", "等待确认"))
            if conflict.get("type") == "conflict_candidate":
                old_text = (
                    self._compact_preview(
                        self._control.get_sanitized_content(existing),
                        90,
                    )
                    if isinstance(existing, MemoryItem)
                    else ""
                )
                new_text = (
                    self._compact_preview(
                        self._control.get_sanitized_content(new_item),
                        90,
                    )
                    if isinstance(new_item, MemoryItem)
                    else ""
                )
            else:
                item = conflict.get("item")
                old_text = (
                    self._compact_preview(
                        self._control.get_sanitized_content(item),
                        90,
                    )
                    if isinstance(item, MemoryItem)
                    else ""
                )
                new_text = "等待你确认这条内容"
                conflict_type = "需要复核"
            self._conflict_table.setItem(row, 0, QTableWidgetItem(created_at))
            self._conflict_table.setItem(row, 1, QTableWidgetItem(conflict_type))
            self._conflict_table.setItem(row, 2, QTableWidgetItem(old_text))
            self._conflict_table.setItem(row, 3, QTableWidgetItem(new_text))
            self._conflict_table.setRowHeight(row, 42)
        self._accept_conflict_btn.setEnabled(False)
        self._reject_conflict_btn.setEnabled(False)

    def _on_conflict_selection_changed(self) -> None:
        selected = self._conflict_table.selectedItems()
        if not selected:
            self._accept_conflict_btn.setEnabled(False)
            self._reject_conflict_btn.setEnabled(False)
            return
        row = selected[0].row()
        conflict = self._conflict_items[row] if row < len(self._conflict_items) else {}
        resolvable = conflict.get("type") == "conflict_candidate"
        self._accept_conflict_btn.setEnabled(resolvable)
        self._reject_conflict_btn.setEnabled(resolvable)

    def _on_resolve_conflict(self, accept_new: bool) -> None:
        selected = self._conflict_table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        if row >= len(self._conflict_items):
            return
        conflict = self._conflict_items[row]
        candidate_id = conflict.get("candidate_id")
        if not candidate_id:
            QMessageBox.warning(self, "暂时无法处理", "这条内容还没有可裁决的冲突记录。")
            return
        action = "采用新的理解" if accept_new else "保留原来的理解"
        reply = QMessageBox.question(
            self,
            "确认你的选择",
            f"{action}？另一份内容会停止使用，但裁决原因会保留在时间线中。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            success = self._control.resolve_conflict_with_reason(
                candidate_id,
                accept_new,
                f"你选择{action}",
            )
            if success:
                self._after_mutation(f"冲突已处理：{action}")
        except Exception as exc:
            self._show_action_error("冲突处理失败", exc)

    @staticmethod
    def _compact_preview(content: str, limit: int) -> str:
        compact = " ".join(content.split())
        if not compact:
            return "（没有可显示的内容）"
        return compact if len(compact) <= limit else compact[: limit - 1] + "…"
