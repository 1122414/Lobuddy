"""Headless application orchestration; UI clients observe state, never own execution."""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol

import httpx
from pydantic import JsonValue

from core.agent.dsh.runtime import BridgeEvent
from core.agent.dsh.tools import GovernedTools, ToolRequest
from core.config import Settings
from core.focus.focus_companion import FocusCompanion
from core.models.pet import TaskRecord, TaskResult, TaskStatus
from core.safety.hitl_approval import HitlApprovalDecision, HitlApprovalRequest
from core.service.knowledge import KnowledgeService
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
from core.storage.chat_repo import ChatRepository
from core.storage.db import Database
from core.storage.pet_repo import PetRepository
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
        self.focus = FocusCompanion(settings)
        self._publish = publish
        self.approvals: dict[str, PendingApproval] = {}
        self._states: dict[str, TurnState] = {}
        self._futures: dict[str, asyncio.Future[TaskResult]] = {}
        self._tools: dict[str, GovernedTools] = {}
        self._effects: set[asyncio.Task[None]] = set()
        self._queues = {name: TaskQueue() for name in ("foreground", "background")}
        for queue in self._queues.values():
            queue.set_executor(self._execute)
            queue.task_completed.connect(self._completed)
        self._engine_lock = asyncio.Lock()
        self._consumer: asyncio.Task[None] | None = None
        self._focus_timer: asyncio.Task[None] | None = None
        self._closed = False

    def emit(self, state: TurnState, kind: str, data: dict[str, JsonValue]) -> None:
        self._publish(self.repo.event(state, kind, data))

    async def handle(self, request: RpcRequest) -> JsonValue:
        if self._closed:
            raise ValueError("服务正在退出")
        model = METHODS.get(request.method)
        if model is None:
            raise ValueError("不支持的业务接口")
        params = model.model_validate(request.params)
        method = request.method
        if method.startswith(("memory.", "skill.", "history.")):
            result = self.knowledge.handle(request)
            if method in (
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
            state, created, _ = self.repo.submit(request.id, params)
            if created:
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
            }
        raise ValueError("不支持的业务接口")

    async def _poll_focus(self) -> None:
        while not self._closed and self.focus.is_active:
            await asyncio.sleep(1)
            self.focus.poll()

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
                },
            )
            result = await future
            if result.success and state.status != "cancelled":
                # The durable reply is committed before summary/candidate derivation.
                state.status = "completed"
                self.repo.save(state)
                try:
                    self.knowledge.completed(state, self._tools[state.turn_id].used)
                except (ValueError, OSError, sqlite3.Error):
                    self.emit(state, "knowledge.warning", {"message": "回答已保存，知识整理未完成"})
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
                future = self._futures.get(state.turn_id)
                terminal = event.kind in ("turn.completed", "turn.failed", "turn.cancelled")
                if state.status != "running" and not (state.status == "cancelled" and terminal):
                    continue
                if event.kind == "tool.request":
                    task = asyncio.create_task(self._tool(state, event))
                    self._effects.add(task)
                    task.add_done_callback(self._effects.discard)
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
            else "执行失败，请检查模型配置或服务连接。"
        )
        self.repo.save(state)
        self.emit(state, "turn." + state.status, {"status": state.status, "error": state.error})

    async def cancel(self, turn_id: str) -> None:
        saved = self.repo.get(turn_id)
        state = self._states.get(saved.task_id)
        if state is None:
            return
        state.status = "cancelled"
        self.repo.save(state)
        self._deny_approvals(turn_id)
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
