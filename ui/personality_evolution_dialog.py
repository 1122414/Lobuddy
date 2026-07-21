"""User-governed history and restoration for Lobuddy's pet personality."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.models.personality import PersonalityDimension
from core.personality.evolution import PersonalityEvolution
from core.personality.evolution_models import (
    PERSONALITY_TRAIT_LABELS,
    PersonalityVersionView,
)
from ui.styles import current_theme
from ui.theme import (
    ThemeManager,
    generate_button_style,
    generate_card_style,
)


class PersonalityEvolutionDialog(QDialog):
    """Version history whose restore action appends evidence instead of rewriting it."""

    restored = Signal(str)

    def __init__(
        self,
        evolution: PersonalityEvolution,
        parent=None,
        *,
        pet_id: str = "default",
    ) -> None:
        super().__init__(parent)
        self._evolution = evolution
        self._pet_id = pet_id
        self._versions: list[PersonalityVersionView] = []
        self._current_version: PersonalityVersionView | None = None
        self._init_ui()
        self._apply_theme(current_theme())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self.refresh()

    def _init_ui(self) -> None:
        self.setWindowTitle("Lobuddy 的成长版本")
        self.setMinimumSize(900, 620)
        self.resize(980, 690)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(3)
        title = QLabel("Lobuddy 的成长版本")
        title.setObjectName("pageTitle")
        heading.addWidget(title)
        subtitle = QLabel("每次任务成长和用户恢复都会留下版本；任务正文不会进入这里。")
        subtitle.setObjectName("pageSubtitle")
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)
        self._version_chip = QLabel("0 个版本")
        self._version_chip.setObjectName("summaryChip")
        self._version_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._version_chip)
        root.addLayout(header)

        guardrail = QLabel(
            "恢复只改变五维成长倾向与对应证据计数。等级、经验、外观和已经解锁的能力保持不变。"
        )
        guardrail.setObjectName("guardrail")
        guardrail.setWordWrap(True)
        root.addWidget(guardrail)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        history_card = QWidget()
        history_card.setObjectName("card")
        history_layout = QVBoxLayout(history_card)
        history_layout.setContentsMargins(16, 14, 16, 14)
        history_layout.setSpacing(10)
        history_title = QLabel("版本时间线")
        history_title.setObjectName("sectionTitle")
        history_layout.addWidget(history_title)

        self._table = QTableWidget()
        self._table.setObjectName("versionTable")
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["版本", "时间", "来源", "变化"])
        self._table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
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
            QHeaderView.ResizeMode.Stretch,
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        history_layout.addWidget(self._table, 1)
        splitter.addWidget(history_card)

        detail_card = QWidget()
        detail_card.setObjectName("card")
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(18, 16, 18, 16)
        detail_layout.setSpacing(10)

        detail_header = QHBoxLayout()
        detail_heading = QVBoxLayout()
        detail_heading.setSpacing(2)
        self._detail_title = QLabel("选择一个成长版本")
        self._detail_title.setObjectName("detailTitle")
        detail_heading.addWidget(self._detail_title)
        self._detail_meta = QLabel("查看形成原因与五维结果")
        self._detail_meta.setObjectName("mutedText")
        detail_heading.addWidget(self._detail_meta)
        detail_header.addLayout(detail_heading, 1)
        self._current_chip = QLabel("等待选择")
        self._current_chip.setObjectName("currentChip")
        detail_header.addWidget(self._current_chip)
        detail_layout.addLayout(detail_header)

        self._summary_label = QLabel("还没有选中版本")
        self._summary_label.setObjectName("versionSummary")
        self._summary_label.setWordWrap(True)
        detail_layout.addWidget(self._summary_label)

        reason_title = QLabel("为什么有这个版本")
        reason_title.setObjectName("eyebrow")
        detail_layout.addWidget(reason_title)
        self._reason_label = QLabel("选择后显示内容最小化的形成原因")
        self._reason_label.setObjectName("reasonText")
        self._reason_label.setWordWrap(True)
        detail_layout.addWidget(self._reason_label)

        traits_title = QLabel("这个版本的五维成长")
        traits_title.setObjectName("eyebrow")
        detail_layout.addWidget(traits_title)
        self._traits_layout = QVBoxLayout()
        self._traits_layout.setSpacing(8)
        detail_layout.addLayout(self._traits_layout)
        detail_layout.addStretch(1)

        self._restore_btn = QPushButton("恢复到这个版本")
        self._restore_btn.clicked.connect(self._restore_selected)
        self._restore_btn.setEnabled(False)
        detail_layout.addWidget(self._restore_btn)
        splitter.addWidget(detail_card)
        splitter.setSizes([540, 390])
        root.addWidget(splitter, 1)

        footer = QLabel(
            "版本历史是追加式证据：恢复会生成一个新版本，不会删除或改写旧版本。"
        )
        footer.setObjectName("footerText")
        footer.setWordWrap(True)
        root.addWidget(footer)

    def refresh(self) -> None:
        selected_id = self._current_version.revision_id if self._current_version else ""
        self._versions = self._evolution.history(pet_id=self._pet_id, limit=200)
        self._version_chip.setText(f"{len(self._versions)} 个可追溯版本")
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._versions))
        selected_row = -1
        for row, version in enumerate(self._versions):
            version_cell = QTableWidgetItem(f"#{version.sequence}")
            version_cell.setData(Qt.ItemDataRole.UserRole, version)
            self._table.setItem(row, 0, version_cell)
            self._table.setItem(
                row,
                1,
                QTableWidgetItem(version.created_at.strftime("%m-%d %H:%M")),
            )
            self._table.setItem(row, 2, QTableWidgetItem(version.kind_label))
            suffix = " · 当前" if version.is_current else ""
            self._table.setItem(row, 3, QTableWidgetItem(f"{version.summary}{suffix}"))
            self._table.setRowHeight(row, 48)
            if version.revision_id == selected_id:
                selected_row = row
        self._table.blockSignals(False)
        if selected_row >= 0:
            self._table.selectRow(selected_row)
        elif self._versions:
            self._table.selectRow(0)

    def _on_selection_changed(self) -> None:
        selected = self._table.selectedItems()
        if not selected:
            return
        first = self._table.item(selected[0].row(), 0)
        version = first.data(Qt.ItemDataRole.UserRole) if first else None
        if not isinstance(version, PersonalityVersionView):
            return
        self._current_version = version
        self._detail_title.setText(f"成长版本 #{version.sequence}")
        self._detail_meta.setText(
            f"{version.kind_label} · {version.source_label} · "
            f"{version.created_at:%Y-%m-%d %H:%M}"
        )
        self._current_chip.setText("当前版本" if version.is_current else "历史版本")
        self._summary_label.setText(version.summary)
        self._reason_label.setText(version.reason)
        self._render_traits(version)
        self._restore_btn.setEnabled(version.can_restore)
        self._restore_btn.setText("当前正在使用" if version.is_current else "恢复到这个版本")

    def _render_traits(self, version: PersonalityVersionView) -> None:
        self._clear_layout(self._traits_layout)
        for dimension in PersonalityDimension:
            row = QWidget()
            row.setObjectName("traitRow")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            label = QLabel(PERSONALITY_TRAIT_LABELS[dimension])
            label.setObjectName("traitName")
            label.setFixedWidth(76)
            layout.addWidget(label)
            value = float(getattr(version.personality, dimension.value))
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(round(value * 10))
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            layout.addWidget(bar, 1)
            value_label = QLabel(f"{value:g}")
            value_label.setObjectName("traitValue")
            value_label.setFixedWidth(42)
            value_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            layout.addWidget(value_label)
            self._traits_layout.addWidget(row)

    def _restore_selected(self) -> None:
        version = self._current_version
        if version is None or not version.can_restore:
            return
        reason, ok = QInputDialog.getText(
            self,
            "恢复成长版本",
            "为什么希望恢复到这个版本？",
            QLineEdit.EchoMode.Normal,
            "这版更符合我希望的伙伴成长方式",
        )
        if not ok:
            return
        reason = reason.strip()
        if not reason:
            QMessageBox.warning(self, "还差恢复原因", "请说明为什么选择这个版本。")
            return
        reply = QMessageBox.warning(
            self,
            "确认恢复成长版本",
            "只会恢复五维成长倾向与证据计数；等级、经验、外观和已解锁能力不会倒退。"
            "恢复操作本身会成为一个新版本。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self._evolution.restore(
                version.revision_id,
                pet_id=self._pet_id,
                reason=reason,
            )
        except Exception as exc:
            QMessageBox.warning(self, "恢复失败", f"暂时无法恢复这个版本：{exc}")
            return
        if not result.applied:
            QMessageBox.information(self, "无需恢复", "当前已经是这个成长版本。")
            return
        self.restored.emit(result.revision.id)
        self._current_version = None
        self.refresh()
        QMessageBox.information(
            self,
            "已恢复",
            "Lobuddy 已恢复到所选成长状态，并保留了一条新的恢复版本。",
        )

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
            QLabel#summaryChip, QLabel#currentChip {{
                background: {theme.surface_soft};
                color: {theme.text_secondary};
                border: 1px solid {theme.border};
                border-radius: 12px;
                padding: 5px 9px;
                font-size: 11px;
                font-weight: 700;
            }}
            QLabel#guardrail {{
                background: {theme.primary_soft};
                color: {theme.text};
                border: 1px solid {theme.border_focus};
                border-radius: {theme.radius_sm}px;
                padding: 10px 12px;
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
            QLabel#versionSummary {{
                background: {theme.surface_soft};
                color: {theme.text};
                border-radius: {theme.radius_sm}px;
                padding: 10px 12px;
                font-weight: 700;
            }}
            QLabel#eyebrow {{
                color: {theme.text_secondary};
                font-size: 11px;
                font-weight: 700;
            }}
            QLabel#reasonText, QLabel#footerText {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QLabel#traitName {{
                color: {theme.text};
                font-weight: 700;
            }}
            QLabel#traitValue {{
                color: {theme.primary_active};
                font-weight: 700;
            }}
            QProgressBar {{
                background: {theme.surface_soft};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: {theme.primary};
                border-radius: 4px;
            }}
            QTableWidget {{
                background: {theme.surface};
                alternate-background-color: {theme.surface_soft};
                color: {theme.text};
                border: none;
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
            """
            + generate_card_style(theme)
        )
        self._restore_btn.setStyleSheet(
            generate_button_style(theme, size="sm", variant="primary")
        )

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
