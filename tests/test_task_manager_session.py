"""Tests for TaskManager session attribution."""

import asyncio
import sys
from unittest.mock import MagicMock, patch, AsyncMock

sys.modules["nanobot"] = MagicMock()
sys.modules["nanobot.bus"] = MagicMock()
sys.modules["nanobot.bus.events"] = MagicMock()


class _SignalInstance:
    def __init__(self):
        self._slots: list = []

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


_pyside = MagicMock()
_pyside.QtCore.QObject = _QObject
_pyside.QtCore.Signal = _Signal
sys.modules["PySide6"] = _pyside
sys.modules["PySide6.QtCore"] = _pyside.QtCore

from core.tasks.task_manager import TaskManager
from app.config import Settings


def run_async(coro):
    return asyncio.run(coro)


class TestTaskManagerSessionAttribution:
    def test_task_completed_includes_original_session_id(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        manager = TaskManager(settings)
        manager.queue._is_running = True

        with patch.object(manager.adapter, "run_task", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                success=True, raw_output="ok", summary="done", error_message=None
            )
            task_id = run_async(manager.submit_task("hello", "session-a"))

        received = []

        def slot(task_id_out, session_id_out, success, summary, error):
            received.append((task_id_out, session_id_out, success, summary, error))

        manager.task_completed.connect(slot)
        # Trigger completion manually via queue callback
        manager.queue.task_completed.emit(
            task_id, MagicMock(success=True, summary="done", error_message=None)
        )

        assert len(received) == 1
        assert received[0][1] == "session-a"

    def test_session_id_preserved_when_panel_switches(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        manager = TaskManager(settings)
        manager.queue._is_running = True

        with patch.object(manager.adapter, "run_task", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                success=True, raw_output="ok", summary="done", error_message=None
            )
            task_id_a = run_async(manager.submit_task("hello", "session-a"))
            task_id_b = run_async(manager.submit_task("hi", "session-b"))

        received = []

        def slot(task_id_out, session_id_out, success, summary, error):
            received.append((task_id_out, session_id_out))

        manager.task_completed.connect(slot)
        manager.queue.task_completed.emit(
            task_id_a, MagicMock(success=True, summary="done", error_message=None)
        )
        manager.queue.task_completed.emit(
            task_id_b, MagicMock(success=True, summary="done", error_message=None)
        )

        session_ids = {r[1] for r in received}
        assert session_ids == {"session-a", "session-b"}

    def test_task_session_map_cleaned_up_after_completion(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        manager = TaskManager(settings)
        manager.queue._is_running = True

        with patch.object(manager.adapter, "run_task", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                success=True, raw_output="ok", summary="done", error_message=None
            )
            task_id = run_async(manager.submit_task("hello", "session-a"))

        assert task_id in manager._task_session_map
        manager.queue.task_completed.emit(
            task_id, MagicMock(success=True, summary="done", error_message=None)
        )
        assert task_id not in manager._task_session_map
