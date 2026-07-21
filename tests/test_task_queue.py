"""Tests for TaskQueue concurrency and race conditions."""

import asyncio
import sys
from unittest.mock import AsyncMock



class _SignalInstance:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in self._slots:
            slot(*args)


class _Signal:
    def __init__(self, *types):
        pass

    def __get__(self, instance, owner):
        if instance is None:
            return self
        attr_name = "_signal_inst_" + str(id(self))
        if not hasattr(instance, attr_name):
            setattr(instance, attr_name, _SignalInstance())
        return getattr(instance, attr_name)


class _QObject:
    def __init__(self, *args, **kwargs):
        pass


_pyside = type(sys)("PySide6")
_pyside.QtCore = type(sys)("QtCore")
_pyside.QtCore.QObject = _QObject
_pyside.QtCore.Signal = _Signal
sys.modules["PySide6"] = _pyside
sys.modules["PySide6.QtCore"] = _pyside.QtCore

from core.models.pet import TaskRecord, TaskResult
from core.tasks.task_queue import TaskQueue


async def _wait_until_idle(queue: TaskQueue, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while queue._is_running or queue.get_queue_length():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("TaskQueue did not become idle")
        await asyncio.sleep(0.01)


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

    def test_worker_is_reserved_atomically_for_concurrent_enqueues(self):
        queue = TaskQueue()
        processor_starts = 0
        original_processor = queue._process_queue

        async def counted_processor():
            nonlocal processor_starts
            processor_starts += 1
            await original_processor()

        async def executor(task):
            await asyncio.sleep(0)
            return TaskResult(task_id=task.id, success=True, summary="done")

        queue._process_queue = counted_processor
        queue.set_executor(executor)

        async def run_test():
            tasks = [TaskRecord(id=f"reserved-{i}", input_text="test") for i in range(20)]
            await asyncio.gather(*(queue.add_task(task) for task in tasks))
            assert queue._is_running is True
            await _wait_until_idle(queue)
            assert processor_starts == 1

        asyncio.run(run_test())

    def test_stop_safe_stops_current_and_pending_tasks(self):
        queue = TaskQueue()
        started = None
        completed = []
        queue.task_completed.connect(lambda task_id, result: completed.append((task_id, result)))

        async def run_test():
            nonlocal started
            started = asyncio.Event()

            async def executor(_task):
                started.set()
                await asyncio.Event().wait()

            queue.set_executor(executor)
            await queue.add_task(TaskRecord(id="current", input_text="test"))
            await started.wait()
            await queue.add_task(TaskRecord(id="pending", input_text="test"))
            await queue.stop()

            assert queue.get_queue_length() == 0
            assert queue._is_running is False
            assert queue._processor_task is None
            assert {task_id for task_id, _result in completed} == {"current", "pending"}
            assert all(result.cancelled for _task_id, result in completed)
            assert all(not result.success for _task_id, result in completed)

        asyncio.run(run_test())

    def test_immediate_stop_releases_a_reserved_but_unstarted_worker(self):
        queue = TaskQueue()
        completed = []
        queue.task_completed.connect(lambda task_id, result: completed.append((task_id, result)))

        async def run_test():
            await queue.add_task(TaskRecord(id="not-started", input_text="test"))
            await queue.stop()

            assert [(task_id, result.cancelled) for task_id, result in completed] == [
                ("not-started", True)
            ]
            assert queue._is_running is False
            assert queue._processor_task is None

        asyncio.run(run_test())

    def test_other_work_distinguishes_current_from_another_completion(self):
        queue = TaskQueue()
        queue._current_task = TaskRecord(id="active", input_text="test")

        assert queue.has_other_work("active") is False
        assert queue.has_other_work("pending") is True
        queue._queue_length = 1
        assert queue.has_other_work("active") is True

    def test_executor_result_cannot_escape_its_task_run(self):
        queue = TaskQueue()
        completed = []
        queue.task_completed.connect(lambda task_id, result: completed.append((task_id, result)))
        queue.set_executor(
            AsyncMock(
                return_value=TaskResult(
                    task_id="another-task",
                    success=True,
                    summary="wrong owner",
                )
            )
        )

        async def run_test():
            await queue.add_task(TaskRecord(id="owned-task", input_text="test"))
            await _wait_until_idle(queue)

            assert len(completed) == 1
            emitted_task_id, result = completed[0]
            assert emitted_task_id == "owned-task"
            assert result.task_id == "owned-task"
            assert result.success is False
            assert "another Task Run" in result.error_message

        asyncio.run(run_test())


for _mod in list(sys.modules.keys()):
    if _mod.startswith('PySide6'):
        del sys.modules[_mod]

