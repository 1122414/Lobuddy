"""Task queue for serial task execution."""

import asyncio
from collections import deque
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from core.models.pet import TaskRecord, TaskResult


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
                # Reserve the single worker before yielding the lock. Without this,
                # an enqueue during worker teardown can be left without a processor.
                self._is_running = True
                self._processor_task = asyncio.create_task(self._process_queue())

            return self._queue_length

    async def _process_queue(self):
        """Process tasks in FIFO order."""
        processor = asyncio.current_task()
        try:
            while True:
                async with self._lock:
                    if self._shutdown:
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

                if self._task_executor is None:
                    result = TaskResult(
                        task_id=task_id,
                        success=False,
                        raw_result="",
                        summary="Task executor unavailable",
                        error_message="No task executor is configured",
                    )
                    self.task_completed.emit(task_id, result)
                else:
                    try:
                        result = await self._task_executor(self._current_task)
                        if not isinstance(result, TaskResult):
                            raise TypeError("Task executor must return TaskResult")
                        if result.task_id != task_id:
                            result = TaskResult(
                                task_id=task_id,
                                success=False,
                                raw_result="",
                                summary="Task result ownership mismatch",
                                error_message=(
                                    "Task executor returned a result for another Task Run"
                                ),
                            )
                        self.task_completed.emit(task_id, result)
                    except asyncio.CancelledError:
                        result = TaskResult(
                            task_id=task_id,
                            success=False,
                            raw_result="",
                            summary="任务已安全暂停",
                            error_message="应用退出时停止了正在执行的任务；未自动重放",
                            cancelled=True,
                        )
                        self.task_completed.emit(task_id, result)
                        raise
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
        finally:
            async with self._lock:
                if self._processor_task is processor:
                    self._is_running = False
                    self._current_task = None
                    self._processor_task = None
                    if self._queue and not self._shutdown:
                        self._is_running = True
                        self._processor_task = asyncio.create_task(self._process_queue())

    async def stop(self):
        """Safe-stop active and pending work without silently dropping Task Runs."""
        async with self._lock:
            self._shutdown = True
            pending = list(self._queue)
            self._queue.clear()
            self._queue_length = 0
            self.queue_updated.emit(0)
            processor = self._processor_task
        for task in pending:
            self.task_completed.emit(
                task.id,
                self._cancelled_result(
                    task.id,
                    "应用退出前已从等待队列安全移除；未开始执行",
                ),
            )
        if processor and not processor.done():
            processor.cancel()
            try:
                await asyncio.wait_for(processor, timeout=5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        async with self._lock:
            if self._processor_task is processor:
                self._processor_task = None
                self._is_running = False
                self._current_task = None

    def get_queue_length(self) -> int:
        return self._queue_length

    def has_other_work(self, task_id: str) -> bool:
        """Return whether work other than the completing Task Run still exists."""
        current = self._current_task
        return self._queue_length > 0 or (current is not None and current.id != task_id)

    async def clear(self):
        """Safe-stop pending work while allowing the current task to continue."""
        async with self._lock:
            pending = list(self._queue)
            self._queue.clear()
            self._queue_length = 0
        self.queue_updated.emit(0)
        for task in pending:
            self.task_completed.emit(
                task.id,
                self._cancelled_result(
                    task.id,
                    "已从等待队列安全移除；未开始执行",
                ),
            )

    @staticmethod
    def _cancelled_result(task_id: str, reason: str) -> TaskResult:
        return TaskResult(
            task_id=task_id,
            success=False,
            raw_result="",
            summary="任务已安全暂停",
            error_message=reason,
            cancelled=True,
        )
