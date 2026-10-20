"""HITL confirmation dialog for dangerous command approval.

Shown when the agent attempts to execute a dangerous shell command
(rm, del, rmdir, etc.). The user must explicitly click "确认执行"
to proceed — Esc, close, or "取消执行" all block the command.
"""

from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QWidget,
)

from ui.theme import ThemeManager


class HitlConfirmationDialog(QDialog):
    confirmed = Signal(str, bool, str)

    def __init__(self, request, parent=None):
        super().__init__(parent)
        self._request = request
        self._result_set = False

        # Calculate accurate remaining time from request creation
        elapsed = (datetime.now(timezone.utc) - request.created_at).total_seconds()
        self._remaining = max(0, int(request.timeout_seconds - elapsed))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

        t = ThemeManager.instance().current

        self.setWindowTitle("需要确认危险命令")
        self.setMinimumWidth(580)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background: {t.surface}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # === Header: icon + title + tool name + risk badge ===
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        icon_label = QLabel("⚠️")
        icon_label.setStyleSheet("font-size: 24px;")
        header_layout.addWidget(icon_label)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        title_label = QLabel("危险命令确认")
        title_label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {t.text};")
        title_col.addWidget(title_label)

        subtitle_label = QLabel(f"工具：{request.tool_name}")
        subtitle_label.setStyleSheet(f"font-size: 12px; color: {t.text_secondary};")
        title_col.addWidget(subtitle_label)

        header_layout.addLayout(title_col)
        header_layout.addStretch()

        # Risk level badge
        if request.risk_tags:
            badge_text = " · ".join(request.risk_tags).upper()
            badge_bg = t.danger
        else:
            badge_text = "需要确认"
            badge_bg = t.warning

        risk_badge = QLabel(badge_text)
        risk_badge.setStyleSheet(
            f"background: {badge_bg}; color: white; font-weight: bold; "
            f"font-size: 10px; padding: 4px 12px; "
            f"border-radius: {t.radius_sm - 2}px;"
        )
        risk_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(risk_badge)

        layout.addLayout(header_layout)

        # === Divider ===
        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {t.divider};")
        layout.addWidget(divider)

        # === Reason (warning box with left accent border) ===
        reason_container = QFrame()
        reason_container.setStyleSheet(
            f"QFrame {{"
            f"  background: {t.surface_soft};"
            f"  border-left: 3px solid {t.warning};"
            f"  border-radius: {t.radius_sm}px;"
            f"}}"
        )
        reason_layout = QHBoxLayout(reason_container)
        reason_layout.setContentsMargins(12, 10, 12, 10)
        reason_layout.setSpacing(8)

        warn_icon = QLabel("⚠")
        warn_icon.setStyleSheet(f"font-size: 16px; color: {t.warning}; background: transparent;")
        reason_layout.addWidget(warn_icon)

        reason_label = QLabel(request.reason)
        reason_label.setWordWrap(True)
        reason_label.setStyleSheet(f"color: {t.text}; font-size: 13px; background: transparent;")
        reason_layout.addWidget(reason_label)

        layout.addWidget(reason_container)

        # === Command code block ===
        cmd_header = QLabel("将要执行的命令：")
        cmd_header.setStyleSheet(
            f"color: {t.text_secondary}; font-size: 12px; font-weight: bold;"
        )
        layout.addWidget(cmd_header)

        command_text = QTextEdit()
        command_text.setPlainText(request.command)
        command_text.setReadOnly(True)
        command_text.setMaximumHeight(100)
        command_text.setStyleSheet(
            f"QTextEdit {{"
            f"  font-family: 'Consolas', 'Courier New', monospace;"
            f"  font-size: 12px;"
            f"  background: {t.background};"
            f"  color: {t.text};"
            f"  border: 1px solid {t.border};"
            f"  border-radius: {t.radius_sm}px;"
            f"  padding: 10px;"
            f"}}"
        )
        layout.addWidget(command_text)

        # === Details: working dir + affected paths ===
        if request.working_dir:
            wd_icon = QLabel("📁")
            wd_icon.setStyleSheet("font-size: 11px;")
            wd_label = QLabel(f"工作目录：{request.working_dir}")

            wd_row = QHBoxLayout()
            wd_row.setSpacing(4)
            wd_row.addWidget(wd_icon)
            wd_row.addWidget(wd_label)
            wd_row.addStretch()

            wd_label.setStyleSheet(
                f"font-family: 'Consolas', monospace; font-size: 11px; color: {t.text_secondary};"
            )
            layout.addLayout(wd_row)

        if request.affected_paths:
            paths = list(request.affected_paths)[:10]
            paths_lines = "\n".join(f"  • {p}" for p in paths)
            if len(request.affected_paths) > 10:
                paths_lines += "\n  ..."

            paths_header = QLabel("影响路径：")
            paths_header.setStyleSheet(f"color: {t.text_muted}; font-size: 11px;")
            layout.addWidget(paths_header)

            paths_label = QLabel(paths_lines)
            paths_label.setStyleSheet(
                f"font-family: 'Consolas', monospace; font-size: 11px; "
                f"color: {t.text_muted};"
            )
            layout.addWidget(paths_label)

        # === Countdown timer ===
        self._timer_label = QLabel(self._format_timer_text())
        self._timer_label.setStyleSheet(f"color: {t.text_muted}; font-size: 11px;")
        layout.addWidget(self._timer_label)

        layout.addStretch()

        # === Divider ===
        divider2 = QWidget()
        divider2.setFixedHeight(1)
        divider2.setStyleSheet(f"background: {t.divider};")
        layout.addWidget(divider2)

        # === Buttons ===
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        cancel_btn = QPushButton("取消执行 (Esc)")
        cancel_btn.setDefault(True)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {t.surface};"
            f"  color: {t.text};"
            f"  border: 1px solid {t.border};"
            f"  border-radius: {t.radius_sm}px;"
            f"  padding: 10px 24px;"
            f"  font-size: 13px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {t.surface_soft};"
            f"  border-color: {t.text_muted};"
            f"}}"
        )
        cancel_btn.clicked.connect(self._on_cancel)
        button_layout.addWidget(cancel_btn)

        button_layout.addStretch()

        confirm_btn = QPushButton("确认执行")
        confirm_btn.setDefault(False)
        confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {t.danger};"
            f"  color: white;"
            f"  border: none;"
            f"  border-radius: {t.radius_sm}px;"
            f"  padding: 10px 24px;"
            f"  font-size: 13px;"
            f"  font-weight: bold;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {t.danger};"
            f"  border: 1px solid rgba(255, 255, 255, 0.3);"
            f"}}"
        )
        confirm_btn.clicked.connect(self._on_confirm)
        button_layout.addWidget(confirm_btn)

        layout.addLayout(button_layout)

        # If request already expired, auto-timeout after a short delay
        if self._remaining <= 0:
            self._timer.stop()
            t_exp = ThemeManager.instance().current
            self._timer_label.setText("⏱ 请求已超时")
            self._timer_label.setStyleSheet(
                f"color: {t_exp.danger}; font-size: 11px; font-weight: bold;"
            )
            QTimer.singleShot(100, self._on_timeout)

    # ── helpers ──────────────────────────────────────────────────────────

    def _format_timer_text(self) -> str:
        return f"⏱ 剩余时间：{self._remaining}秒"

    def _tick(self):
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self._on_timeout()
        else:
            self._timer_label.setText(self._format_timer_text())
            if self._remaining <= 10:
                t = ThemeManager.instance().current
                self._timer_label.setStyleSheet(
                    f"color: {t.danger}; font-size: 11px; font-weight: bold;"
                )

    # ── signal logic (preserved from original) ───────────────────────────

    def _on_timeout(self):
        if self._result_set:
            return
        self._result_set = True
        self.confirmed.emit(self._request.request_id, False, "HITL 请求超时")
        self.reject()

    def _on_confirm(self):
        if self._result_set:
            return
        self._timer.stop()
        self._result_set = True
        self.confirmed.emit(self._request.request_id, True, "用户确认执行")
        self.accept()

    def _on_cancel(self):
        if self._result_set:
            return
        self._timer.stop()
        self._result_set = True
        self.confirmed.emit(self._request.request_id, False, "用户取消执行")
        self.reject()

    def reject(self):
        self._timer.stop()
        if not self._result_set:
            self._result_set = True
            self.confirmed.emit(self._request.request_id, False, "用户关闭窗口")
        super().reject()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._on_cancel()
        else:
            super().keyPressEvent(event)
