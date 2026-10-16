"""Service lifecycle, durable request identity, isolated lanes and cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import JsonValue

from core.agent.dsh.runtime import BridgeEvent
from core.config import Settings
from core.models.pet import TaskRecord, TaskResult
from core.service.application import ApplicationService
from core.service.protocol import RpcRequest, ServiceEvent
from core.storage.db import Database
from core.tasks.task_queue import TaskQueue


class Backend:
    def __init__(self) -> None:
        self.ready = asyncio.Event()
        self.queue: asyncio.Queue[BridgeEvent] = asyncio.Queue()
        self.sent: list[dict[str, JsonValue]] = []
        self.sequence = 0
        self.closed = False

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        self.closed = True
        self.ready.clear()

    async def call(self, method: str, params: dict[str, JsonValue]) -> JsonValue:
        if method == "turn.send":
            self.sent.append(params)
            await self.emit(params, "turn.started", {})
        if method == "turn.cancel":
            original = next(item for item in self.sent if item["turnId"] == params["turnId"])
            await self.emit(original, "turn.cancelled", {})
        return {}

    async def emit(self, turn: dict[str, JsonValue], kind: str, data: dict[str, JsonValue]) -> None:
        self.sequence += 1
        await self.queue.put(
            BridgeEvent.model_validate(
                {
                    **{key: turn[key] for key in ("sessionId", "taskId", "turnId")},
                    "sequence": self.sequence,
                    "kind": kind,
                    "data": data,
                }
            )
        )

    async def events(self) -> AsyncIterator[BridgeEvent]:
        self.ready.set()
        while True:
            yield await self.queue.get()


def make_service(tmp_path: Path, events: list[ServiceEvent]) -> tuple[ApplicationService, Backend]:
    settings = Settings(
        llm_api_key="test", data_dir=tmp_path / "data", workspace_path=tmp_path / "workspace"
    )
    settings.workspace_path.mkdir(exist_ok=True)
    db = Database(settings)
    db.init_database(allow_desktop=True)
    backend = Backend()
    return ApplicationService(settings, db, backend, events.append), backend


async def call(
    service: ApplicationService,
    method: str,
    params: dict[str, JsonValue],
    request_id: str = "request",
) -> JsonValue:
    return await service.handle(
        RpcRequest(jsonrpc="2.0", id=request_id, method=method, params=params)
    )


async def wait_sent(backend: Backend, count: int) -> None:
    async with asyncio.timeout(2):
        while len(backend.sent) < count:
            await asyncio.sleep(0.001)


class TestHeadlessService:
    async def test_timeout_is_failed_not_user_cancel_and_no_reward(self, tmp_path: Path) -> None:
        events: list[ServiceEvent] = []
        service, _backend = make_service(tmp_path, events)
        service.settings.task_timeout = 1
        try:
            session = await call(service, "session.create", {}, "timeout-session")
            assert isinstance(session, dict)
            turn = await call(
                service, "turn.send", {"session_id": session["id"], "text": "wait"}, "timeout-turn"
            )
            assert isinstance(turn, dict)
            async with asyncio.timeout(3):
                while not any(event.kind == "turn.failed" for event in events):
                    await asyncio.sleep(0.01)
            state = service.repo.get(str(turn["turn_id"]))
            assert state.status == "failed" and "时限" in state.error
            assert service.pet.get_or_create_pet().exp == 0
        finally:
            await service.close()

    async def test_repeated_request_and_restart_never_reexecute(self, tmp_path: Path) -> None:
        events: list[ServiceEvent] = []
        service, backend = make_service(tmp_path, events)
        try:
            session = await call(service, "session.create", {}, "session")
            assert isinstance(session, dict)
            params = {"session_id": session["id"], "text": "hello"}
            first = await call(service, "turn.send", params, "send-once")
            repeat = await call(service, "turn.send", params, "send-once")
            assert first == repeat
            await wait_sent(backend, 1)
            assert len(backend.sent) == 1
            with pytest.raises(ValueError, match="不同内容"):
                await call(service, "turn.send", {**params, "text": "changed"}, "send-once")
        finally:
            await service.close()
        restored, new_backend = make_service(tmp_path, [])
        try:
            await call(restored, "turn.send", params, "send-once")
            await asyncio.sleep(0)
            assert not new_backend.sent
            history = await call(restored, "session.history", {"session_id": session["id"]})
            assert isinstance(history, list) and len(history) == 1
        finally:
            await restored.close()

    async def test_cancel_foreground_keeps_background_and_filters_late_text(
        self, tmp_path: Path
    ) -> None:
        events: list[ServiceEvent] = []
        service, backend = make_service(tmp_path, events)
        try:
            session = await call(service, "session.create", {}, "session")
            assert isinstance(session, dict)
            foreground = await call(
                service, "turn.send", {"session_id": session["id"], "text": "chat"}, "chat"
            )
            await call(
                service,
                "turn.send",
                {"session_id": session["id"], "text": "work", "lane": "background"},
                "work",
            )
            await wait_sent(backend, 2)
            assert backend.sent[0]["sessionId"] != backend.sent[1]["sessionId"]
            assert isinstance(foreground, dict)
            await call(service, "turn.cancel", {"turn_id": foreground["turn_id"]}, "cancel")
            await backend.emit(backend.sent[0], "text.delta", {"text": "late"})
            await backend.emit(backend.sent[1], "text.final", {"text": "background result"})
            await backend.emit(backend.sent[1], "turn.completed", {})
            async with asyncio.timeout(2):
                while (
                    len(
                        [
                            event
                            for event in events
                            if event.kind in ("turn.completed", "turn.cancelled")
                        ]
                    )
                    < 2
                ):
                    await asyncio.sleep(0.001)
            assert not any(event.data.get("text") == "late" for event in events)
            states = service.repo.list_turns()
            assert {state.status for state in states} == {"cancelled", "completed"}
            assert (
                next(state for state in states if state.lane == "background").output_text
                == "background result"
            )
            assert [event.sequence for event in events] == sorted(
                {event.sequence for event in events}
            )
        finally:
            await service.close()

    async def test_fifo_uses_one_processor_and_stop_cancels_all(self) -> None:
        queue = TaskQueue()
        started: list[str] = []
        completed: list[TaskResult] = []
        active = 0
        maximum = 0

        async def execute(task: TaskRecord) -> TaskResult:
            nonlocal active, maximum
            active += 1
            maximum = max(active, maximum)
            started.append(task.id)
            try:
                await asyncio.sleep(0.01)
                return TaskResult(task_id=task.id, success=True)
            finally:
                active -= 1

        queue.set_executor(execute)
        queue.task_completed.connect(lambda _, result: completed.append(result))
        await asyncio.gather(
            *(queue.add_task(TaskRecord(id=str(index), input_text="test")) for index in range(20))
        )
        processor = queue._processor_task
        await asyncio.sleep(0.025)
        assert queue._processor_task is processor
        await queue.stop()
        assert maximum == 1 and active == 0
        assert started == [str(index) for index in range(len(started))]
        assert len(completed) == 20
        assert any(result.cancelled for result in completed)

    async def test_crash_ledger_recovery_does_not_enqueue(self, tmp_path: Path) -> None:
        from core.service.protocol import TurnSend

        service, _ = make_service(tmp_path, [])
        session = await call(service, "session.create", {}, "session")
        assert isinstance(session, dict) and isinstance(session["id"], str)
        params = TurnSend(session_id=session["id"], text="unknown outcome")
        state, _, _ = service.repo.submit("crashed", params)
        state.status = "running"
        service.repo.save(state)
        await service.close()
        restored, backend = make_service(tmp_path, [])
        try:
            result = await call(restored, "turn.send", params.model_dump(mode="json"), "crashed")
            assert isinstance(result, dict) and result["status"] == "interrupted"
            assert not backend.sent
        finally:
            await restored.close()

    async def test_approval_on_close_is_denied(self, tmp_path: Path) -> None:
        from core.safety.hitl_approval import HitlApprovalRequest
        from core.service.application import TurnApproval
        from core.service.protocol import TurnSend

        service, _ = make_service(tmp_path, [])
        session = await call(service, "session.create", {}, "session")
        assert isinstance(session, dict) and isinstance(session["id"], str)
        state, _, _ = service.repo.submit(
            "approval", TurnSend(session_id=session["id"], text="test")
        )
        state.status = "running"
        pending = asyncio.create_task(
            TurnApproval(service, state).request_approval(
                HitlApprovalRequest.create(
                    session_id=state.session_id,
                    command="write file",
                    tool_name="lobuddy_write_file",
                    reason="test",
                )
            )
        )
        await asyncio.sleep(0)
        await service.close()
        decision = await pending
        assert not decision.approved
        assert not service.approvals

    def test_generated_types_match_protocol(self) -> None:
        from scripts.generate_desktop_protocol import generate

        target = Path(__file__).resolve().parents[1] / "shared/desktop-protocol.ts"
        assert target.read_text() == generate()

    async def test_stdio_invalid_duplicate_and_eof(self, tmp_path: Path) -> None:
        import json
        import os
        import sys

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.service",
            "--data-dir",
            str(tmp_path / "data"),
            "--workspace",
            str(tmp_path / "workspace"),
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "LLM_API_KEY": "test"},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdin and process.stdout
        try:
            process.stdin.write(b"{broken}\n")
            await process.stdin.drain()
            invalid = json.loads(await asyncio.wait_for(process.stdout.readline(), 5))
            assert invalid["error"]["code"] == -32602
            payload = {
                "jsonrpc": "2.0",
                "id": "one",
                "method": "session.create",
                "params": {"title": "once"},
            }
            for _ in range(2):
                process.stdin.write((json.dumps(payload) + "\n").encode())
            await process.stdin.drain()
            replies = [
                json.loads(await asyncio.wait_for(process.stdout.readline(), 5)) for _ in range(2)
            ]
            assert replies[0]["result"]["id"] == replies[1]["result"]["id"]
            payload["params"] = {"title": "conflict"}
            process.stdin.write((json.dumps(payload) + "\n").encode())
            await process.stdin.drain()
            conflict = json.loads(await asyncio.wait_for(process.stdout.readline(), 5))
            assert conflict["error"]["code"] == -32602
            process.stdin.close()
            await asyncio.wait_for(process.wait(), 5)
            assert process.returncode == 0
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
