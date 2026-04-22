"""Task queue for serial task execution."""

import asyncio
from collections import deque
from datetime import datetime
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
        self._queue_length = 0
        self._current_task: Optional[TaskRecord] = None
        self._is_running = False
        self._task_executor: Optional[Callable] = None
        self._shutdown = False
        self._processor_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def set_executor(self, executor: Callable):
        """Set async task executor function."""
        self._task_executor = executor

    async def add_task(self, task: TaskRecord) -> int:
        """Add task to queue and return position."""
        async with self._lock:
            if self._shutdown:
                return 0

            self._queue.append(task)
            self._queue_length = len(self._queue)
            self.queue_updated.emit(self._queue_length)

            if not self._is_running:
                self._processor_task = asyncio.create_task(self._process_queue())

            return self._queue_length

    async def _process_queue(self):
        """Process tasks in FIFO order."""
        async with self._lock:
            if self._is_running:
                return
            self._is_running = True

        try:
            while True:
                async with self._lock:
                    if self._shutdown:
                        self._queue.clear()
                        self.queue_updated.emit(0)
                        break

                    if not self._queue:
                        break

                    self._current_task = self._queue.popleft()
                    self._queue_length = len(self._queue)
                    self.queue_updated.emit(self._queue_length)

                task_id = self._current_task.id
                try:
                    self._current_task.start()
                except ValueError as e:
                    self._current_task.complete(False)
                    result = TaskResult(
                        task_id=task_id,
                        success=False,
                        raw_result="",
                        summary="Invalid task state transition",
                        error_message=str(e),
                    )
                    self.task_completed.emit(task_id, result)
                    self._current_task = None
                    continue

                self.task_started.emit(task_id)

                if self._task_executor:
                    try:
                        result = await self._task_executor(self._current_task)
                        self.task_completed.emit(task_id, result)
                    except asyncio.CancelledError:
                        self._current_task.complete(False)
                        result = TaskResult(
                            task_id=task_id,
                            success=False,
                            raw_result="",
                            summary="Task cancelled",
                            error_message="Task was cancelled during shutdown",
                        )
                        self.task_completed.emit(task_id, result)
                        raise
                    except Exception as e:
                        self._current_task.complete(False)
                        result = TaskResult(
                            task_id=task_id,
                            success=False,
                            raw_result="",
                            summary="Task execution failed",
                            error_message=str(e),
                        )
                        self.task_completed.emit(task_id, result)

                self._current_task = None
        finally:
            async with self._lock:
                self._is_running = False
                self._current_task = None

    async def stop(self):
        """Stop queue processing and clear pending tasks."""
        async with self._lock:
            self._shutdown = True
            self._queue.clear()
            self._queue_length = 0
            self.queue_updated.emit(0)
            processor = self._processor_task
        if processor and not processor.done():
            processor.cancel()
            try:
                await asyncio.wait_for(processor, timeout=5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

    def get_queue_length(self) -> int:
        return self._queue_length

    async def clear(self):
        async with self._lock:
            self._queue.clear()
            self._queue_length = 0
        self.queue_updated.emit(0)
