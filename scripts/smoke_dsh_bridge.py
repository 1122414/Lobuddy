"""Real-provider P1 acceptance, using synthetic data and constrained test approvals.

Requires .env and `npm run --prefix bridge/dsh build`. Makes billable model requests.
No user files are supplied to the model. Never prints credentials or raw provider errors.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import tempfile
import uuid
from pathlib import Path
from typing import get_args

import httpx
from pydantic import JsonValue

from core.agent.dsh.runtime import BridgeEvent, DshRuntime
from core.agent.dsh.tools import GovernedTools, ToolRequest
from core.config.credentials import load_settings
from core.safety.hitl_approval import HitlApprovalDecision, HitlApprovalRequest


class FixtureApproval:
    allowed = False
    requests = 0

    def __init__(self) -> None:
        self.hold = False
        self.waiting = asyncio.Event()
        self.release = asyncio.Event()

    async def request_approval(self, request: HitlApprovalRequest) -> HitlApprovalDecision:
        self.requests += 1
        if self.hold:
            self.waiting.set()
            await self.release.wait()
        if self.allowed and request.affected_paths == ("acceptance.txt",):
            return HitlApprovalDecision.approved_now(
                request.request_id, "Synthetic acceptance file"
            )
        return HitlApprovalDecision.rejected_now(request.request_id, "Acceptance rejection case")


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = load_settings()
    values = {
        "LLM_API_KEY": settings.llm_api_key,
        "LLM_BASE_URL": settings.llm_base_url,
        "LLM_MODEL": settings.llm_model,
    }
    if not all(values.get(key) for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")):
        raise RuntimeError("Configure local model credentials first")
    with tempfile.TemporaryDirectory(prefix="lobuddy-dsh-acceptance-") as directory:
        data = Path(directory)
        workspace = data / "workspace"
        workspace.mkdir()
        runtime = DshRuntime(
            home=data / "home",
            workspace=workspace,
            plugin=root / "bridge/dsh/dist/index.js",
            api_key=values["LLM_API_KEY"] or "",
            base_url=values["LLM_BASE_URL"] or "",
            model=values["LLM_MODEL"] or "",
        )
        approval = FixtureApproval()
        tools = GovernedTools(workspace, approval, timeout=2)
        events: asyncio.Queue[BridgeEvent] = asyncio.Queue()
        active: set[str] = set()
        effects: set[asyncio.Task[None]] = set()

        async def execute(event: BridgeEvent) -> None:
            result: dict[str, JsonValue]
            try:
                request = ToolRequest.model_validate(event.data)
                value = await tools.execute(
                    request,
                    session_id=event.sessionId,
                    turn_id=event.turnId,
                    is_active=lambda: event.turnId in active and runtime.ready.is_set(),
                )
                result = {"ok": True, "value": value}
            except (ValueError, RuntimeError, OSError):
                result = {"ok": False, "error": "Rejected by Lobuddy tool governance"}
            with contextlib.suppress(RuntimeError, httpx.HTTPError):
                await runtime.call(
                    "tool.resolve",
                    {"callId": event.data["callId"], "turnId": event.turnId, **result},
                )

        async def consume() -> None:
            async for event in runtime.events():
                if event.kind == "tool.request":
                    task = asyncio.create_task(execute(event))
                    effects.add(task)
                    task.add_done_callback(effects.discard)
                await events.put(event)

        async def turn(prompt: str, *, cancel: bool = False) -> tuple[str, list[BridgeEvent]]:
            turn_id = str(uuid.uuid4())
            active.add(turn_id)
            await runtime.call(
                "turn.send",
                {
                    "sessionId": "acceptance",
                    "taskId": turn_id,
                    "turnId": turn_id,
                    "lane": "foreground",
                    "text": prompt,
                },
            )
            collected = []
            cancel_sent = False
            async with asyncio.timeout(90):
                while True:
                    event = await events.get()
                    if event.turnId != turn_id:
                        continue
                    collected.append(event)
                    if cancel and not cancel_sent and event.kind == "text.delta":
                        active.discard(turn_id)
                        cancel_sent = True
                        await runtime.call(
                            "turn.cancel", {"sessionId": "acceptance", "turnId": turn_id}
                        )
                    if event.kind in ("turn.completed", "turn.cancelled", "turn.failed"):
                        active.discard(turn_id)
                        assert event.kind == (
                            "turn.cancelled" if cancel else "turn.completed"
                        ), event.kind
                        return turn_id, collected

        consumer = None
        try:
            await runtime.start()
            consumer = asyncio.create_task(consume())
            await asyncio.wait_for(runtime.ready.wait(), 5)
            health = await runtime.call("health", {})
            assert isinstance(health, dict)
            names = health["tools"]
            assert isinstance(names, list) and all(isinstance(name, str) for name in names)
            assert {str(name) for name in names} == set(
                get_args(ToolRequest.model_fields["name"].annotation)
            )
            await runtime.call("session.open", {"sessionId": "acceptance"})
            _, response = await turn("请回复一句简短的中文问候，不调用工具。")
            assert any(e.kind == "text.delta" for e in response)
            print("PASS: real model streaming text", flush=True)
            await turn(
                "请调用 lobuddy_write_file，将 acceptance.txt 写入 hello。只尝试一次；如果被拒绝就停止并告知我。"
            )
            assert approval.requests > 0 and not (workspace / "acceptance.txt").exists()
            print("PASS: real model tool request rejected with no file effect", flush=True)
            approval.allowed = True
            completed_id, _ = await turn(
                "现在我允许你调用 lobuddy_write_file，将 acceptance.txt 写入 hello。请立即执行。"
            )
            assert (workspace / "acceptance.txt").read_text().strip() == "hello"
            print("PASS: approved real model tool request produced expected file", flush=True)
            await turn("请写一篇很长的关于海洋的文章。", cancel=True)
            print("PASS: cancellation has its own terminal state", flush=True)
            await runtime.close()
            consumer.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await consumer
            await runtime.start()
            consumer = asyncio.create_task(consume())
            await asyncio.wait_for(runtime.ready.wait(), 5)
            await runtime.call("session.open", {"sessionId": "acceptance", "resume": True})
            try:
                await runtime.call(
                    "turn.send",
                    {
                        "sessionId": "acceptance",
                        "taskId": completed_id,
                        "turnId": completed_id,
                        "lane": "foreground",
                        "text": "Do not repeat",
                    },
                )
            except RuntimeError:
                print("PASS: resumed session rejects duplicate completed turn", flush=True)
            else:
                raise AssertionError("Duplicate turn was accepted")
            approval.hold = True
            crash_turn = str(uuid.uuid4())
            active.add(crash_turn)
            await runtime.call(
                "turn.send",
                {
                    "sessionId": "acceptance",
                    "taskId": crash_turn,
                    "turnId": crash_turn,
                    "lane": "foreground",
                    "text": "请再次调用 lobuddy_write_file，将 acceptance.txt 的内容改为 changed。",
                },
            )
            await asyncio.wait_for(approval.waiting.wait(), 90)
            assert runtime.process_id is not None
            os.kill(runtime.process_id, signal.SIGKILL)
            with contextlib.suppress(httpx.HTTPError):
                await asyncio.wait_for(consumer, 10)
            assert not runtime.ready.is_set()
            active.clear()
            approval.release.set()
            await asyncio.gather(*effects, return_exceptions=True)
            assert (workspace / "acceptance.txt").read_text().strip() == "hello"
            await runtime.close()
            await runtime.start()
            consumer = asyncio.create_task(consume())
            await asyncio.wait_for(runtime.ready.wait(), 5)
            await runtime.call("session.open", {"sessionId": "acceptance", "resume": True})
            await asyncio.sleep(0.5)
            assert (workspace / "acceptance.txt").read_text().strip() == "hello"
            assert not effects
            print("PASS: crash during approval resumes without replay or file effect", flush=True)
            credential = (values["LLM_API_KEY"] or "").encode()
            assert all(
                credential not in file.read_bytes()
                for file in (data / "home").rglob("*")
                if file.is_file()
            )
            print("PASS: credentials absent from DSH home files", flush=True)
            print("PASS: P1 real model smoke completed", flush=True)
        finally:
            active.clear()
            for task in effects:
                task.cancel()
            await asyncio.gather(*effects, return_exceptions=True)
            if consumer:
                consumer.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await consumer
            await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
