"""User-facing work record built from privacy-safe runtime evidence."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.services.observability_service import ObservabilityService
from ui.styles import current_theme
from ui.theme import (
    ThemeManager,
    generate_button_style,
    generate_card_style,
)


_STATUS_LABELS = {
    "created": "准备中",
    "queued": "排队中",
    "running": "处理中",
    "success": "已完成",
    "failed": "未完成",
    "cancelled": "已安全暂停",
}


class ObservabilityPanel(QDialog):
    """Calm command-center view of Task Runs and execution evidence."""

    def __init__(
        self,
        observability: ObservabilityService,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._obs = observability
        self._init_ui()
        self._apply_theme(current_theme())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self._refresh()

    def _init_ui(self) -> None:
        self.setWindowTitle("工作记录")
        self.setMinimumSize(920, 650)
        self.resize(1040, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(3)
        title = QLabel("工作记录")
        title.setObjectName("pageTitle")
        heading.addWidget(title)
        subtitle = QLabel("看清 Lobuddy 做到了哪里、用了多久，以及为什么停下。")
        subtitle.setObjectName("pageSubtitle")
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)

        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.clicked.connect(self._refresh)
        header.addWidget(self._refresh_btn)
        root.addLayout(header)

        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        self._total_metric = self._metric("最近工作", "0")
        self._success_metric = self._metric("完成率", "—")
        self._duration_metric = self._metric("平均用时", "—")
        self._interrupted_metric = self._metric("安全暂停", "0")
        for card, _value in (
            self._total_metric,
            self._success_metric,
            self._duration_metric,
            self._interrupted_metric,
        ):
            metrics.addWidget(card, 1)
        root.addLayout(metrics)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("workTabs")
        self._tabs.addTab(self._build_runs_tab(), "最近工作")
        self._tabs.addTab(self._build_tools_tab(), "工具可靠性")
        self._tabs.addTab(self._build_evidence_tab(), "运行证据")
        root.addWidget(self._tabs, 1)

        footer = QHBoxLayout()
        privacy_note = QLabel("运行记录只保存脱敏摘要、状态与计量信息，不展示完整提示词、输入文本或密钥。")
        privacy_note.setObjectName("privacyNote")
        privacy_note.setWordWrap(True)
        footer.addWidget(privacy_note, 1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("closeButton")
        close_btn.clicked.connect(self.close)
        footer.addWidget(close_btn)
        root.addLayout(footer)
        self._close_btn = close_btn

    @staticmethod
    def _metric(label: str, value: str) -> tuple[QWidget, QLabel]:
        card = QWidget()
        card.setObjectName("metricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(3)
        label_widget = QLabel(label)
        label_widget.setObjectName("metricLabel")
        layout.addWidget(label_widget)
        value_widget = QLabel(value)
        value_widget.setObjectName("metricValue")
        layout.addWidget(value_widget)
        return card, value_widget

    def _build_runs_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(8)
        self._runs_hint = QLabel("最近的 Task Run 会显示真实尝试次数、耗时、模型用量和最后进展。")
        self._runs_hint.setObjectName("hintText")
        layout.addWidget(self._runs_hint)
        self._runs_table = self._table(
            ["工作", "状态", "尝试", "耗时 / 预测", "模型用量", "最后进展"],
        )
        self._runs_table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        self._runs_table.horizontalHeader().setSectionResizeMode(
            5,
            QHeaderView.ResizeMode.Stretch,
        )
        layout.addWidget(self._runs_table)
        return page

    def _build_tools_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(8)
        hint = QLabel("可靠性来自最近的真实工具调用；没有调用时不会生成推测数据。")
        hint.setObjectName("hintText")
        layout.addWidget(hint)
        self._tools_table = self._table(["工具", "调用次数", "成功率"])
        self._tools_table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        layout.addWidget(self._tools_table)
        return page

    def _build_evidence_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        self._token_label = QLabel("Token：暂无可用计量")
        self._token_label.setObjectName("evidenceSummary")
        layout.addWidget(self._token_label)

        trace_title = QLabel("最近工具调用")
        trace_title.setObjectName("sectionTitle")
        layout.addWidget(trace_title)
        self._trace_table = self._table(["工具", "状态", "结果摘要"])
        self._trace_table.horizontalHeader().setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Stretch,
        )
        layout.addWidget(self._trace_table, 1)

        approval_title = QLabel("最近人工确认")
        approval_title.setObjectName("sectionTitle")
        layout.addWidget(approval_title)
        self._approval_table = self._table(["工具", "决定", "命令摘要"])
        self._approval_table.horizontalHeader().setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Stretch,
        )
        layout.addWidget(self._approval_table, 1)
        return page

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for column in range(len(headers)):
            table.horizontalHeader().setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        return table

    def _refresh(self) -> None:
        data = self._obs.get_summary()
        self._populate_metrics(data.get("task_overview", {}))
        self._populate_runs(data.get("recent_tasks", []))
        self._populate_tools(data.get("tool_reliability", []))
        self._populate_traces(data.get("recent_traces", []))
        self._populate_approvals(data.get("hitl_decisions", []))
        self._populate_tokens(data.get("token", {}))

    def _populate_metrics(self, overview: dict) -> None:
        available = overview.get("available", False)
        self._total_metric[1].setText(str(overview.get("total", 0)) if available else "—")
        self._success_metric[1].setText(f"{overview.get('success_rate', 0)}%" if available else "—")
        average = int(overview.get("average_duration_seconds", 0))
        self._duration_metric[1].setText(self._duration(average) if average else "—")
        self._interrupted_metric[1].setText(
            str(overview.get("interrupted", 0)) if available else "—"
        )

    def _populate_runs(self, runs: list[dict]) -> None:
        self._runs_table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            elapsed = int(run.get("elapsed_seconds", 0))
            estimate = int(run.get("estimated_duration_seconds", 0))
            status = str(run.get("status", ""))
            timing = self._duration(elapsed) if elapsed else "尚未开始"
            if not elapsed and status in {"success", "failed", "cancelled"}:
                timing = "< 1 秒"
            elif not elapsed and estimate:
                timing = f"预计 {self._duration(estimate)}"
            self._set_row(
                self._runs_table,
                row,
                [
                    run.get("summary", "") or "未命名工作",
                    _STATUS_LABELS.get(
                        str(run.get("status", "")),
                        str(run.get("status", "")),
                    ),
                    f"第 {run.get('attempt_no', 1)} 次",
                    timing,
                    self._run_usage(run),
                    run.get("latest_update", "") or "等待更新",
                ],
            )
            self._runs_table.setRowHeight(row, 42)
        self._runs_hint.setText(
            (
                "还没有工作记录。完成第一项任务后，这里会出现真实运行轨迹。"
                if not runs
                else "最近的 Task Run 会显示真实尝试次数、耗时、模型用量和最后进展。"
            )
        )

    def _populate_tools(self, tools: list[dict]) -> None:
        self._tools_table.setRowCount(len(tools))
        for row, tool in enumerate(tools):
            self._set_row(
                self._tools_table,
                row,
                [
                    tool.get("tool_name", "") or "unknown",
                    str(tool.get("calls", 0)),
                    f"{tool.get('success_rate', 0)}%",
                ],
            )
            self._tools_table.setRowHeight(row, 38)

    def _populate_traces(self, traces: list[dict]) -> None:
        self._trace_table.setRowCount(len(traces))
        for row, trace in enumerate(traces):
            self._set_row(
                self._trace_table,
                row,
                [
                    trace.get("tool_name", "") or "unknown",
                    trace.get("status", "unknown"),
                    trace.get("result_summary", ""),
                ],
            )

    def _populate_approvals(self, approvals: list[dict]) -> None:
        self._approval_table.setRowCount(len(approvals))
        for row, approval in enumerate(approvals):
            self._set_row(
                self._approval_table,
                row,
                [
                    approval.get("tool_name", "") or "unknown",
                    approval.get("decision", "unknown"),
                    approval.get("command_preview", ""),
                ],
            )

    def _populate_tokens(self, token_data: dict) -> None:
        if not token_data or not token_data.get("available", True):
            self._token_label.setText("Token：暂无可用计量")
            return
        sessions = [value for value in token_data.values() if isinstance(value, dict)]
        total_tokens = sum(int(item.get("total_tokens", 0)) for item in sessions)
        turns = sum(int(item.get("turn_count", 0)) for item in sessions)
        provider_turns = sum(
            int(item.get("measurement_sources", {}).get("provider", 0)) for item in sessions
        )
        estimated_turns = sum(
            int(item.get("measurement_sources", {}).get("local_estimate", 0)) for item in sessions
        )
        if estimated_turns and provider_turns:
            evidence = "含本地估算"
        elif estimated_turns:
            evidence = "本地估算"
        elif provider_turns:
            evidence = "服务商计量"
        else:
            evidence = "来源未标注"
        self._token_label.setText(f"Token：{total_tokens:,} · {evidence} · 对话轮次：{turns}")

    @classmethod
    def _run_usage(cls, run: dict) -> str:
        total = int(run.get("model_usage_tokens", 0))
        source = str(run.get("model_usage_source", "unavailable"))
        if total > 0:
            label = "实测" if source == "provider" else "估算"
            return f"{label} {cls._tokens(total)}"
        estimate = int(run.get("estimated_token_usage", 0))
        return f"预算约 {cls._tokens(estimate)}" if estimate > 0 else "—"

    @staticmethod
    def _tokens(tokens: int) -> str:
        if tokens < 1000:
            return f"{tokens:,}"
        value = tokens / 1000
        return f"{value:.1f}k" if tokens % 1000 else f"{int(value)}k"

    @staticmethod
    def _set_row(
        table: QTableWidget,
        row: int,
        values: list[str],
    ) -> None:
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            table.setItem(row, column, item)

    @staticmethod
    def _duration(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds} 秒"
        minutes, remainder = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes} 分钟" if remainder < 30 else f"约 {minutes + 1} 分钟"
        hours, minutes = divmod(minutes, 60)
        return f"{hours} 小时" if not minutes else f"{hours} 小时 {minutes} 分钟"

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
            QLabel#pageSubtitle, QLabel#hintText, QLabel#privacyNote {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QWidget#metricCard {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_md}px;
            }}
            QLabel#metricLabel {{
                color: {theme.text_muted};
                font-size: 11px;
                font-weight: 600;
            }}
            QLabel#metricValue {{
                color: {theme.text};
                font-size: 20px;
                font-weight: 700;
            }}
            QLabel#sectionTitle {{
                color: {theme.text};
                font-size: 13px;
                font-weight: 700;
            }}
            QLabel#evidenceSummary {{
                background: {theme.surface_soft};
                color: {theme.text_secondary};
                border-radius: {theme.radius_sm}px;
                padding: 9px 12px;
                font-weight: 600;
            }}
            QTableWidget {{
                background: {theme.surface};
                alternate-background-color: {theme.surface_soft};
                color: {theme.text};
                border: none;
                selection-background-color: {theme.primary_soft};
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
            """
            + generate_card_style(theme)
        )
        self._refresh_btn.setStyleSheet(
            generate_button_style(theme, size="sm", variant="secondary")
        )
        self._close_btn.setStyleSheet(generate_button_style(theme, size="sm", variant="primary"))
