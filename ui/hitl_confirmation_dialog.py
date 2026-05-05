"""HITL confirmation dialog for dangerous command approval.

Shown when the agent attempts to execute a dangerous shell command
(rm, del, rmdir, etc.). The user must explicitly click "确认执行"
to proceed — Esc, close, or "取消执行" all block the command.
"""

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QWidget,
)


class HitlConfirmationDialog(QDialog):
    confirmed = Signal(str, bool, str)

    def __init__(self, request, parent=None):
        super().__init__(parent)
        self._request = request
        self._result_set = False
        self.setWindowTitle("需要确认危险命令")
        self.setMinimumWidth(520)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        risk_label = QLabel("⚠ 该命令会删除文件或目录，执行后可能无法恢复。")
        risk_label.setStyleSheet("color: #CC6600; font-size: 13px; font-weight: bold;")
        risk_label.setWordWrap(True)
        layout.addWidget(risk_label)

        reason_label = QLabel(f"风险原因：{request.reason}")
        reason_label.setWordWrap(True)
        layout.addWidget(reason_label)

        command_label = QLabel("将要执行的命令：")
        layout.addWidget(command_label)

        command_text = QTextEdit()
        command_text.setPlainText(request.command)
        command_text.setReadOnly(True)
        command_text.setMaximumHeight(80)
        command_text.setStyleSheet("font-family: 'Consolas', 'Courier New', monospace; font-size: 12px;")
        layout.addWidget(command_text)

        if request.working_dir:
            wd_label = QLabel(f"工作目录：{request.working_dir}")
            wd_label.setStyleSheet("font-family: 'Consolas', monospace;")
            layout.addWidget(wd_label)

        if request.affected_paths:
            paths = list(request.affected_paths)[:10]
            paths_text = "\n".join(f"  • {p}" for p in paths)
            if len(request.affected_paths) > 10:
                paths_text += "\n  ..."
            paths_label = QLabel(f"影响路径：\n{paths_text}")
            paths_label.setStyleSheet("font-family: 'Consolas', monospace; font-size: 11px;")
            layout.addWidget(paths_label)

        layout.addStretch()

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("取消执行")
        cancel_btn.setDefault(True)
        cancel_btn.clicked.connect(self._on_cancel)
        button_layout.addWidget(cancel_btn)

        confirm_btn = QPushButton("确认执行")
        confirm_btn.setDefault(False)
        confirm_btn.setStyleSheet("QPushButton { background-color: #CC3300; color: white; font-weight: bold; }")
        confirm_btn.clicked.connect(self._on_confirm)
        button_layout.addWidget(confirm_btn)

        layout.addLayout(button_layout)

    def _on_confirm(self):
        if self._result_set:
            return
        self._result_set = True
        self.confirmed.emit(self._request.request_id, True, "用户确认执行")
        self.accept()

    def _on_cancel(self):
        if self._result_set:
            return
        self._result_set = True
        self.confirmed.emit(self._request.request_id, False, "用户取消执行")
        self.reject()

    def reject(self):
        if not self._result_set:
            self._result_set = True
            self.confirmed.emit(self._request.request_id, False, "用户关闭窗口")
        super().reject()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._on_cancel()
        else:
            super().keyPressEvent(event)
