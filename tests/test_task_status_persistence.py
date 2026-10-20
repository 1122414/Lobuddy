"""Tests for task status persistence."""

import pytest
from datetime import datetime

from app.config import Settings
from core.models.pet import TaskStatus, TaskRecord, TaskDifficulty
from core.storage.task_repo import TaskRepository
from core.storage.db import Database


class TestTaskStatusPersistence:
    """Test task status transitions are persisted."""

    def test_running_status_persisted(self, tmp_path, monkeypatch):
        """Test that RUNNING status is persisted when task starts."""
        settings = Settings(
            llm_api_key="test",
            data_dir=tmp_path,
        )
        db = Database(settings)
        db.init_database()

        # Create a task
        repo = TaskRepository(db)
        task = TaskRecord(
            id="test-task-1",
            input_text="Test input",
            status=TaskStatus.CREATED,
            difficulty=TaskDifficulty.SIMPLE,
        )
        repo.create_task(task)

        # Verify initial status
        stored = repo.get_task("test-task-1")
        assert stored.status == TaskStatus.CREATED
        assert stored.started_at is None

        # Simulate task start - update to RUNNING
        repo.update_task_status(
            "test-task-1",
            TaskStatus.RUNNING,
            started_at=datetime.now(),
        )

        # Verify RUNNING status persisted
        stored = repo.get_task("test-task-1")
        assert stored.status == TaskStatus.RUNNING
        assert stored.started_at is not None

    def test_completed_status_persisted(self, tmp_path, monkeypatch):
        """Test that completion status is persisted."""
        settings = Settings(
            llm_api_key="test",
            data_dir=tmp_path,
        )
        db = Database(settings)
        db.init_database()

        repo = TaskRepository(db)
        task = TaskRecord(
            id="test-task-2",
            input_text="Test input",
            status=TaskStatus.RUNNING,
            started_at=datetime.now(),
            difficulty=TaskDifficulty.SIMPLE,
        )
        repo.create_task(task)

        # Complete the task
        repo.update_task_status(
            "test-task-2",
            TaskStatus.SUCCESS,
            finished_at=datetime.now(),
        )

        # Verify completion persisted
        stored = repo.get_task("test-task-2")
        assert stored.status == TaskStatus.SUCCESS
        assert stored.finished_at is not None

    def test_failed_status_persisted(self, tmp_path, monkeypatch):
        """Test that failure status is persisted."""
        settings = Settings(
            llm_api_key="test",
            data_dir=tmp_path,
        )
        db = Database(settings)
        db.init_database()

        repo = TaskRepository(db)
        task = TaskRecord(
            id="test-task-3",
            input_text="Test input",
            status=TaskStatus.RUNNING,
            started_at=datetime.now(),
            difficulty=TaskDifficulty.SIMPLE,
        )
        repo.create_task(task)

        # Mark as failed
        repo.update_task_status(
            "test-task-3",
            TaskStatus.FAILED,
            finished_at=datetime.now(),
        )

        # Verify failure persisted
        stored = repo.get_task("test-task-3")
        assert stored.status == TaskStatus.FAILED
        assert stored.finished_at is not None
