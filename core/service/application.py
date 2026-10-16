"""Headless application orchestration; UI clients observe state, never own execution."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import JsonValue

from core.agent.dsh.runtime import BridgeEvent
from core.agent.dsh.tools import GovernedTools, ToolRequest
from core.config import Settings
from core.config.credentials import migrate_credentials
from core.focus.focus_companion import FocusCompanion
from core.models.pet import TaskRecord, TaskResult, TaskStatus
from core.safety.hitl_approval import HitlApprovalDecision, HitlApprovalRequest
from core.service.companion import CompanionPreferences, CompanionService
from core.service.companionship import (
    CompanionActivity,
    CompanionFeedback,
    CompanionPolicy,
    Companionship,
    CompanionTrigger,
    proactive_instruction,
)
from core.service.images import ImageImport, ImageReference, ImageStore
from core.service.knowledge import KnowledgeService
from core.service.learning import LearningHandler, LearningService, maintenance_handler
from core.service.learning_protocol import LearningPolicy
from core.service.protocol import (
    METHODS,
    ApprovalResolve,
    FocusStart,
    RpcRequest,
    ServiceEvent,
    SessionCreate,
    SessionReference,
    TurnReference,
    TurnSend,
    TurnState,
)
from core.service.settings_service import SettingsPatch, SettingsService
from core.service.themes import ThemeReference, ThemeSave, ThemeService
from core.service.topics import TopicReference
from core.services.credential_prompt import CredentialConfigure, configure_credential
from core.storage.chat_repo import ChatRepository
from core.storage.db import Database
from core.storage.keychain import MacKeychain
from core.storage.pet_repo import PetRepository
from core.storage.runtime_ledger import RuntimeLedger
from core.storage.service_repo import ServiceRepository
from core.tasks.task_queue import TaskQueue


class AgentBackend(Protocol):
    ready: asyncio.Event

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def call(self, method: str, params: dict[str, JsonValue]) -> JsonValue: ...
    def events(self) -> AsyncIterator[BridgeEvent]: ...


@dataclass
class PendingApproval:
    request: HitlApprovalRequest
    state: TurnState
    future: asyncio.Future[HitlApprovalDecision]


class TurnApproval:
    def __init__(self, service: ApplicationService, state: TurnState) -> None:
        self.service = service
        self.state = state

    async def request_approval(self, request: HitlApprovalRequest) -> HitlApprovalDecision:
        future: asyncio.Future[HitlApprovalDecision] = asyncio.get_running_loop().create_future()
        self.service.approvals[request.request_id] = PendingApproval(request, self.state, future)
        try:
            self.service.emit(
                self.state,
                "approval.requested",
                {
                    "approval_id": request.request_id,
                    "command": request.command,
                    "reason": request.reason,
                    "tool_name": request.tool_name,
                },
            )
            return await future
        finally:
            self.service.approvals.pop(request.request_id, None)


class ApplicationService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        backend: AgentBackend,
        publish: Callable[[ServiceEvent], None],
    ) -> None:
        self.settings = settings
        self.backend = backend
        self.chat = ChatRepository(db)
        self.pet = PetRepository(db)
        self.repo = ServiceRepository(db)
        self.repo.interrupt_unfinished()
        self.knowledge = KnowledgeService(settings, db)
        self.ledger = RuntimeLedger(db)
        self.ledger.recover()
        self.configuration = SettingsService(settings, db)
        self._credential_lock = asyncio.Lock()
        self.images = ImageStore(settings.data_dir / "images")
        self.companion = CompanionService(db, settings.data_dir)
        self.themes = ThemeService(db, self.companion, self.images)
        self.companionship = Companionship(db)
        self.focus = FocusCompanion(settings)
        self._publish = publish
        self.approvals: dict[str, PendingApproval] = {}
        self._states: dict[str, TurnState] = {}
        self._futures: dict[str, asyncio.Future[TaskResult]] = {}
        self._tools: dict[str, GovernedTools] = {}
        self._effects: dict[asyncio.Task[None], str] = {}
        self._queues = {name: TaskQueue() for name in ("foreground", "background")}
        for queue in self._queues.values():
            queue.set_executor(self._execute)
            queue.task_completed.connect(self._completed)
        self._engine_lock = asyncio.Lock()
        self._consumer: asyncio.Task[None] | None = None
        self._focus_timer: asyncio.Task[None] | None = None
        self._closed = False
        self.learning = LearningService(db, settings, self._learning_busy)
        self.learning.handlers["skill_evidence"] = LearningHandler(self._learn_skill)
        self.learning.handlers["maintenance"] = maintenance_handler(settings, db)
        self.learning.handlers["relationship"] = LearningHandler(
            self._learn_relationship, calls=1, input_tokens=8192, output_tokens=1024
        )

    def emit(self, state: TurnState, kind: str, data: dict[str, JsonValue]) -> None:
        self._publish(self.repo.event(state, kind, data))

    async def _learn_skill(self, source_id: str) -> dict[str, JsonValue]:
        return self.knowledge.learn_outcome(self.repo.get(source_id))

    async def _learn_relationship(self, source_id: str) -> dict[str, JsonValue]:
        sources = self.knowledge.relationship._sources([source_id])
        if not sources or not self.knowledge.relationship.enabled:
            return {"skipped": "no_authorized_source"}
        previous = {
            item.id
            for item in self.knowledge.relationship.list_relations()
            if item.status == "active"
        }
        result = await self.knowledge.relationship.analyze(sources[0].session_id, self._analyze)
        remembered = [
            item.id
            for item in self.knowledge.relationship.list_relations()
            if item.status == "active" and item.id not in previous
        ]
        if remembered:
            with contextlib.suppress(ValueError):
                state = self.repo.get(source_id)
                self.emit(
                    state, "relationship.remembered", {"ids": [identity for identity in remembered]}
                )
        return result

    async def _analyze(self, prompt: str) -> str:
        identity = uuid.uuid4().hex
        await self._ensure_engine()
        try:
            result = await self.backend.call("analysis.run", {"id": identity, "prompt": prompt})
            if not isinstance(result, dict) or not isinstance(result.get("text"), str):
                raise TypeError("知识整理结果无效")
            return str(result["text"])
        finally:
            with contextlib.suppress(RuntimeError, httpx.HTTPError):
                await self.backend.call("analysis.cancel", {"id": identity})

    def _learning_busy(self) -> bool:
        voice = getattr(self, "voice", None)
        return bool(self._states) or bool(voice and voice.view().state not in ("off", "error"))

    async def handle(self, request: RpcRequest) -> JsonValue:
        if self._closed:
            raise ValueError("服务正在退出")
        model = METHODS.get(request.method)
        if model is None:
            raise ValueError("不支持的业务接口")
        params = model.model_validate(request.params)
        method = request.method
        self.learning.start()
        if method in ("turn.send", "voice.start") or (
            method == "companionship.activity"
            and (request.params.get("typing") or request.params.get("conversation"))
        ):
            await self.learning.activity()
        if method == "learning.get":
            return self.learning.view().model_dump(mode="json")
        if method == "learning.configure":
            assert isinstance(params, LearningPolicy)
            return (await self.learning.configure(params)).model_dump(mode="json")
        if method.startswith(("memory.", "skill.", "history.", "preference.", "relationship.")):
            if method in ("relationship.forget", "relationship.configure", "memory.delete"):
                await self.learning.activity()
            result = self.knowledge.handle(request)
            if method == "preference.save" and request.params.get("kind") == "boundary":
                content = request.params.get("content")
                if isinstance(content, str):
                    instruction = proactive_instruction(content)
                    if instruction is not None:
                        self.companionship.configure(
                            self.companionship.policy.model_copy(update={"enabled": instruction})
                        )
            if method in (
                "preference.save",
                "relationship.edit",
                "relationship.resolve",
                "relationship.forget",
                "memory.save",
                "memory.delete",
                "skill.save",
                "skill.toggle",
                "skill.archive",
                "skill.candidate.resolve",
            ):
                for active_state in self._states.values():
                    if active_state.status == "running" and self.backend.ready.is_set():
                        await self.backend.call(
                            "context.update",
                            {
                                "sessionId": active_state.engine_id,
                                "context": self.knowledge.context(active_state),
                            },
                        )
            return result
        if method == "companionship.overview":
            return self.companionship.topics.overview().model_dump(mode="json")
        if method == "companionship.topics":
            return [
                topic.model_dump(mode="json") for topic in self.companionship.topics.list_topics()
            ]
        if method == "companionship.topic.unblock":
            assert isinstance(params, TopicReference)
            self.companionship.topics.feedback(params.topic_id, "unblock")
            return {"changed": True}
        if method == "companionship.get":
            return self.companionship.policy.model_dump(mode="json")
        if method == "companionship.configure":
            assert isinstance(params, CompanionPolicy)
            return self.companionship.configure(params).model_dump(mode="json")
        if method == "companionship.activity":
            assert isinstance(params, CompanionActivity)
            self.companionship.engage(params)
            return {"accepted": True}
        if method == "companionship.trigger":
            assert isinstance(params, CompanionTrigger)
            self.companionship.trigger(params)
            return {"accepted": True}
        if method == "companionship.feedback":
            assert isinstance(params, CompanionFeedback)
            self.companionship.feedback(params)
            return {"accepted": True}
        if method == "companionship.poll":
            notice = self.companionship.poll(
                focused=self.focus.is_active,
                running=bool(self._states) or bool(self.approvals),
            )
            return notice.model_dump(mode="json") if notice else None
        if method == "theme.list":
            return [value.model_dump(mode="json") for value in self.themes.list()]
        if method == "theme.save":
            assert isinstance(params, ThemeSave)
            return self.themes.save(params).model_dump(mode="json")
        if method == "theme.apply":
            assert isinstance(params, ThemeReference)
            self.themes.apply(params)
            return {"applied": True}
        if method == "theme.delete":
            assert isinstance(params, ThemeReference)
            return {"deleted": self.themes.remove(params)}
        if method == "theme.from_image":
            assert isinstance(params, ImageReference)
            return (await asyncio.to_thread(self.themes.from_image, params)).model_dump(mode="json")
        if method == "companion.get":
            return self.companion.preferences.model_dump(mode="json")
        if method == "companion.save":
            assert isinstance(params, CompanionPreferences)
            return self.companion.save(params).model_dump(mode="json")
        if method == "companion.import":
            assert isinstance(params, ImageImport)
            return (await asyncio.to_thread(self.companion.import_image, params.path)).model_dump(
                mode="json"
            )
        if method == "image.import":
            assert isinstance(params, ImageImport)
            return (await asyncio.to_thread(self.images.import_file, params.path)).model_dump(
                mode="json"
            )
        if method == "image.get":
            assert isinstance(params, ImageReference)
            return (await asyncio.to_thread(self.images.get, params.image_id)).model_dump(
                mode="json"
            )
        if method == "credential.configure":
            assert isinstance(params, CredentialConfigure)
            if self._credential_lock.locked():
                raise ValueError("凭据窗口已经打开")
            async with self._credential_lock:
                await asyncio.to_thread(
                    migrate_credentials, self.repo.db, Path.cwd() / ".env", MacKeychain()
                )
                saved = await configure_credential(params.account)
                if saved:
                    self.configuration.credential_status[params.account] = True
                    self.configuration.restart_required = True
                return {"saved": saved}
        if method == "settings.get":
            return self.configuration.view().model_dump(mode="json")
        if method == "settings.patch":
            return self.configuration.patch(
                SettingsPatch.model_validate(request.params)
            ).model_dump(mode="json")
        if method == "service.health":
            return {
                "protocol": 1,
                "engine": "dsh",
                "connected": self.backend.ready.is_set(),
                "voice_available": False,
                "model_configured": bool(
                    self.settings.llm_api_key
                    and self.settings.llm_base_url
                    and self.settings.llm_model
                ),
            }
        if method == "session.create":
            assert isinstance(params, SessionCreate)
            identity = str(uuid.uuid5(uuid.NAMESPACE_URL, "lobuddy-session:" + request.id))
            return self.chat.get_or_create_session(identity, title=params.title).model_dump(
                mode="json"
            )
        if method == "session.list":
            return [session.model_dump(mode="json") for session in self.chat.get_all_sessions(100)]
        if method == "session.history":
            assert isinstance(params, SessionReference)
            return [
                message.model_dump(mode="json")
                for message in self.chat.get_messages(params.session_id)
            ]
        if method == "turn.send":
            assert isinstance(params, TurnSend)
            if not params.text.strip():
                raise ValueError("消息不能为空")
            if params.image_id:
                await asyncio.to_thread(self.images.get, params.image_id)
            state, created, _ = self.repo.submit(request.id, params)
            if created:
                self.companionship.respond(state.input_text)
                if self.learning.policy.enabled:
                    remembered = self.knowledge.relationship.immediate(
                        state.session_id, state.turn_id, state.input_text
                    )
                    if remembered:
                        self.emit(
                            state,
                            "relationship.remembered",
                            {"ids": [identity for identity in remembered]},
                        )
                instruction = proactive_instruction(state.input_text)
                if instruction is not None:
                    self.companionship.configure(
                        self.companionship.policy.model_copy(update={"enabled": instruction})
                    )
                self._states[state.task_id] = state
                self.emit(state, "turn.queued", {})
                await self._queues[state.lane].add_task(
                    TaskRecord(
                        id=state.task_id, input_text=state.input_text, status=TaskStatus.QUEUED
                    )
                )
            return state.model_dump(mode="json")
        if method == "task.list":
            return [state.model_dump(mode="json") for state in self.repo.list_turns()]
        if method == "task.outcome":
            assert isinstance(params, TurnReference)
            return self.ledger.outcomes.get(params.turn_id).model_dump(mode="json")
        if method == "task.get":
            assert isinstance(params, TurnReference)
            return self.repo.get(params.turn_id).model_dump(mode="json")
        if method == "turn.cancel":
            assert isinstance(params, TurnReference)
            await self.cancel(params.turn_id)
            return self.repo.get(params.turn_id).model_dump(mode="json")
        if method == "approval.list":
            return [
                {
                    "approval_id": value.request.request_id,
                    "turn_id": value.state.turn_id,
                    "session_id": value.state.session_id,
                    "command": value.request.command,
                    "reason": value.request.reason,
                }
                for value in self.approvals.values()
            ]
        if method == "approval.resolve":
            assert isinstance(params, ApprovalResolve)
            pending = self.approvals.get(params.approval_id)
            if pending is None or pending.future.done() or pending.state.status != "running":
                raise ValueError("审批已失效")
            pending.future.set_result(
                HitlApprovalDecision.approved_now(params.approval_id)
                if params.approved
                else HitlApprovalDecision.rejected_now(params.approval_id, "用户拒绝")
            )
            return {"accepted": True}
        if method == "progress.get":
            return self.ledger.summary()
        if method == "pet.get":
            return self.pet.get_or_create_pet().model_dump(mode="json")
        if method.startswith("focus."):
            if method == "focus.start":
                assert isinstance(params, FocusStart)
                self.focus.start_focus(params.minutes)
                if self._focus_timer is None or self._focus_timer.done():
                    self._focus_timer = asyncio.create_task(self._poll_focus())
            elif method == "focus.pause":
                self.focus.pause()
            elif method == "focus.resume":
                self.focus.resume()
            elif method == "focus.stop":
                self.focus.stop()
            session = self.focus.current_session
            return {
                "state": session.state.value if session else "idle",
                "seconds_remaining": session.seconds_remaining if session else 0,
                "completed_count": self.focus.completed_count,
            }
        raise ValueError("不支持的业务接口")

    async def _poll_focus(self) -> None:
        while not self._closed and self.focus.is_active:
            await asyncio.sleep(1)
            session = self.focus.current_session
            completed = self.focus.completed_count
            self.focus.poll()
            if session and self.focus.completed_count > completed:
                self.knowledge.record_focus(session.identity, session.focus_minutes)
                self.companionship.trigger(CompanionTrigger(event="focus_finished"))

    async def _ensure_engine(self) -> None:
        async with self._engine_lock:
            if self._consumer and not self._consumer.done():
                return
            if self._consumer:
                raise RuntimeError("引擎连接已中断，需要重新启动服务；不会自动重放")
            await self.backend.start()
            self._consumer = asyncio.create_task(self._consume())
            await asyncio.wait_for(self.backend.ready.wait(), 5)

    async def _execute(self, task: TaskRecord) -> TaskResult:
        state = self._states[task.id]
        await self._ensure_engine()
        resume = self.repo.engine_ready(state.engine_id)
        await self.backend.call("session.open", {"sessionId": state.engine_id, "resume": resume})
        self.repo.mark_engine_ready(state.engine_id)
        if state.status == "cancelled":
            return TaskResult(task_id=task.id, success=False, cancelled=True)
        state.status = "running"
        self.repo.save(state)
        self._tools[state.turn_id] = GovernedTools(
            self.settings.workspace_path,
            TurnApproval(self, state),
            knowledge=self.knowledge,
            state=state,
            settings=self.settings,
            record_skill=lambda skill_id: self.ledger.record_skill_use(state, skill_id),
        )
        future: asyncio.Future[TaskResult] = asyncio.get_running_loop().create_future()
        self._futures[state.turn_id] = future
        try:
            await self.backend.call(
                "turn.send",
                {
                    "sessionId": state.engine_id,
                    "taskId": state.task_id,
                    "turnId": state.turn_id,
                    "lane": state.lane,
                    "text": state.input_text,
                    "context": self.knowledge.prepare(state),
                    "image": (
                        self.images.get(state.image_id).model_dump(mode="json", exclude={"preview"})
                        if state.image_id
                        else None
                    ),
                },
            )
            try:
                result = await asyncio.wait_for(asyncio.shield(future), self.settings.task_timeout)
            except TimeoutError:
                await self.cancel(state.turn_id)
                try:
                    await asyncio.wait_for(asyncio.shield(future), 10)
                except (TimeoutError, RuntimeError):
                    await self.backend.close()
                state.status = "failed"
                return TaskResult(
                    task_id=state.task_id,
                    success=False,
                    error_message="任务超过设定时限，已停止执行。",
                )
            if result.success and state.status != "cancelled":
                # The durable reply is committed before summary/candidate derivation.
                state.status = "completed"
                self.repo.save(state)
            return result
        finally:
            self._futures.pop(state.turn_id, None)
            self._tools.pop(state.turn_id, None)

    async def _consume(self) -> None:
        try:
            async for event in self.backend.events():
                state = self._states.get(event.taskId)
                if (
                    state is None
                    or event.turnId != state.turn_id
                    or event.sessionId != state.engine_id
                ):
                    continue
                if event.kind == "usage":
                    usage = event.data.get("usage")
                    if isinstance(usage, dict):
                        self.ledger.usage(state, event.sequence, usage)
                future = self._futures.get(state.turn_id)
                terminal = event.kind in ("turn.completed", "turn.failed", "turn.cancelled")
                if state.status != "running" and not (state.status == "cancelled" and terminal):
                    continue
                if event.kind == "tool.request":
                    task = asyncio.create_task(self._tool(state, event))
                    self._effects[task] = state.turn_id
                    task.add_done_callback(lambda completed: self._effects.pop(completed, None))
                elif event.kind in ("text.delta", "text.final"):
                    value = event.data.get("text")
                    if isinstance(value, str):
                        state.output_text = (
                            state.output_text + value if event.kind == "text.delta" else value
                        )
                    self.repo.save(state)
                    self.emit(state, event.kind, event.data)
                elif event.kind in ("turn.completed", "turn.failed", "turn.cancelled"):
                    if future and not future.done():
                        future.set_result(
                            TaskResult(
                                task_id=state.task_id,
                                success=event.kind == "turn.completed",
                                cancelled=event.kind == "turn.cancelled"
                                or state.status == "cancelled",
                                raw_result=state.output_text,
                                summary=state.output_text,
                            )
                        )
                else:
                    self.emit(state, event.kind, event.data)
        except (httpx.HTTPError, RuntimeError, ValueError):
            pass
        finally:
            self.backend.ready.clear()
            self._deny_approvals()
            for effect in self._effects:
                effect.cancel()
            for future in self._futures.values():
                if not future.done():
                    future.set_exception(RuntimeError("引擎连接中断，未自动重试"))

    async def _tool(self, state: TurnState, event: BridgeEvent) -> None:
        call_id = event.data.get("callId")
        if not isinstance(call_id, str):
            await self.cancel(state.turn_id)
            return
        result: dict[str, JsonValue]
        try:
            value = await self._tools[state.turn_id].execute(
                ToolRequest.model_validate(event.data),
                session_id=state.session_id,
                turn_id=state.turn_id,
                is_active=lambda: state.status == "running"
                and self.backend.ready.is_set()
                and not self._closed,
            )
            if event.data.get("name") == "lobuddy_memory_propose" and state.status == "running":
                await self.backend.call(
                    "context.update",
                    {
                        "sessionId": state.engine_id,
                        "context": self.knowledge.context(state),
                    },
                )
            self.emit(state, "tool.completed", {"name": event.data.get("name"), "call_id": call_id})
            result = {"ok": True, "value": value}
        except (ValueError, RuntimeError, OSError, KeyError):
            result = {"ok": False, "error": "操作被拒绝、已取消或超出预算"}
        with contextlib.suppress(RuntimeError, httpx.HTTPError):
            await self.backend.call(
                "tool.resolve", {"callId": call_id, "turnId": state.turn_id, **result}
            )

    def _completed(self, task_id: str, result: TaskResult) -> None:
        state = self._states.pop(task_id, None)
        if state is None:
            return
        state.status = (
            "cancelled"
            if result.cancelled or state.status == "cancelled"
            else "completed" if result.success else "failed"
        )
        state.error = (
            ""
            if result.success or state.status == "cancelled"
            else (
                "任务超过设定时限，已停止执行。"
                if result.error_message == "任务超过设定时限，已停止执行。"
                else "执行失败，请检查模型配置或服务连接。"
            )
        )
        self.repo.save(state)
        if state.status == "completed" and state.lane == "foreground":
            self.companionship.trigger(CompanionTrigger(event="conversation_finished"))
        if (
            state.status == "completed"
            and self.learning.policy.enabled
            and self.knowledge.relationship.enabled
        ):
            self.learning.repo.enqueue("relationship", state.turn_id, self.learning.clock())
        outcome = self.ledger.outcomes.finish_turn(state.turn_id, state.status)
        self.emit(state, "task.outcome", outcome.model_dump(mode="json"))
        if self.learning.policy.enabled and (
            outcome.verdict in ("verified", "failed")
            or state.input_text.startswith(("以后整理", "下次整理", "以后归纳", "下次归纳"))
        ):
            self.learning.repo.enqueue("skill_evidence", state.turn_id, self.learning.clock())
        progress = self.ledger.settle(state)
        self.emit(state, "progress.changed", progress.model_dump(mode="json"))
        self.emit(state, "turn." + state.status, {"status": state.status, "error": state.error})

    async def cancel(self, turn_id: str) -> None:
        saved = self.repo.get(turn_id)
        state = self._states.get(saved.task_id)
        if state is None:
            return
        state.status = "cancelled"
        self.repo.save(state)
        self._deny_approvals(turn_id)
        effects = [effect for effect, identity in self._effects.items() if identity == turn_id]
        for effect in effects:
            effect.cancel()
        await asyncio.gather(*effects, return_exceptions=True)
        if await self._queues[state.lane].cancel_pending(state.task_id):
            return
        if self.backend.ready.is_set():
            await self.backend.call(
                "turn.cancel", {"sessionId": state.engine_id, "turnId": turn_id}
            )

    def _deny_approvals(self, turn_id: str | None = None) -> None:
        for pending in self.approvals.values():
            if (turn_id is None or pending.state.turn_id == turn_id) and not pending.future.done():
                pending.future.set_result(
                    HitlApprovalDecision.rejected_now(
                        pending.request.request_id, "会话已关闭或取消"
                    )
                )

    async def close(self) -> None:
        self._closed = True
        await self.learning.close()
        self._deny_approvals()
        self.focus.stop()
        if self._focus_timer:
            self._focus_timer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._focus_timer
        for queue in self._queues.values():
            await queue.stop()
        for task in self._effects:
            task.cancel()
        await asyncio.gather(*self._effects, return_exceptions=True)
        if self._consumer:
            self._consumer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer
        await self.backend.close()
