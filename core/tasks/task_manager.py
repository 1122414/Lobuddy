"""Task manager for Lobuddy."""

import uuid
from datetime import datetime

from typing import Any

from PySide6.QtCore import QObject, Signal

from app.config import Settings
from core.agent.nanobot_adapter import NanobotAdapter
from core.models.pet import TaskDifficulty, TaskRecord, TaskResult, TaskStatus
from core.storage.task_repo import TaskRepository
from core.tasks.task_queue import TaskQueue


class TaskManager(QObject):
    """Manages task lifecycle and execution."""

    task_started = Signal(str)
    task_completed = Signal(str, bool, str, str)
    pet_state_changed = Signal(TaskStatus)

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.adapter = NanobotAdapter(settings)
        self.repo = TaskRepository()
        self.queue = TaskQueue()
        self._task_context: dict[str, dict[str, Any]] = {}

        self.queue.set_executor(self._execute_task)
        self.queue.task_started.connect(self._on_task_started)
        self.queue.task_completed.connect(self._on_task_completed)

    async def submit_task(
        self,
        input_text: str,
        session_id: str,
        chat_history: list[dict[str, Any]] | None = None,
    ) -> str:
        """Submit new task and return task ID."""
        task_id = str(uuid.uuid4())

        task = TaskRecord(
            id=task_id,
            input_text=input_text,
            task_type="general",
            status=TaskStatus.QUEUED,
            difficulty=TaskDifficulty.SIMPLE,
            reward_exp=5,
        )

        self.repo.create_task(task)
        self._task_context[task_id] = {
            "session_id": session_id,
            "chat_history": chat_history or [],
        }
        position = self.queue.add_task(task)

        return task_id

    async def _execute_task(self, task: TaskRecord) -> TaskResult:
        """Execute single task via nanobot."""
        context = self._task_context.pop(task.id, {})
        session_id = context.get("session_id", task.id)

        session_key = self.adapter.build_session_key(session_id)

        agent_result = await self.adapter.run_task(
            task.input_text,
            session_key,
        )

        task_result = TaskResult(
            task_id=task.id,
            success=agent_result.success,
            raw_result=agent_result.raw_output,
            summary=agent_result.summary,
            error_message=agent_result.error_message,
        )

        self.repo.save_task_result(task_result)

        if agent_result.success:
            task.status = TaskStatus.SUCCESS
        else:
            task.status = TaskStatus.FAILED
        task.finished_at = datetime.now()

        return task_result

    def _on_task_started(self, task_id: str):
        """Handle task start."""
        self.task_started.emit(task_id)
        self.pet_state_changed.emit(TaskStatus.RUNNING)

    def _on_task_completed(self, task_id: str, result: TaskResult):
        """Handle task completion."""
        self.task_completed.emit(task_id, result.success, result.summary, result.error_message)

        if self.queue.get_queue_length() == 0:
            if result.success:
                self.pet_state_changed.emit(TaskStatus.IDLE)
            else:
                self.pet_state_changed.emit(TaskStatus.FAILED)
