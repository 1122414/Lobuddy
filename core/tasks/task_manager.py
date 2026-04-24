"""Task manager for Lobuddy."""

import threading
import uuid
from typing import Any

from PySide6.QtCore import QObject, Signal

from core.config import Settings
from core.agent.nanobot_adapter import NanobotAdapter
from core.models.pet import PetProgressEvent, TaskDifficulty, TaskRecord, TaskResult, TaskStatus
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
        self.queue = TaskQueue()
        self._task_context: dict[str, dict[str, Any]] = {}
        self._task_session_map: dict[str, str] = {}
        self._lock = threading.Lock()

        self.queue.set_executor(self._execute_task)
        self.queue.task_started.connect(self._on_task_started)
        self.queue.task_completed.connect(self._on_task_completed)

    @staticmethod
    def _determine_task_difficulty(input_text: str) -> tuple[TaskDifficulty, int]:
        """Auto-determine task difficulty based on input characteristics.

        Returns:
            Tuple of (difficulty, reward_exp)
        """
        text = input_text.strip().lower()
        length = len(text)

        complex_keywords = [
            "代码", "code", "程序", "program", "脚本", "script",
            "分析", "analyze", "分析", "analysis",
            "优化", "optimize", "重构", "refactor",
            "设计", "design", "架构", "architecture",
            "实现", "implement", "开发", "develop",
            "比较", "compare", "对比", "versus", "vs",
            "解释", "explain", "详细", "detail",
        ]
        medium_keywords = [
            "搜索", "search", "查找", "find",
            "总结", "summarize", "概括", "summary",
            "转换", "convert", "翻译", "translate",
            "修复", "fix", "调试", "debug",
            "创建", "create", "生成", "generate",
            "写", "write", "撰写", "compose",
        ]

        complex_score = sum(1 for kw in complex_keywords if kw in text)
        medium_score = sum(1 for kw in medium_keywords if kw in text)

        if length > 200 or complex_score >= 2 or (complex_score >= 1 and length > 100):
            return TaskDifficulty.COMPLEX, 30
        elif length > 80 or medium_score >= 2 or complex_score == 1 or medium_score >= 1:
            return TaskDifficulty.MEDIUM, 15
        else:
            return TaskDifficulty.SIMPLE, 5

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

        difficulty, reward_exp = self._determine_task_difficulty(stripped)

        task = TaskRecord(
            id=task_id,
            input_text=input_text,
            task_type="general",
            status=TaskStatus.QUEUED,
            difficulty=difficulty,
            reward_exp=reward_exp,
        )

        self.repo.create_task(task)
        with self._lock:
            self._task_context[task_id] = {
                "session_id": session_id,
                "image_path": image_path,
            }
            self._task_session_map[task_id] = session_id
        await self.queue.add_task(task)

        return task_id

    async def _execute_task(self, task: TaskRecord) -> TaskResult:
        """Execute single task via nanobot."""
        with self._lock:
            context = self._task_context.pop(task.id, {})
        session_id = context.get("session_id", task.id)

        session_key = self.adapter.build_session_key(session_id)

        pet = self.pet_repo.get_or_create_pet()
        agent_result = await self.adapter.run_task(
            task.input_text,
            session_key,
            pet_state=self._build_pet_state(pet),
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

    @staticmethod
    def _build_pet_state(pet):
        return {
            "name": pet.name,
            "level": pet.level,
            "exp": pet.exp,
            "exp_for_next_level": pet.get_exp_for_next_level(),
            "evolution_stage": pet.evolution_stage.value,
        }

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
            event = self._pet_progress.process_task_completion(task, result)
            self._emit_progress(event)

        with self._lock:
            session_id = self._task_session_map.pop(task_id, "")
        error_message = result.error_message or ""
        self.task_completed.emit(task_id, session_id, result.success, result.summary, error_message)

        if self.queue.get_queue_length() == 0:
            self.pet_state_changed.emit(TaskStatus.IDLE if result.success else TaskStatus.FAILED)

    def _emit_progress(self, event: PetProgressEvent):
        self.pet_exp_gained.emit(
            event.exp_gained, event.current_exp, event.required_exp, event.level_up
        )
        if event.level_up:
            self.pet_level_up.emit(event.new_level, event.new_stage)
        if event.personality_adjustments:
            self.pet_personality_changed.emit(event.personality_adjustments)
        for ability_id, ability_name in event.unlocked_abilities:
            self.ability_unlocked.emit(ability_id, ability_name)
