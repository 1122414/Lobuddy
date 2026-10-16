"""Bounded newline JSON-RPC transport; no domain logic and no stdout logging."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable

from pydantic import JsonValue, ValidationError

from core.service.protocol import RpcRequest, ServiceEvent

MAX_LINE = 1024 * 1024


class StdioServer:
    def __init__(self) -> None:
        self._outgoing: asyncio.Queue[dict[str, JsonValue]] = asyncio.Queue(maxsize=1024)
        self._requests: dict[str, tuple[str, asyncio.Task[dict[str, JsonValue]]]] = {}
        self._closed = False

    def publish(self, event: ServiceEvent) -> None:
        if not self._closed:
            self._outgoing.put_nowait(
                {"jsonrpc": "2.0", "method": "event", "params": event.model_dump(mode="json")}
            )

    async def run(self, handle: Callable[[RpcRequest], Awaitable[JsonValue]]) -> None:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=MAX_LINE)
        input_transport, _ = await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer
        )
        output_transport, protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout.buffer
        )
        writer = asyncio.StreamWriter(output_transport, protocol, None, loop)
        outgoing = asyncio.create_task(self._write(writer))
        deliveries: set[asyncio.Task[None]] = set()
        slots = asyncio.Semaphore(32)

        async def read_input() -> None:
            while True:
                line = await reader.readline()
                if not line:
                    return
                await slots.acquire()
                task = asyncio.create_task(self._receive(line, handle, slots))
                deliveries.add(task)
                task.add_done_callback(deliveries.discard)

        incoming = asyncio.create_task(read_input())
        try:
            done, _ = await asyncio.wait((incoming, outgoing), return_when=asyncio.FIRST_COMPLETED)
            for finished in done:
                finished.result()
        finally:
            self._closed = True
            input_transport.close()
            incoming.cancel()
            await asyncio.gather(incoming, return_exceptions=True)
            for task in deliveries:
                task.cancel()
            await asyncio.gather(*deliveries, return_exceptions=True)
            for _, pending in self._requests.values():
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(
                *(task for _, task in self._requests.values()), return_exceptions=True
            )
            outgoing.cancel()
            await asyncio.gather(outgoing, return_exceptions=True)
            output_transport.close()

    async def _write(self, writer: asyncio.StreamWriter) -> None:
        while True:
            payload = await self._outgoing.get()
            writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
            await writer.drain()

    async def _receive(
        self,
        line: bytes,
        handle: Callable[[RpcRequest], Awaitable[JsonValue]],
        slots: asyncio.Semaphore,
    ) -> None:
        request_id: str | None = None
        try:
            request = RpcRequest.model_validate_json(line)
            request_id = request.id
            fingerprint = request.model_dump_json()
            existing = self._requests.get(request.id)
            if existing:
                if existing[0] != fingerprint:
                    raise ValueError("Request ID conflict")
                result = await asyncio.shield(existing[1])
            else:
                if len(self._requests) >= 8192:
                    raise ValueError("Request capacity reached")
                task = asyncio.create_task(self._dispatch(request, handle))
                self._requests[request.id] = (fingerprint, task)
                result = await asyncio.shield(task)
            await self._outgoing.put(result)
        except (ValueError, ValidationError):
            await self._outgoing.put(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32602, "message": "请求参数无效或请求 ID 冲突"},
                }
            )
        finally:
            slots.release()

    @staticmethod
    async def _dispatch(
        request: RpcRequest, handle: Callable[[RpcRequest], Awaitable[JsonValue]]
    ) -> dict[str, JsonValue]:
        try:
            return {"jsonrpc": "2.0", "id": request.id, "result": await handle(request)}
        except Exception as error:  # noqa: BLE001 - provider boundary
            error_type = type(error).__name__
            # Provider exceptions may contain diagnostics; never forward them to the renderer.
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "error": {
                    "code": -32000,
                    "message": "操作未完成，请检查参数、模型配置或服务连接",
                    "type": error_type,
                },
            }
