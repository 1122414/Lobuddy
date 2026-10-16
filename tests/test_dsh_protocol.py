"""Malformed or reordered plugin events must stop delivery, never be silently accepted."""

from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from core.agent.dsh.runtime import BridgeEvent, DshRuntime


def runtime(tmp_path: Path) -> DshRuntime:
    return DshRuntime(
        home=tmp_path,
        workspace=tmp_path,
        plugin=tmp_path / "plugin.js",
        api_key="test",
        base_url="https://example.invalid",
        model="test",
    )


class TestDshProtocol:
    @pytest.mark.parametrize("sequences", [[2], [1, 1], [1, 3]])
    async def test_missing_or_replayed_sequence_closes_stream(
        self, tmp_path: Path, sequences: list[int]
    ) -> None:
        instance = runtime(tmp_path)
        lines = [
            BridgeEvent(
                sessionId="s",
                taskId="t",
                turnId="r",
                sequence=seq,
                kind="text.delta",
                data={"text": "hello"},
            ).model_dump_json()
            for seq in sequences
        ]
        payload = "".join(f"data: {line}\n\n" for line in lines)
        instance._http = httpx.AsyncClient(
            base_url="http://127.0.0.1:12345",
            transport=httpx.MockTransport(lambda req: httpx.Response(200, text=payload)),
        )
        try:
            with pytest.raises(RuntimeError, match="reordered"):
                async for _ in instance.events():
                    pass
            assert not instance.ready.is_set()
        finally:
            await instance.close()

    def test_event_identity_and_kind_are_required(self) -> None:
        with pytest.raises(ValidationError):
            BridgeEvent.model_validate({"sessionId": "s", "kind": "anything", "data": {}})

    async def test_unknown_delivery_does_not_retry(self, tmp_path: Path) -> None:
        calls = 0

        def respond(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ReadError("Outcome unknown")

        instance = runtime(tmp_path)
        instance._http = httpx.AsyncClient(
            base_url="http://127.0.0.1:12345", transport=httpx.MockTransport(respond)
        )
        try:
            with pytest.raises(httpx.ReadError):
                await instance.call("turn.send", {})
            assert calls == 1
        finally:
            await instance.close()

    async def test_cancel_during_sdk_start_waits_then_closes_child(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio
        import threading

        import core.agent.dsh.runtime as module

        started = threading.Event()
        release = threading.Event()
        lifecycle: list[str] = []

        class Harness:
            def __init__(self, config: object) -> None:
                pass

            def start(self) -> None:
                started.set()
                assert release.wait(2)
                lifecycle.append("launched")

            def close(self) -> None:
                lifecycle.append("closed")

        monkeypatch.setattr(module, "DeepSeekHarness", Harness)
        monkeypatch.setattr(module, "version", lambda _: module.DSH_VERSION)
        instance = runtime(tmp_path)
        instance.plugin.write_text("export default {}")
        task = asyncio.create_task(instance.start())
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert lifecycle == ["launched", "closed"]
        assert instance._harness is None and instance._launch is None
