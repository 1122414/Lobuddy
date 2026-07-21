"""Task manager for Lobuddy."""

import threading
import uuid
from typing import Any

from PySide6.QtCore import QObject, Signal

from core.config import Settings
from core.agent.nanobot_adapter import NanobotAdapter
from core.events import (
    ComputerUseProgress,
    HitlApproved,
    HitlDenied,
    HitlRequested,
    HitlTimeout,
    MemoryContextPrepared,
    TaskCompleted as TaskCompletedEvent,
    TaskFailed as TaskFailedEvent,
    TaskQueued as TaskQueuedEvent,
    TaskStarted as TaskStartedEvent,
    ToolCallBlocked,
    ToolCallExecuted,
    ToolCallPlanned,
)
from core.models.pet import PetProgressEvent, TaskDifficulty, TaskRecord, TaskResult, TaskStatus
from core.models.model_usage import ModelUsageEvidence
from core.services.pet_progress_service import PetProgressService
from core.storage.pet_repo import PetRepository
from core.storage.task_repo import TaskRepository
from core.tasks.task_queue import TaskQueue
from core.tasks.task_recovery_service import TaskRecoveryService
from core.tasks.task_run_service import TaskRunService
from core.logging.trace import get_logger

task_log = get_logger("task")


class TaskManager(QObject):
    """Manages task lifecycle and execution."""

    task_started = Signal(str)
    task_completed = Signal(str, str, bool, str, str)
    pet_state_changed = Signal(TaskStatus)
    pet_exp_gained = Signal(int, int, int, bool)
    pet_level_up = Signal(int, int)
    pet_personality_changed = Signal(dict)
    ability_unlocked = Signal(str, str)
    computer_use_progress = Signal(object)
    memory_context_prepared = Signal(object)
    task_run_updated = Signal(object)

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.adapter = NanobotAdapter(settings)
        self.event_bus = self.adapter.event_bus
        self.event_bus.subscribe(ComputerUseProgress, self._on_computer_use_progress)
        self.event_bus.subscribe(MemoryContextPrepared, self._on_memory_context_prepared)
        self.event_bus.subscribe(ToolCallPlanned, self._on_tool_call_planned)
        self.event_bus.subscribe(ToolCallExecuted, self._on_tool_call_executed)
        self.event_bus.subscribe(ToolCallBlocked, self._on_tool_call_blocked)
        self.event_bus.subscribe(HitlRequested, self._on_hitl_requested)
        self.event_bus.subscribe(HitlApproved, self._on_hitl_approved)
        self.event_bus.subscribe(HitlDenied, self._on_hitl_denied)
        self.event_bus.subscribe(HitlTimeout, self._on_hitl_timeout)
        self.repo = TaskRepository()
        self.task_runs = TaskRunService(settings, self.repo)
        self.task_recovery = TaskRecoveryService(settings, self.task_runs)
        self._interrupted_runs = self.task_runs.interrupt_incomplete()
        self._revoked_startup_grants = self.task_recovery.invalidate_process_grants()
        self.pet_repo = PetRepository()
        self._pet_progress = PetProgressService()
        self.queue = TaskQueue()
        self._task_context: dict[str, dict[str, Any]] = {}
        self._task_session_map: dict[str, str] = {}
        self._task_evolution_map: dict[str, str] = {}
        self._lock = threading.Lock()

        self.queue.set_executor(self._execute_task)
        self.queue.task_started.connect(self._on_task_started)
        self.queue.task_completed.connect(self._on_task_completed)

    def update_settings(self, settings: Settings) -> None:
        """Keep Task Run and recovery policy in sync with live settings."""
        self.settings = settings
        self.task_runs.update_settings(settings)
        self.task_recovery.update_settings(settings)

    @staticmethod
    def _determine_task_difficulty(input_text: str) -> tuple[TaskDifficulty, int]:
        """Auto-determine task difficulty based on input characteristics.

        Returns:
            Tuple of (difficulty, reward_exp)
        """
        text = input_text.strip().lower()
        length = len(text)

        complex_keywords = [
            "代码",
            "code",
            "程序",
            "program",
            "脚本",
            "script",
            "分析",
            "analyze",
            "分析",
            "analysis",
            "优化",
            "optimize",
            "重构",
            "refactor",
            "设计",
            "design",
            "架构",
            "architecture",
            "实现",
            "implement",
            "开发",
            "develop",
            "比较",
            "compare",
            "对比",
            "versus",
            "vs",
            "解释",
            "explain",
            "详细",
            "detail",
        ]
        medium_keywords = [
            "搜索",
            "search",
            "查找",
            "find",
            "总结",
            "summarize",
            "概括",
            "summary",
            "转换",
            "convert",
            "翻译",
            "translate",
            "修复",
            "fix",
            "调试",
            "debug",
            "创建",
            "create",
            "生成",
            "generate",
            "写",
            "write",
            "撰写",
            "compose",
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
        if not stripped and image_path:
            stripped = "请描述这张图片，并指出你认为最重要的信息。"
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
            input_text=stripped,
            task_type="general",
            status=TaskStatus.QUEUED,
            difficulty=difficulty,
            reward_exp=reward_exp,
            session_id=session_id,
            has_image=bool(image_path),
        )

        snapshot = self.task_runs.create(task)
        with self._lock:
            self._task_context[task_id] = {
                "session_id": session_id,
                "image_path": image_path,
            }
            self._task_session_map[task_id] = session_id
        position = await self.queue.add_task(task)
        if position <= 0:
            with self._lock:
                self._task_context.pop(task_id, None)
                self._task_session_map.pop(task_id, None)
            unavailable = TaskResult(
                task_id=task_id,
                success=False,
                summary="任务队列已停止，未开始执行",
                error_message="Task queue is unavailable",
            )
            failed_snapshot = self.task_runs.complete(task_id, unavailable)
            self.task_run_updated.emit(failed_snapshot)
            raise RuntimeError("Task queue is unavailable")
        self.task_run_updated.emit(snapshot)

        self.event_bus.publish(TaskQueuedEvent(task_id=task_id, session_id=session_id))

        task_log.info(
            "Task queued — id=%s, session=%s, difficulty=%s, exp_reward=%d, input_len=%d",
            task_id,
            session_id,
            difficulty.name,
            reward_exp,
            len(stripped),
        )
        return task_id

    async def _execute_task(self, task: TaskRecord) -> TaskResult:
        """Execute single task via nanobot."""
        with self._lock:
            context = self._task_context.pop(task.id, {})
        session_id = context.get("session_id", task.session_id or task.id)

        session_key = self.adapter.build_session_key(session_id)

        import logging

        logger = logging.getLogger("lobuddy.task_manager")
        logger.info(f"[chat] current_session_id={session_id}")
        logger.info(f"[chat] session_key={session_key}")
        task_log.info(
            "Task executing — id=%s, session=%s, prompt_len=%d",
            task.id,
            session_id,
            len(task.input_text),
        )

        pet = self.pet_repo.get_or_create_pet()
        agent_result = await self.adapter.run_task(
            task.input_text,
            session_key,
            pet_state=self._build_pet_state(pet),
            image_path=context.get("image_path"),
            task_id=task.id,
        )
        evolution_candidate_id = getattr(
            agent_result,
            "evolution_candidate_id",
            None,
        )
        if evolution_candidate_id:
            with self._lock:
                self._task_evolution_map[task.id] = evolution_candidate_id
        usage_evidence = getattr(agent_result, "usage_evidence", None)

        task_result = TaskResult(
            task_id=task.id,
            success=agent_result.success,
            raw_result=agent_result.raw_output,
            summary=agent_result.summary,
            error_message=agent_result.error_message,
            usage_evidence=(
                usage_evidence
                if isinstance(usage_evidence, ModelUsageEvidence)
                else ModelUsageEvidence()
            ),
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
        snapshot = self.task_runs.start(task_id)
        self.task_started.emit(task_id)
        self.task_run_updated.emit(snapshot)
        self.pet_state_changed.emit(TaskStatus.RUNNING)
        task_log.info("Task started signal — id=%s", task_id)

        self.event_bus.publish(TaskStartedEvent(task_id=task_id))

    def _on_computer_use_progress(self, event: ComputerUseProgress) -> None:
        """Bridge pure domain progress into Qt's cross-thread signal delivery."""
        try:
            snapshot = self.task_runs.progress(
                event.task_id,
                key=event.step_key,
                title=event.title,
                detail=event.detail,
                status=event.status,
                step_index=event.step_index,
                max_actions=event.max_actions,
                depends_on=event.depends_on,
                stage_family=event.stage_family,
            )
            self.task_run_updated.emit(snapshot)
        except ValueError:
            task_log.debug(
                "Ignored Task Run progress for unknown task — id=%s",
                event.task_id,
            )
        self.computer_use_progress.emit(event)

    def _on_tool_call_planned(self, event: ToolCallPlanned) -> None:
        label = self._tool_label(event.tool_name)
        self._record_work_stage(
            event.task_id,
            key=event.stage_key or f"tool:{event.tool_name}:{event.call_id or 'current'}",
            title=f"使用：{label}",
            detail="正在调用受控工具；不会把参数或结果写入任务进度",
            status="running",
            stage_family=f"tool:{event.tool_name}",
        )

    def _on_tool_call_executed(self, event: ToolCallExecuted) -> None:
        label = self._tool_label(event.tool_name)
        self._record_work_stage(
            event.task_id,
            key=event.stage_key or f"tool:{event.tool_name}:{event.call_id or 'current'}",
            title=f"已完成：{label}" if event.success else f"未完成：{label}",
            detail=("工具调用完成，已记录耗时" if event.success else "工具返回失败状态，未保留参数或原始结果"),
            status="success" if event.success else "failed",
            stage_family=f"tool:{event.tool_name}",
            measured_duration_ms=round(event.duration_ms),
        )

    def _on_tool_call_blocked(self, event: ToolCallBlocked) -> None:
        label = self._tool_label(event.tool_name)
        self._record_work_stage(
            event.task_id,
            key=event.stage_key or f"tool:{event.tool_name}:{event.call_id or 'blocked'}",
            title=f"已阻止：{label}",
            detail="安全规则阻止了这次调用；未保留命令、参数或原始错误",
            status="failed",
            stage_family=f"tool:{event.tool_name}",
        )

    def _on_hitl_requested(self, event: HitlRequested) -> None:
        self._record_work_stage(
            event.task_id,
            key=f"approval:{event.request_id or event.tool_name}",
            title=f"等待你的确认：{self._tool_label(event.tool_name)}",
            detail="这一步暂停在你手里；确认前不会执行",
            status="warning",
            stage_family="approval",
        )

    def _on_hitl_approved(self, event: HitlApproved) -> None:
        self._record_work_stage(
            event.task_id,
            key=f"approval:{event.request_id or event.tool_name}",
            title=f"你已确认：{self._tool_label(event.tool_name)}",
            detail="授权只适用于这一次受控调用",
            status="success",
            stage_family="approval",
        )

    def _on_hitl_denied(self, event: HitlDenied) -> None:
        self._record_work_stage(
            event.task_id,
            key=f"approval:{event.request_id or event.tool_name}",
            title=f"已取消：{self._tool_label(event.tool_name)}",
            detail="没有执行这次需要确认的调用",
            status="failed",
            stage_family="approval",
        )

    def _on_hitl_timeout(self, event: HitlTimeout) -> None:
        self._record_work_stage(
            event.task_id,
            key=f"approval:{event.request_id or event.tool_name}",
            title=f"确认已过期：{self._tool_label(event.tool_name)}",
            detail="等待超时，没有执行这次调用",
            status="failed",
            stage_family="approval",
        )

    def _record_work_stage(
        self,
        task_id: str,
        *,
        key: str,
        title: str,
        detail: str,
        status: str,
        stage_family: str,
        measured_duration_ms: int = 0,
    ) -> None:
        try:
            snapshot = self.task_runs.progress(
                task_id,
                key=key,
                title=title,
                detail=detail,
                status=status,
                stage_family=stage_family,
                measured_duration_ms=measured_duration_ms,
            )
            self.task_run_updated.emit(snapshot)
        except ValueError:
            task_log.debug(
                "Ignored Work Stage for inactive task — id=%s key=%s",
                task_id,
                key,
            )

    @staticmethod
    def _tool_label(tool_name: str) -> str:
        labels = {
            "read_file": "读取文件",
            "write_file": "写入文件",
            "edit_file": "修改文件",
            "list_dir": "查看目录",
            "glob": "查找文件",
            "grep": "搜索内容",
            "exec": "运行受控命令",
            "shell": "运行受控命令",
            "web_search": "搜索网页",
            "web_fetch": "读取网页",
            "spawn": "分派子任务",
            "session_search": "查找历史会话",
            "local_app_resolve": "查找本机应用",
            "local_open": "打开本机目标",
        }
        return labels.get(tool_name, "使用工具")

    def _on_memory_context_prepared(self, event: MemoryContextPrepared) -> None:
        """Project content-minimized recall evidence into Task Run and Qt."""
        if event.selected_count > 0:
            try:
                snapshot = self.task_runs.progress(
                    event.task_id,
                    key="memory-context",
                    title="准备相关记忆",
                    detail=f"参考 {event.selected_count} 条已确认记忆",
                    status="success",
                )
                self.task_run_updated.emit(snapshot)
            except ValueError:
                task_log.debug(
                    "Ignored memory context progress for unknown task — id=%s",
                    event.task_id,
                )
        self.memory_context_prepared.emit(event)

    def _on_task_completed(self, task_id: str, result: TaskResult):
        """Handle task completion - award EXP and evolve personality."""
        if not isinstance(result, TaskResult):
            usage_evidence = getattr(result, "usage_evidence", None)
            cancelled_value = getattr(result, "cancelled", False)
            result = TaskResult(
                task_id=task_id,
                success=bool(getattr(result, "success", False)),
                raw_result=str(getattr(result, "raw_result", "") or ""),
                summary=str(getattr(result, "summary", "") or ""),
                error_message=str(getattr(result, "error_message", "") or "") or None,
                cancelled=cancelled_value if isinstance(cancelled_value, bool) else False,
                usage_evidence=(
                    usage_evidence
                    if isinstance(usage_evidence, ModelUsageEvidence)
                    else ModelUsageEvidence()
                ),
            )
        snapshot = self.task_runs.complete(task_id, result)
        self.task_run_updated.emit(snapshot)
        with self._lock:
            evolution_candidate_id = self._task_evolution_map.pop(
                task_id,
                "",
            )
        if evolution_candidate_id:
            self.adapter.finalize_skill_evolution(evolution_candidate_id)
        task = self.repo.get_task(task_id)
        cancelled = snapshot.status == TaskStatus.CANCELLED
        if task:
            event = self._pet_progress.process_task_completion(task, result)
            self._emit_progress(event)

        with self._lock:
            session_id = self._task_session_map.pop(
                task_id,
                snapshot.session_id,
            )
        error_message = result.error_message or ""
        task_log.info(
            "Task completed signal — id=%s, success=%s, session=%s",
            task_id,
            result.success,
            session_id,
        )
        self.task_completed.emit(task_id, session_id, result.success, result.summary, error_message)

        if result.success:
            self.event_bus.publish(
                TaskCompletedEvent(
                    task_id=task_id,
                    session_id=session_id,
                    success=True,
                    summary=result.summary[:200],
                    error_message="",
                )
            )
        elif not cancelled:
            self.event_bus.publish(
                TaskFailedEvent(
                    task_id=task_id,
                    session_id=session_id,
                    error_message=error_message[:200],
                )
            )

        if not self.queue.has_other_work(task_id):
            self.pet_state_changed.emit(
                TaskStatus.IDLE if result.success or cancelled else TaskStatus.FAILED
            )

    async def retry_task(
        self,
        task_id: str,
        *,
        recovery_fingerprint: str,
    ) -> str:
        """Queue a new linked Task Run after a freshness-bound recovery review."""
        prepared = self.task_recovery.prepare_retry(
            task_id,
            expected_fingerprint=recovery_fingerprint,
        )
        task = prepared.task
        snapshot = prepared.snapshot
        with self._lock:
            self._task_context[task.id] = {
                "session_id": task.session_id,
                "image_path": "",
            }
            self._task_session_map[task.id] = task.session_id
        position = await self.queue.add_task(task)
        if position <= 0:
            with self._lock:
                self._task_context.pop(task.id, None)
                self._task_session_map.pop(task.id, None)
            unavailable = TaskResult(
                task_id=task.id,
                success=False,
                summary="任务队列已停止，未开始重新尝试",
                error_message="Task queue is unavailable",
            )
            failed_snapshot = self.task_runs.complete(task.id, unavailable)
            self.task_run_updated.emit(failed_snapshot)
            raise RuntimeError("Task queue is unavailable")
        self.task_run_updated.emit(snapshot)
        self.event_bus.publish(TaskQueuedEvent(task_id=task.id, session_id=task.session_id))
        task_log.info(
            "Task retry queued — id=%s, parent=%s, attempt=%d",
            task.id,
            task.parent_task_id,
            task.attempt_no,
        )
        return task.id

    def get_task_recovery_review(self, task_id: str):
        """Return content-minimized evidence required before retry."""
        return self.task_recovery.review(task_id)

    def get_task_run(self, task_id: str):
        """Return the user-facing projection for one Task Run."""
        return self.task_runs.snapshot(task_id)

    def _emit_progress(self, event: PetProgressEvent):
        self.pet_exp_gained.emit(
            event.exp_gained, event.current_exp, event.required_exp, event.level_up
        )
        if event.level_up:
            task_log.info(
                "Pet level up — Lv%d Stage%d (exp=%d, gained=%d)",
                event.new_level,
                event.new_stage,
                event.current_exp,
                event.exp_gained,
            )
            self.pet_level_up.emit(event.new_level, event.new_stage)
        else:
            task_log.debug(
                "Pet EXP gained — +%d (total=%d/%d)",
                event.exp_gained,
                event.current_exp,
                event.required_exp,
            )
        if event.personality_adjustments:
            self.pet_personality_changed.emit(event.personality_adjustments)
        for ability_id, ability_name in event.unlocked_abilities:
            task_log.info("Ability unlocked — %s (%s)", ability_name, ability_id)
            self.ability_unlocked.emit(ability_id, ability_name)
