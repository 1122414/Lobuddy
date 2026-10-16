"""Tests for TaskQueue concurrency and race conditions."""

import asyncio
from unittest.mock import AsyncMock

import pytest


from core.models.pet import TaskRecord, TaskResult
from core.tasks.task_queue import TaskQueue


class TestTaskQueueConcurrency:
    def test_concurrent_add_tasks(self):
        queue = TaskQueue()
        queue.set_executor(AsyncMock(return_value=TaskResult(
            task_id="dummy",
            success=True,
            raw_result="ok",
            summary="done",
        )))

        async def run_test():
            tasks = [TaskRecord(id=f"task-{i}", input_text=f"test {i}") for i in range(10)]
            results = await asyncio.gather(*[queue.add_task(t) for t in tasks])
            assert all(r > 0 for r in results)
            await asyncio.sleep(0.2)
            assert queue.get_queue_length() == 0

        asyncio.run(run_test())

    def test_stop_cancels_pending(self):
        queue = TaskQueue()
        queue.set_executor(AsyncMock())

        async def run_test():
            task = TaskRecord(id="task-1", input_text="test")
            await queue.add_task(task)
            await queue.stop()
            assert queue.get_queue_length() == 0

        asyncio.run(run_test())

    def test_only_one_processor_task(self):
        queue = TaskQueue()
        queue.set_executor(AsyncMock(return_value=TaskResult(
            task_id="dummy",
            success=True,
            raw_result="ok",
            summary="done",
        )))

        async def run_test():
            for i in range(5):
                await queue.add_task(TaskRecord(id=f"task-{i}", input_text=f"test {i}"))
            await asyncio.sleep(0.2)
            assert queue.get_queue_length() == 0

        asyncio.run(run_test())

