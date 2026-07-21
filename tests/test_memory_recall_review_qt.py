"""Subprocess Qt regression for per-Task Run memory recall feedback."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_QT_PROBE = r"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from core.config import Settings
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    MemoryContextEvidence,
    MemoryItem,
    MemoryRecallFeedback,
    MemoryStatus,
    MemoryType,
)
from core.memory.memory_service import MemoryService
from core.storage.db import Database
from ui.memory_recall_review_dialog import MemoryRecallReviewDialog


root = Path(sys.argv[1])
settings = Settings(
    llm_api_key="test",
    data_dir=root / "data",
    logs_dir=root / "logs",
    workspace_path=root / "workspace",
    memory_enable_migration=False,
)
database = Database(settings)
database.init_database()
repo = MemoryRepository(database)
service = MemoryService(settings, repo)
control = MemoryControlService(settings, memory_service=service, repo=repo)
helpful = repo.save(
    MemoryItem(
        id="memory-a",
        memory_type=MemoryType.USER_PROFILE,
        title="沟通偏好",
        content="你偏好简洁的进度说明",
    )
)
inaccurate = repo.save(
    MemoryItem(
        id="memory-b",
        memory_type=MemoryType.PROJECT_MEMORY,
        title="发布时间",
        content="项目固定在周五发布",
    )
)
service.record_recall(
    "task-review",
    "session-1",
    [
        MemoryContextEvidence(
            memory_id=helpful.id,
            memory_type=helpful.memory_type,
            reason="用户档案优先级",
            chars=28,
        ),
        MemoryContextEvidence(
            memory_id=inaccurate.id,
            memory_type=inaccurate.memory_type,
            reason="当前请求关键词匹配",
            chars=32,
        ),
    ],
)
app = QApplication.instance() or QApplication([])
dialog = MemoryRecallReviewDialog(control, "task-review")
changed = []
dialog.memory_changed.connect(changed.append)
dialog.show()
app.processEvents()

assert dialog._table.rowCount() == 2
assert "沟通偏好" in dialog._table.item(0, 0).text()
dialog._table.selectRow(0)
dialog._helpful_btn.click()
app.processEvents()
assert dialog._table.item(0, 2).text() == "有帮助"

QMessageBox.question = staticmethod(
    lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes
)
dialog._table.selectRow(1)
dialog._inaccurate_btn.click()
app.processEvents()

assert dialog._table.item(1, 2).text() == "内容不对"
persisted = repo.get(inaccurate.id)
assert persisted is not None
assert persisted.status == MemoryStatus.NEEDS_REVIEW
assert changed == [helpful.id, inaccurate.id]
receipts = repo.list_recall_receipts("task-review")
assert [receipt.feedback for receipt in receipts] == [
    MemoryRecallFeedback.HELPFUL,
    MemoryRecallFeedback.INACCURATE,
]
assert dialog.grab().width() >= 680
dialog.close()
app.processEvents()
"""


def test_recall_review_records_feedback_and_pauses_inaccurate_memory(
    tmp_path: Path,
) -> None:
    probe = tmp_path / "memory_recall_review_probe.py"
    probe.write_text(_QT_PROBE, encoding="utf-8")
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    completed = subprocess.run(
        [sys.executable, str(probe), str(tmp_path)],
        cwd=Path(__file__).parent.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
