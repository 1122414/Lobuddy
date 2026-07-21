"""Warm, low-noise review dialog for a Memory Portability Package."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.memory.memory_portability import MemoryImportPreview
from ui.styles import current_theme
from ui.theme import ThemeManager, generate_button_style, generate_card_style

_TYPE_LABELS = {
    "user_profile": "偏好与边界",
    "project_memory": "项目约定",
    "episodic_memory": "共同经历",
    "procedural_memory": "协作方法",
}


class MemoryImportReviewDialog(QDialog):
    """Explain a validated import without exposing memory content."""

    def __init__(self, preview: MemoryImportPreview, parent=None) -> None:
        super().__init__(parent)
        self._preview = preview
        self.setWindowTitle("检查记忆迁移包")
        self.setModal(True)
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        title = QLabel("把熟悉的协作方式带到这里")
        title.setObjectName("portabilityTitle")
        root.addWidget(title)
        subtitle = QLabel(
            "Lobuddy 已检查文件格式与完整性。这里仅显示数量与类别，不在预览中展开记忆正文。"
        )
        subtitle.setObjectName("portabilityMuted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        summary = QWidget()
        summary.setObjectName("card")
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(16, 14, 16, 14)
        summary_layout.setSpacing(18)
        self._add_metric(summary_layout, "可以导入", str(preview.importable_count))
        self._add_metric(summary_layout, "重复跳过", str(preview.duplicate_count))
        self._add_metric(summary_layout, "包内总数", str(preview.total_count))
        root.addWidget(summary)

        type_text = " · ".join(
            f"{_TYPE_LABELS.get(memory_type, memory_type)} {count}"
            for memory_type, count in preview.type_counts.items()
        )
        self._type_label = QLabel(type_text or "这个迁移包没有可显示的记忆类别")
        self._type_label.setObjectName("portabilityTypes")
        self._type_label.setWordWrap(True)
        root.addWidget(self._type_label)

        try:
            exported_at = datetime.fromisoformat(preview.exported_at).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            exported_at = preview.exported_at
        package_note = QLabel(
            f"文件：{preview.path.name}\n导出时间：{exported_at}\n"
            f"包标识：{preview.package_id[:8]}…"
        )
        package_note.setObjectName("portabilityMuted")
        package_note.setWordWrap(True)
        root.addWidget(package_note)

        self._guardrail_label = QLabel(
            "安全边界：导入会清除原始会话与消息来源，生成新的本地记忆；"
            "所有内容先进入“等待确认”，在你逐条确认前不会用于后续对话。"
        )
        self._guardrail_label.setObjectName("portabilityGuardrail")
        self._guardrail_label.setWordWrap(True)
        root.addWidget(self._guardrail_label)

        self._acknowledge = QCheckBox("我知道这些内容需要逐条确认")
        self._acknowledge.toggled.connect(self._sync_accept_state)
        root.addWidget(self._acknowledge)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("先不导入")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("导入并等待确认")
        self._buttons.rejected.connect(self.reject)
        self._buttons.accepted.connect(self.accept)
        root.addWidget(self._buttons)

        self._apply_theme(current_theme())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self._sync_accept_state()

    @staticmethod
    def _add_metric(layout: QHBoxLayout, label: str, value: str) -> None:
        column = QVBoxLayout()
        column.setSpacing(2)
        value_label = QLabel(value)
        value_label.setObjectName("portabilityMetric")
        column.addWidget(value_label)
        name_label = QLabel(label)
        name_label.setObjectName("portabilityMuted")
        column.addWidget(name_label)
        layout.addLayout(column, 1)

    def _sync_accept_state(self) -> None:
        accept = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        accept.setEnabled(
            self._preview.importable_count > 0 and self._acknowledge.isChecked()
        )

    def _apply_theme(self, theme) -> None:
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {theme.background};
                color: {theme.text};
                font-size: 13px;
            }}
            QLabel#portabilityTitle {{
                color: {theme.text};
                font-size: 20px;
                font-weight: 700;
            }}
            QLabel#portabilityMetric {{
                color: {theme.text};
                font-size: 22px;
                font-weight: 700;
            }}
            QLabel#portabilityMuted {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QLabel#portabilityTypes {{
                color: {theme.text};
                font-weight: 600;
                padding: 2px 0;
            }}
            QLabel#portabilityGuardrail {{
                background: {theme.surface_soft};
                color: {theme.text};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
                padding: 11px 13px;
            }}
            QCheckBox {{
                color: {theme.text_secondary};
                spacing: 8px;
            }}
            """
            + generate_card_style(theme)
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(
            generate_button_style(theme, size="sm", variant="secondary")
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(
            generate_button_style(theme, size="sm", variant="primary")
        )
