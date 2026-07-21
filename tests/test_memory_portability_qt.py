"""Real Qt regressions for memory portability review and console wiring."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_QT_PROBE = r"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QFileDialog, QMessageBox

from core.config import Settings
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import MemoryItem, MemoryStatus, MemoryType
from core.memory.memory_service import MemoryService
from core.memory.memory_write_gateway import MemoryWriteGateway
from core.memory.privacy_mode import PrivacyModeManager
from core.storage.db import Database
from ui.memory_console_window import MemoryConsoleWindow
from ui.memory_portability_dialog import MemoryImportReviewDialog


def build_stack(root):
    settings = Settings(
        llm_api_key="test",
        data_dir=root / "data",
        logs_dir=root / "logs",
        workspace_path=root / "workspace",
        memory_enable_migration=False,
        user_name="",
    )
    repo = MemoryRepository(Database(settings))
    privacy = PrivacyModeManager(settings)
    service = MemoryService(settings, repo, privacy)
    gateway = MemoryWriteGateway(service, settings, privacy)
    control = MemoryControlService(
        settings,
        memory_service=service,
        repo=repo,
        gateway=gateway,
    )
    return service, control, repo


root = Path(sys.argv[1])
source_service, source_control, _source_repo = build_stack(root / "source")
source_service.save_memory(
    MemoryItem(
        id="preference",
        memory_type=MemoryType.USER_PROFILE,
        title="沟通偏好",
        content="先给结论",
    )
)
source_service.save_memory(
    MemoryItem(
        id="procedure",
        memory_type=MemoryType.PROCEDURAL_MEMORY,
        title="发布前检查",
        content="先测试，再写发布说明",
    )
)
package_path = root / "memories.json"
source_control.export_memory_package(package_path)

_target_service, target_control, target_repo = build_stack(root / "target")
preview = target_control.inspect_memory_package(package_path)
app = QApplication.instance() or QApplication([])

review = MemoryImportReviewDialog(preview)
review.show()
app.processEvents()
accept = review._buttons.button(QDialogButtonBox.StandardButton.Ok)
assert review.windowTitle() == "检查记忆迁移包"
assert "不会用于后续对话" in review._guardrail_label.text()
assert not accept.isEnabled()
review._acknowledge.setChecked(True)
app.processEvents()
assert accept.isEnabled()
assert review.minimumWidth() >= 560
review.close()

messages = []
QFileDialog.getOpenFileName = staticmethod(
    lambda *_args, **_kwargs: (str(package_path), "Lobuddy 记忆迁移包 (*.json)")
)
MemoryImportReviewDialog.exec = lambda self: QDialog.DialogCode.Accepted
QMessageBox.information = staticmethod(
    lambda _parent, title, message, *_args, **_kwargs: messages.append((title, message))
)

window = MemoryConsoleWindow(target_control, session_id_provider=lambda: "target-session")
window.show()
app.processEvents()
assert window._export_btn.text() == "导出记忆"
assert window._import_btn.text() == "导入记忆"
window._on_import_memories()
app.processEvents()

assert target_repo.count(MemoryStatus.NEEDS_REVIEW) == 2
assert window._status_filter.currentData() == MemoryStatus.NEEDS_REVIEW
assert any("全部等待确认" in message for _title, message in messages)

window.close()
app.processEvents()
"""


def test_real_qt_memory_import_review_and_console_wiring(tmp_path: Path) -> None:
    probe = tmp_path / "memory_portability_probe.py"
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
