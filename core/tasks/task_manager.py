"""Task manager for Lobuddy."""

import uuid
from datetime import datetime

from typing import Any

from PySide6.QtCore import QObject, Signal

from app.config import Settings
from core.agent.nanobot_adapter import NanobotAdapter
from core.models.pet import TaskDifficulty, TaskRecord, TaskResult, TaskStatus
from core.abilities.ability_system import AbilityManager
from core.models.personality import PetPersonality
from core.personality.personality_engine import PersonalityEngine
from core.storage.pet_repo import PetRepository
from core.storage.task_repo import TaskRepository
from core.tasks.task_queue import TaskQueue


class TaskManager(QObject):
    """Manages task lifecycle and execution."""

    task_started = Signal(str)
    task_completed = Signal(str, str, bool, str, str)
    pet_state_changed = Signal(TaskStatus)
    pet_exp_gained = Signal(int, int, int, bool)  # amount, current_exp, required_exp, level_up
    pet_level_up = Signal(int, int)
    pet_personality_changed = Signal(dict)
    ability_unlocked = Signal(str, str)  # level, evolution_stage

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.adapter = NanobotAdapter(settings)
        self.repo = TaskRepository()
        self.pet_repo = PetRepository()
        self.ability_manager = AbilityManager()
        self.queue = TaskQueue()
        self._task_context: dict[str, dict[str, Any]] = {}
        self._task_session_map: dict[str, str] = {}
        self._tasks_completed_count = 0

        self.queue.set_executor(self._execute_task)
        self.queue.task_started.connect(self._on_task_started)
        self.queue.task_completed.connect(self._on_task_completed)

    async def submit_task(
        self,
        input_text: str,
        session_id: str,
        image_path: str = "",
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
            "image_path": image_path,
        }
        self._task_session_map[task_id] = session_id
        position = self.queue.add_task(task)

        return task_id

    async def _execute_task(self, task: TaskRecord) -> TaskResult:
        """Execute single task via nanobot."""
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
        """Handle task completion - award EXP and evolve personality."""
        task = self.repo.get_task(task_id)
        if task:
            pet = self.pet_repo.get_or_create_pet()

            # Award EXP
            level_up = pet.add_exp(task.reward_exp)
            self.pet_repo.save_pet(pet)

            # Emit EXP notification signals
            required_exp = pet.get_exp_for_next_level()
            self.pet_exp_gained.emit(task.reward_exp, pet.exp, required_exp, level_up)
            if level_up:
                self.pet_level_up.emit(pet.level, pet.evolution_stage.value)

            # Evolve personality based on task content
            personality = pet.personality if hasattr(pet, "personality") else PetPersonality()
            adjustments = PersonalityEngine.analyze_task(task, personality)
            if adjustments:
                PersonalityEngine.apply_adjustments(personality, adjustments)
                pet.personality = personality
                self.pet_repo.save_pet(pet)
                self.pet_personality_changed.emit(adjustments)

            # Check for ability unlocks
            self._tasks_completed_count += 1
            unlocked = self.ability_manager.check_and_unlock(
                pet, personality, self._tasks_completed_count
            )
            for ability in unlocked:
                self.ability_unlocked.emit(ability.id, ability.name)

        session_id = self._task_session_map.pop(task_id, "")
        error_message = result.error_message or ""
        self.task_completed.emit(task_id, session_id, result.success, result.summary, error_message)

        if self.queue.get_queue_length() == 0:
            if result.success:
                self.pet_state_changed.emit(TaskStatus.IDLE)
            else:
                self.pet_state_changed.emit(TaskStatus.FAILED)
