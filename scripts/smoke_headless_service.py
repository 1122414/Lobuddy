"""Exercise the actual stdio service with a real model and disposable data.

Run with a Qt-free Python to verify deployment independence. Uses local .env credentials.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


class Client:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
        self.events: list[dict[str, Any]] = []
        self.responses: dict[str, dict[str, Any]] = {}

    async def read(self) -> None:
        assert self.process.stdout is not None
        line = await asyncio.wait_for(self.process.stdout.readline(), 90)
        if not line:
            raise RuntimeError("Service stdout closed unexpectedly")
        message = json.loads(line)
        if message.get("method") == "event":
            self.events.append(message["params"])
        else:
            self.responses[message["id"]] = message

    async def request(self, identity: str, method: str, params: dict[str, Any]) -> Any:
        assert self.process.stdin is not None
        self.responses.pop(identity, None)
        self.process.stdin.write(
            (
                json.dumps({"jsonrpc": "2.0", "id": identity, "method": method, "params": params})
                + "\n"
            ).encode()
        )
        await self.process.stdin.drain()
        while identity not in self.responses:
            await self.read()
        response = self.responses.pop(identity)
        assert "error" not in response, response.get("error")
        return response["result"]

    async def completed(self, turn_id: str, approve: bool = False) -> None:
        handled: set[str] = set()
        while True:
            previous_count = len(self.events)
            for event in list(self.events):
                if event["turn_id"] != turn_id:
                    continue
                if event["kind"] == "approval.requested":
                    identity = event["data"]["approval_id"]
                    if identity not in handled:
                        handled.add(identity)
                        await self.request(
                            identity,
                            "approval.resolve",
                            {"approval_id": identity, "approved": approve},
                        )
                if event["kind"] in ("turn.completed", "turn.failed", "turn.cancelled"):
                    assert event["kind"] == "turn.completed", event["data"]
                    return
            if len(self.events) == previous_count:
                await self.read()

    async def close(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()
        await asyncio.wait_for(self.process.wait(), 15)
        assert self.process.returncode == 0, self.process.returncode


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="lobuddy-stdio-") as directory:
        data = Path(directory)
        workspace = data / "workspace"
        workspace.mkdir()

        async def launch() -> Client:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "app.service",
                "--data-dir",
                str(data / "data"),
                "--workspace",
                str(workspace),
                cwd=root,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            return Client(process)

        client = await launch()
        try:
            assert (await client.request("health", "service.health", {}))["protocol"] == 1
            session = await client.request("session", "session.create", {"title": "协议验收"})
            params = {"session_id": session["id"], "text": "只回复你好。"}
            first = await client.request("send-once", "turn.send", params)
            await client.completed(first["turn_id"])
            repeated = await client.request("send-once", "turn.send", params)
            assert repeated["turn_id"] == first["turn_id"]
            history = await client.request(
                "history", "session.history", {"session_id": session["id"]}
            )
            assert len(history) == 2
            print("PASS: real stdio model turn, history and duplicate request identity", flush=True)
            for allow in (False, True):
                prompt = (
                    "现在我明确允许本次写入。" if allow else ""
                ) + "请调用 lobuddy_write_file 将 acceptance.txt 写入 hello；被拒绝就停止，只尝试一次。"
                task = await client.request(
                    f"write-{allow}", "turn.send", {"session_id": session["id"], "text": prompt}
                )
                await client.completed(task["turn_id"], approve=allow)
                assert any(
                    event["turn_id"] == task["turn_id"] and event["kind"] == "approval.requested"
                    for event in client.events
                )
                assert (workspace / "acceptance.txt").exists() == allow
            assert (workspace / "acceptance.txt").read_text().strip() == "hello"
            print("PASS: stdio approval denial/allowance controls real effects", flush=True)
            focus = await client.request("focus", "focus.start", {"minutes": 1})
            assert focus["state"] == "focusing"
            assert (await client.request("pause", "focus.pause", {}))["state"] == "paused"
            await client.close()
            client = await launch()
            restored = await client.request("send-once", "turn.send", params)
            assert restored["turn_id"] == first["turn_id"] and restored["status"] == "completed"
            assert not (await client.request("health2", "service.health", {}))["connected"]
            print(
                "PASS: restart retains result without launching model or replaying task", flush=True
            )
        finally:
            if client.process.returncode is None:
                await client.close()
        print("PASS: stdio EOF exits normally", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
