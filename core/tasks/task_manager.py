"""Task manager for Lobuddy."""

import threading
import uuid
from datetime import datetime

from typing import Any

from PySide6.QtCore import QObject, Signal

from core.config import Settings
from core.agent.nanobot_adapter import NanobotAdapter
from core.models.pet import TaskDifficulty, TaskRecord, TaskResult, TaskStatus
from core.services.pet_progress_service import PetProgressService
from core.storage.pet_repo import PetRepository
from core.storage.task_repo import TaskRepository
from core.tasks.task_queue import TaskQueue



class TaskManager(QObject):
    """Manages task lifecycle and execution."""

    task_started = Signal(str)
    task_completed = Signal(str, str, bool, str, str)
    pet_state_changed = Signal(TaskStatus)
    pet_exp_gained = Signal(int, int, int, bool)
    pet_level_up = Signal(int, int)
    pet_personality_changed = Signal(dict)
    ability_unlocked = Signal(str, str)

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.adapter = NanobotAdapter(settings)
        self.repo = TaskRepository()
        self.pet_repo = PetRepository()
        self._pet_progress = PetProgressService()
        self._wire_pet_progress_signals()
        self.queue = TaskQueue()
        self._task_context: dict[str, dict[str, Any]] = {}
        self._task_session_map: dict[str, str] = {}
        self._lock = threading.Lock()

        self.queue.set_executor(self._execute_task)
        self.queue.task_started.connect(self._on_task_started)
        self.queue.task_completed.connect(self._on_task_completed)

    def _wire_pet_progress_signals(self):
        """Forward pet progress signals to TaskManager."""
        self._pet_progress.pet_exp_gained.connect(self.pet_exp_gained.emit)
        self._pet_progress.pet_level_up.connect(self.pet_level_up.emit)
        self._pet_progress.pet_personality_changed.connect(self.pet_personality_changed.emit)
        self._pet_progress.ability_unlocked.connect(self.ability_unlocked.emit)

    async def submit_task(
        self,
        input_text: str,
        session_id: str,
        image_path: str = "",
    ) -> str:
        """Submit new task and return task ID."""
        stripped = input_text.strip()
        if not stripped:
            raise ValueError("input_text cannot be empty")
        if len(stripped) > 4000:
            raise ValueError("input_text exceeds maximum length of 4000")
        if not session_id.strip():
            raise ValueError("session_id cannot be empty")
        if len(session_id) > 128:
            raise ValueError("session_id exceeds maximum length of 128")
        if len(image_path) > 512:
            raise ValueError("image_path exceeds maximum length of 512")

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
        with self._lock:
            self._task_context[task_id] = {
                "session_id": session_id,
                "image_path": image_path,
            }
            self._task_session_map[task_id] = session_id
        position = await self.queue.add_task(task)

        return task_id

    async def _execute_task(self, task: TaskRecord) -> TaskResult:
        """Execute single task via nanobot."""
        with self._lock:
            context = self._task_context.pop(task.id, {})
        session_id = context.get("session_id", task.id)

        session_key = self.adapter.build_session_key(session_id)

        # Get current pet state for AI context
        pet = self.pet_repo.get_or_create_pet()
        pet_state = {
            "name": pet.name,
            "level": pet.level,
            "exp": pet.exp,
            "exp_for_next_level": pet.get_exp_for_next_level(),
            "evolution_stage": pet.evolution_stage.value
            if hasattr(pet.evolution_stage, "value")
            else str(pet.evolution_stage),
        }

        agent_result = await self.adapter.run_task(
            task.input_text,
            session_key,
            pet_state=pet_state,
            image_path=context.get("image_path"),
        )

        task_result = TaskResult(
            task_id=task.id,
            success=agent_result.success,
            raw_result=agent_result.raw_output,
            summary=agent_result.summary,
            error_message=agent_result.error_message,
        )

        task.complete(agent_result.success)

        self.repo.save_result_and_status(
            task_result,
            task.status,
            task.finished_at,
        )

        return task_result

    def _on_task_started(self, task_id: str):
        """Handle task start."""
        self.task_started.emit(task_id)
        self.pet_state_changed.emit(TaskStatus.RUNNING)

        task = self.repo.get_task(task_id)
        if task:
            task.start()
            self.repo.update_task_status(
                task_id,
                TaskStatus.RUNNING,
                started_at=task.started_at,
            )

    def _on_task_completed(self, task_id: str, result: TaskResult):
        """Handle task completion - award EXP and evolve personality."""
        task = self.repo.get_task(task_id)
        if task:
            self._pet_progress.process_task_completion(task, result)

        with self._lock:
            session_id = self._task_session_map.pop(task_id, "")
        error_message = result.error_message or ""
        self.task_completed.emit(task_id, session_id, result.success, result.summary, error_message)

        if self.queue.get_queue_length() == 0:
            if result.success:
                self.pet_state_changed.emit(TaskStatus.IDLE)
            else:
                self.pet_state_changed.emit(TaskStatus.FAILED)
