"""Subprocess Qt regressions for the relationship memory console."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_QT_PROBE = r"""
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from core.config import Settings
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    MemoryContextEvidence,
    MemoryItem,
    MemoryRecallFeedback,
    MemoryRevisionType,
    MemoryType,
)
from core.memory.memory_service import MemoryService
from core.storage import db as db_module
from core.storage.db import Database
from ui.memory_console_window import MemoryConsoleWindow


def select_memory(window, memory_id):
    for row in range(window._table.rowCount()):
        item = window._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if getattr(item, "id", "") == memory_id:
            window._table.selectRow(row)
            return
    raise AssertionError(f"Memory not shown in console: {memory_id}")


root = Path(sys.argv[1])
mode = sys.argv[2]
settings = Settings(
    llm_api_key="test",
    data_dir=root / "data",
    logs_dir=root / "logs",
    workspace_path=root / "workspace",
    memory_enable_migration=False,
    user_name="",
)
database = Database(settings)
db_module._db = database
repo = MemoryRepository(database)
service = MemoryService(settings, repo)
control = MemoryControlService(settings, memory_service=service, repo=repo)
service.save_memory(
    MemoryItem(
        id="preference",
        memory_type=MemoryType.USER_PROFILE,
        title="沟通偏好",
        content="先给我简短结论",
        source="ai_patch",
        confidence=0.82,
    )
)
service.save_memory(
    MemoryItem(
        id="shared-moment",
        memory_type=MemoryType.EPISODIC_MEMORY,
        title="第一次一起发布",
        content="我们完成了版本检查和发布说明",
        source="exit_analysis",
    )
)
service.record_recall(
    "task-console",
    "session-console",
    [
        MemoryContextEvidence(
            memory_id="preference",
            memory_type=MemoryType.USER_PROFILE,
            reason="用户档案优先级",
            chars=28,
        )
    ],
)
control.record_recall_feedback(
    "task-console",
    "preference",
    MemoryRecallFeedback.HELPFUL,
)

app = QApplication.instance() or QApplication([])
window = MemoryConsoleWindow(control)
window.show()
app.processEvents()
select_memory(window, "preference")
app.processEvents()

if mode == "render":
    assert window.windowTitle() == "我们一起记住的事"
    assert window._table.columnCount() == 4
    assert window._table.horizontalHeaderItem(0).text() == "记忆"
    assert window._table.rowCount() >= 2
    assert window._current_item is not None
    assert "对话" in window._why_label.text()
    assert "用于回答 1 次" in window._why_label.text()
    assert "有帮助 1" in window._why_label.text()
    assert window._timeline_table.rowCount() >= 1
    assert window._delete_btn.text() == "永久忘记"
    assert window._remember_btn.text() == "主动告诉我"
    assert window._export_btn.text() == "导出记忆"
    assert window._import_btn.text() == "导入记忆"
    assert window.minimumWidth() >= 1080
elif mode == "correct":
    QInputDialog.getText = staticmethod(
        lambda *_args, **_kwargs: ("这份描述更符合现在的偏好", True)
    )
    QMessageBox.information = staticmethod(
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok
    )
    window._content_edit.setPlainText("先给结论，再补充必要细节")
    window._on_save()
    app.processEvents()
    updated = repo.get("preference")
    assert updated is not None
    assert updated.content == "先给结论，再补充必要细节"
    revisions = repo.list_revisions("preference")
    assert revisions[0].revision_type == MemoryRevisionType.CORRECTED
    assert revisions[0].reason == "这份描述更符合现在的偏好"
    assert window._trust_badge.text() == "你已确认"
else:
    raise AssertionError(mode)

window.close()
db_module._db = None
app.processEvents()
"""


def _run_qt_probe(tmp_path: Path, mode: str) -> None:
    probe = tmp_path / f"memory_console_{mode}_probe.py"
    probe.write_text(_QT_PROBE, encoding="utf-8")
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    completed = subprocess.run(
        [sys.executable, str(probe), str(tmp_path), mode],
        cwd=Path(__file__).parent.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_real_qt_console_explains_memory_and_renders_timeline(tmp_path: Path) -> None:
    _run_qt_probe(tmp_path, "render")


def test_real_qt_correction_records_reason_and_refreshes_trust(
    tmp_path: Path,
) -> None:
    _run_qt_probe(tmp_path, "correct")
