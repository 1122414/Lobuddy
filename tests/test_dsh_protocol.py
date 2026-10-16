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
