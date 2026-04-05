"""Task queue for serial task execution."""

import asyncio
from collections import deque
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from core.models.pet import TaskRecord, TaskResult, TaskStatus


class TaskQueue(QObject):
    """Serial task queue with FIFO ordering."""

    task_started = Signal(str)
    task_completed = Signal(str, TaskResult)
    queue_updated = Signal(int)

    def __init__(self):
        super().__init__()
        self._queue: deque[TaskRecord] = deque()
        self._current_task: Optional[TaskRecord] = None
        self._is_running = False
        self._task_executor: Optional[Callable] = None

    def set_executor(self, executor: Callable):
        """Set async task executor function."""
        self._task_executor = executor

    def add_task(self, task: TaskRecord) -> int:
        """Add task to queue and return position."""
        self._queue.append(task)
        position = len(self._queue)
        self.queue_updated.emit(position)

        if not self._is_running:
            asyncio.create_task(self._process_queue())

        return position

    async def _process_queue(self):
        """Process tasks in FIFO order."""
        if self._is_running:
            return

        self._is_running = True

        while self._queue:
            self._current_task = self._queue.popleft()
            self.queue_updated.emit(len(self._queue))

            task_id = self._current_task.id
            self._current_task.status = TaskStatus.RUNNING
            self.task_started.emit(task_id)

            if self._task_executor:
                try:
                    result = await self._task_executor(self._current_task)
                    self.task_completed.emit(task_id, result)
                except Exception as e:
                    result = TaskResult(
                        task_id=task_id,
                        success=False,
                        raw_result="",
                        summary="Task execution failed",
                        error_message=str(e),
                    )
                    self.task_completed.emit(task_id, result)

            self._current_task = None

        self._is_running = False

    def get_queue_length(self) -> int:
        """Get current queue length."""
        return len(self._queue)

    def clear(self):
        """Clear all pending tasks."""
        self._queue.clear()
        self.queue_updated.emit(0)
