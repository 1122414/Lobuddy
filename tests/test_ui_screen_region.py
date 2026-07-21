"""Real Qt tests for the explicit screen-region interaction."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QWidget

from app.config import Settings
from core.screen_region import (
    ScreenRegionBounds,
    ScreenRegionCapture,
    ScreenRegionRuntime,
)
from core.storage import db as db_module
from core.storage.chat_repo import ChatRepository
from core.storage.db import Database
from ui.screen_region_selector import ScreenRegionSelector
from ui.task_panel import TaskPanel


def _ensure_qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _capture(path: Path) -> ScreenRegionCapture:
    Image.new("RGB", (320, 180), (231, 202, 174)).save(path, "PNG")
    now = datetime.now(timezone.utc)
    return ScreenRegionCapture(
        id="capture-1",
        path=path,
        bounds=ScreenRegionBounds(x=40, y=50, width=160, height=90),
        screen_name="Test display",
        pixel_width=320,
        pixel_height=180,
        size_bytes=path.stat().st_size,
        captured_at=now,
        expires_at=now + timedelta(minutes=5),
    )


class TestScreenRegionSelector:
    """The selector captures only the area directly dragged and confirmed by the user."""

    def test_drag_and_enter_create_scaled_crop_with_global_bounds(self, tmp_path):
        app = _ensure_qapp()
        parent = QWidget()
        background = QPixmap(800, 600)
        background.fill(QColor("#E8C9A7"))
        selector = ScreenRegionSelector(
            parent,
            minimum_size=24,
            background=background,
            screen_geometry=QRect(100, 200, 400, 300),
            screen_name="Second display",
        )
        selector.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        selector.show()
        app.processEvents()

        QTest.mousePress(
            selector,
            Qt.MouseButton.LeftButton,
            pos=QPoint(40, 50),
        )
        QTest.mouseMove(selector, QPoint(240, 190), delay=1)
        QTest.mouseRelease(
            selector,
            Qt.MouseButton.LeftButton,
            pos=QPoint(240, 190),
        )
        QTest.keyClick(selector, Qt.Key.Key_Return)
        app.processEvents()

        assert selector.result() == QDialog.DialogCode.Accepted
        draft = selector.selected_draft()
        assert draft.screen_name == "Second display"
        assert draft.bounds.x == 140
        assert draft.bounds.y == 250
        assert 195 <= draft.bounds.width <= 205
        assert 135 <= draft.bounds.height <= 145
        assert draft.path.is_file()
        with Image.open(draft.path) as cropped:
            assert 390 <= cropped.width <= 410
            assert 270 <= cropped.height <= 290

        runtime = ScreenRegionRuntime(
            Settings(
                llm_api_key="test",
                llm_multimodal_model="vision-test",
            ),
            root=tmp_path / "managed",
            draft_roots=[draft.path.parent],
            file_hardener=lambda _path: None,
        )
        capture = runtime.adopt_temporary_capture(draft)
        assert not draft.path.exists()
        assert capture.path.exists()
        assert runtime.clear_all() == 1
        selector.close()
        parent.close()

    def test_escape_cancels_without_creating_crop(self):
        app = _ensure_qapp()
        parent = QWidget()
        background = QPixmap(400, 300)
        background.fill(QColor("#E8C9A7"))
        selector = ScreenRegionSelector(
            parent,
            background=background,
            screen_geometry=QRect(0, 0, 400, 300),
        )
        selector.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        selector.show()
        app.processEvents()

        QTest.keyClick(selector, Qt.Key.Key_Escape)
        app.processEvents()

        assert selector.result() == QDialog.DialogCode.Rejected
        with pytest.raises(RuntimeError, match="No screen region"):
            selector.selected_draft()
        selector.close()
        parent.close()


class TestTaskPanelScreenRegion:
    """The task composer makes temporary ownership and privacy visible."""

    def test_preview_can_be_removed_and_emits_owned_path(self, tmp_path):
        _ensure_qapp()
        settings = Settings(
            llm_api_key="test",
            llm_multimodal_model="vision-test",
            data_dir=tmp_path / "data",
        )
        db_module._db = Database(settings)
        db_module._db.init_database()
        try:
            panel = TaskPanel(ChatRepository())
            panel.set_settings(settings)
            capture = _capture(tmp_path / "preview.png")
            cleared: list[str] = []
            panel.attachment_cleared.connect(cleared.append)

            panel.attach_screen_region(capture)

            assert panel.image_preview.isHidden() is False
            assert panel.image_preview_title.text() == "临时屏幕选区"
            assert "任务结束后自动删除" in panel.image_preview_text.text()
            assert panel.current_image_path == str(capture.path)
            assert "这个区域" in panel.input_box.placeholderText()

            panel._clear_image_btn.click()

            assert cleared == [str(capture.path)]
            assert panel.current_image_path is None
            assert "感受" in panel.input_box.placeholderText()
            panel.close()
        finally:
            db_module._db = None

    def test_send_uses_private_default_prompt_without_rendering_crop_in_chat(self, tmp_path):
        _ensure_qapp()
        settings = Settings(
            llm_api_key="test",
            llm_multimodal_model="vision-test",
            data_dir=tmp_path / "data",
        )
        db_module._db = Database(settings)
        db_module._db.init_database()
        try:
            repo = ChatRepository()
            repo.get_or_create_session("default", "default")
            panel = TaskPanel(repo)
            panel.set_settings(settings)
            capture = _capture(tmp_path / "send.png")
            submissions: list[tuple[str, str, str]] = []
            cleared: list[str] = []
            panel.task_submitted.connect(
                lambda text, session_id, path: submissions.append((text, session_id, path))
            )
            panel.attachment_cleared.connect(cleared.append)
            panel.attach_screen_region(capture)

            panel._send_btn.click()

            assert submissions == [
                (
                    "请分析我刚刚框选的屏幕区域，说明可见信息，并给出下一步建议。",
                    "default",
                    str(capture.path),
                )
            ]
            assert cleared == []
            assert panel.current_image_path is None
            image_labels = [
                label
                for message in panel.messages
                for label in message.findChildren(QLabel)
                if label.pixmap() is not None and not label.pixmap().isNull()
            ]
            assert image_labels == []
            panel.close()
        finally:
            db_module._db = None

    def test_screen_region_button_is_an_explicit_user_action(self, tmp_path):
        _ensure_qapp()
        settings = Settings(llm_api_key="test", data_dir=tmp_path / "data")
        db_module._db = Database(settings)
        db_module._db.init_database()
        try:
            panel = TaskPanel(ChatRepository())
            requested: list[bool] = []
            panel.screen_region_requested.connect(lambda: requested.append(True))

            panel._screen_region_btn.click()

            assert requested == [True]
            assert "只框选" in panel._screen_region_btn.toolTip()
            panel.close()
        finally:
            db_module._db = None
