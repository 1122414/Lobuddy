"""Regression tests for image inspection and image-only task entry."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from core.agent.image_validation import inspect_image_file
from core.storage import db as db_module
from core.storage.db import Database


def test_image_inspection_reports_mime_and_size(tmp_path):
    image = tmp_path / "sample.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"preview")

    result = inspect_image_file(image)

    assert result.mime_type == "image/png"
    assert result.size_bytes == image.stat().st_size


def test_image_inspection_rejects_extension_magic_mismatch(tmp_path):
    image = tmp_path / "renamed.jpg"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"preview")

    with pytest.raises(ValueError, match="does not match"):
        inspect_image_file(image)


def test_task_manager_accepts_image_without_typed_prompt(tmp_path):
    from core.tasks.task_manager import TaskManager

    settings = Settings(llm_api_key="test", data_dir=tmp_path / "data")
    db_module._db = Database(settings)
    db_module._db.init_database()
    manager = None
    try:
        manager = TaskManager(settings)
        manager.queue.add_task = AsyncMock(return_value=1)

        task_id = asyncio.run(manager.submit_task("", "session-1", str(tmp_path / "sample.png")))

        assert task_id
        queued_task = manager.queue.add_task.await_args.args[0]
        assert queued_task.input_text == "请描述这张图片，并指出你认为最重要的信息。"
    finally:
        if manager is not None:
            if hasattr(manager.queue.task_started, "disconnect"):
                manager.queue.task_started.disconnect(manager._on_task_started)
            if hasattr(manager.queue.task_completed, "disconnect"):
                manager.queue.task_completed.disconnect(manager._on_task_completed)
        db_module._db = None
