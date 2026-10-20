"""Qt-free serial task queue with one owned processor and explicit cancellation."""

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable

from core.events.hook import EventHook
from core.models.pet import TaskRecord, TaskResult

logger = logging.getLogger(__name__)


class TaskQueue:
    def __init__(self) -> None:
        self.task_started: EventHook[[str]] = EventHook()
        self.task_completed: EventHook[[str, TaskResult]] = EventHook()
        self.queue_updated: EventHook[[int]] = EventHook()
        self._queue: deque[TaskRecord] = deque()
        self._queue_length = 0
        self._current_task: TaskRecord | None = None
        self._is_running = False
        self._task_executor: Callable[[TaskRecord], Awaitable[TaskResult]] | None = None
        self._shutdown = False
        self._processor_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def set_executor(self, executor: Callable[[TaskRecord], Awaitable[TaskResult]]) -> None:
        self._task_executor = executor

    async def add_task(self, task: TaskRecord) -> int:
        async with self._lock:
            if self._shutdown:
                return 0
            self._queue.append(task)
            self._queue_length = len(self._queue)
            self.queue_updated.emit(self._queue_length)
            if not self._is_running and (
                self._processor_task is None or self._processor_task.done()
            ):
                self._processor_task = asyncio.create_task(self._process_queue())
            return self._queue_length

    async def _process_queue(self) -> None:
        async with self._lock:
            if self._is_running:
                return
            self._is_running = True
        try:
            while True:
                async with self._lock:
                    if self._shutdown or not self._queue:
                        break
                    task = self._queue.popleft()
                    self._current_task = task
                    self._queue_length = len(self._queue)
                    self.queue_updated.emit(self._queue_length)
                try:
                    task.start()
                    self.task_started.emit(task.id)
                    if self._task_executor is None:
                        raise RuntimeError("Task executor is not configured")
                    result = await self._task_executor(task)
                except asyncio.CancelledError:
                    task.cancel()
                    self.task_completed.emit(task.id, self._cancelled_result(task.id))
                    raise
                except Exception as error:  # noqa: BLE001 - each queued task owns its failure.
                    logger.error("Task executor failed: %s", type(error).__name__)
                    result = TaskResult(
                        task_id=task.id,
                        success=False,
                        summary="执行失败",
                        error_message=type(error).__name__,
                    )
                self.task_completed.emit(task.id, result)
                self._current_task = None
        finally:
            async with self._lock:
                self._is_running = False
                self._current_task = None
                if self._queue and not self._shutdown:
                    self._processor_task = asyncio.create_task(self._process_queue())

    @staticmethod
    def _cancelled_result(task_id: str) -> TaskResult:
        return TaskResult(
            task_id=task_id,
            success=False,
            cancelled=True,
            summary="任务已取消",
            error_message="任务已取消",
        )

    async def cancel_pending(self, task_id: str) -> bool:
        async with self._lock:
            task = next((item for item in self._queue if item.id == task_id), None)
            if task is None:
                return False
            self._queue.remove(task)
            task.cancel()
            self._queue_length = len(self._queue)
            self.queue_updated.emit(self._queue_length)
        self.task_completed.emit(task.id, self._cancelled_result(task.id))
        return True

    async def stop(self) -> None:
        async with self._lock:
            self._shutdown = True
            pending = list(self._queue)
            self._queue.clear()
            self._queue_length = 0
            self.queue_updated.emit(0)
            processor = self._processor_task
        for task in pending:
            task.cancel()
            self.task_completed.emit(task.id, self._cancelled_result(task.id))
        if processor and not processor.done():
            processor.cancel()
            try:
                await asyncio.wait_for(processor, timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                logger.debug("Queue processor stopped")

    def get_queue_length(self) -> int:
        return self._queue_length

    async def clear(self) -> None:
        for task in list(self._queue):
            await self.cancel_pending(task.id)
