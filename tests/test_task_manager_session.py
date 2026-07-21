"""Tests for TaskManager session attribution."""

import asyncio
import sys
from unittest.mock import MagicMock, patch, AsyncMock

_original_nanobot = sys.modules.get("nanobot")
_original_nanobot_bus = sys.modules.get("nanobot.bus")
_original_nanobot_bus_events = sys.modules.get("nanobot.bus.events")
_original_pyside = sys.modules.get("PySide6")
_original_pyside_qtcore = sys.modules.get("PySide6.QtCore")

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
from core.events import (
    ComputerUseProgress,
    MemoryContextPrepared,
    TaskFailed,
    ToolCallExecuted,
    ToolCallPlanned,
)
from core.models.pet import TaskResult, TaskStatus
from core.storage.db import init_database

for k, mod in [
    ("nanobot", _original_nanobot),
    ("nanobot.bus", _original_nanobot_bus),
    ("nanobot.bus.events", _original_nanobot_bus_events),
    ("PySide6", _original_pyside),
    ("PySide6.QtCore", _original_pyside_qtcore),
]:
    if mod is not None:
        sys.modules[k] = mod
    else:
        sys.modules.pop(k, None)


def run_async(coro):
    return asyncio.run(coro)


class TestTaskManagerSessionAttribution:
    def setup_method(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        init_database(settings)

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

    def test_safe_stop_is_not_published_as_task_failure(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        manager = TaskManager(settings)
        manager.queue._is_running = True
        task_id = run_async(manager.submit_task("prepare a release", "session-a"))
        manager._on_task_started(task_id)
        manager.queue._queue.clear()
        manager.queue._queue_length = 0
        failures = []
        pet_states = []
        manager.event_bus.subscribe(TaskFailed, failures.append)
        manager.pet_state_changed.connect(pet_states.append)

        manager.queue.task_completed.emit(
            task_id,
            TaskResult(
                task_id=task_id,
                success=False,
                summary="任务已安全暂停",
                cancelled=True,
            ),
        )

        assert manager.get_task_run(task_id).status == TaskStatus.CANCELLED
        assert failures == []
        assert pet_states[-1] == TaskStatus.IDLE

    def test_queue_stop_persists_waiting_runs_as_cancelled(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        manager = TaskManager(settings)
        manager.queue._is_running = True
        task_ids = [
            run_async(manager.submit_task("prepare notes", "session-a")),
            run_async(manager.submit_task("review notes", "session-a")),
        ]

        run_async(manager.queue.stop())

        assert [manager.get_task_run(task_id).status for task_id in task_ids] == [
            TaskStatus.CANCELLED,
            TaskStatus.CANCELLED,
        ]
        assert all(manager.get_task_run(task_id).retryable for task_id in task_ids)

    def test_computer_use_progress_is_bridged_to_qt_signal(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        manager = TaskManager(settings)
        received = []
        manager.computer_use_progress.connect(received.append)
        event = ComputerUseProgress(
            task_id="task-1",
            plan_id="plan-1",
            phase="observed",
            step_key="observe-1",
            title="观察并定位当前界面",
        )

        manager.event_bus.publish(event)

        assert received == [event]

    def test_memory_context_evidence_is_bridged_without_memory_content(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        manager = TaskManager(settings)
        received = []
        manager.memory_context_prepared.connect(received.append)
        event = MemoryContextPrepared(
            task_id="task-1",
            session_id="session-a",
            selected_count=2,
            type_counts={"user_profile": 1, "procedural_memory": 1},
            total_chars=320,
        )

        manager.event_bus.publish(event)

        assert received == [event]
        assert not hasattr(event, "content")
        assert not hasattr(event, "titles")

    def test_tool_timing_events_become_durable_work_stages(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        manager = TaskManager(settings)
        manager.queue._is_running = True

        with patch.object(manager.adapter, "run_task", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                success=True,
                raw_output="ok",
                summary="done",
                error_message=None,
            )
            task_id = run_async(manager.submit_task("read the project file", "session-a"))
        manager._on_task_started(task_id)
        planned = ToolCallPlanned(
            task_id=task_id,
            tool_name="read_file",
            call_id="call-1",
            stage_key="tool:read_file:call-1",
        )
        completed = ToolCallExecuted(
            task_id=task_id,
            tool_name="read_file",
            success=True,
            duration_ms=1250,
            call_id="call-1",
            stage_key="tool:read_file:call-1",
        )

        manager.event_bus.publish(planned)
        manager.event_bus.publish(completed)
        stage = manager.task_runs.snapshot(task_id).stages[-1]

        assert stage.title == "已完成：读取文件"
        assert stage.duration_ms == 1250
        assert "project file" not in stage.detail

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

    def test_failed_task_does_not_award_exp(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        manager = TaskManager(settings)
        manager.queue._is_running = True

        with patch.object(manager.adapter, "run_task", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                success=False, raw_output="", summary="failed", error_message="error"
            )
            task_id = run_async(manager.submit_task("hello", "session-a"))

        pet = manager.pet_repo.get_or_create_pet()
        initial_exp = pet.exp

        received_exp = []

        def exp_slot(amount, current_exp, required_exp, level_up):
            received_exp.append((amount, current_exp, required_exp, level_up))

        manager.pet_exp_gained.connect(exp_slot)
        manager.queue.task_completed.emit(
            task_id, MagicMock(success=False, summary="failed", error_message="error")
        )

        assert len(received_exp) == 1
        assert received_exp[0][0] == 0
        pet_after = manager.pet_repo.get_or_create_pet()
        assert pet_after.exp == initial_exp

    def test_failed_task_does_not_unlock_abilities_or_change_personality(self):
        settings = Settings(llm_api_key="test", llm_model="kimi")
        manager = TaskManager(settings)
        manager.queue._is_running = True

        with patch.object(manager.adapter, "run_task", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                success=False, raw_output="", summary="failed", error_message="error"
            )
            task_id = run_async(manager.submit_task("hello", "session-a"))

        pet = manager.pet_repo.get_or_create_pet()
        initial_personality = pet.personality.model_dump_json()

        unlocked = []
        personality_changes = []

        def ability_slot(level, evolution_stage):
            unlocked.append((level, evolution_stage))

        def personality_slot(adjustments):
            personality_changes.append(adjustments)

        manager.ability_unlocked.connect(ability_slot)
        manager.pet_personality_changed.connect(personality_slot)
        manager.queue.task_completed.emit(
            task_id, MagicMock(success=False, summary="failed", error_message="error")
        )

        assert len(unlocked) == 0
        assert len(personality_changes) == 0
        pet_after = manager.pet_repo.get_or_create_pet()
        assert pet_after.personality.model_dump_json() == initial_personality
