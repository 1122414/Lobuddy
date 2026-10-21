"""Voice ownership, stale audio, bounded transport and local-only transcription boundaries."""

import asyncio
import base64
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from core.config import Settings
from core.config.credentials import load_settings
from core.service.protocol import TRANSIENT_METHODS
from core.storage.db import Database
from core.voice.fish import FishError, synthesize
from core.voice.protocol import VoiceFrame, VoiceMute, VoiceOptions, VoicePoll, VoiceStart
from core.voice.service import VoiceService, spoken_text


@pytest.fixture
def voice(tmp_path: Path) -> VoiceService:
    settings = Settings(llm_api_key="test", fish_api_key="test-fish", data_dir=tmp_path)
    db = Database(settings)
    db.init_database(allow_desktop=True)
    return VoiceService(settings, db, AsyncMock(return_value="foreground"), AsyncMock())


class TestVoiceService:
    async def test_missing_model_never_downloads_implicitly(self, voice: VoiceService) -> None:
        result = await voice.start(VoiceStart(session_id="chat"))
        assert not result.voice_id
        assert "下载" in result.error
        assert voice.downloader is None and voice.worker is None

    async def test_frames_reject_replay_gaps_old_session_and_oversize(
        self, voice: VoiceService
    ) -> None:
        assert {"voice.frame", "voice.poll", "voice.get"} <= TRANSIENT_METHODS
        voice.status.voice_id, voice.status.state = "active", "listening"
        writer = SimpleNamespace(write=lambda _: None, drain=AsyncMock())
        voice.worker = SimpleNamespace(stdin=writer)
        value = VoiceFrame(
            voice_id="active", sequence=1, pcm=base64.b64encode(bytes(1024)).decode()
        )
        assert (await voice.frame(value))["accepted"]
        assert not (await voice.frame(value))["accepted"]
        with pytest.raises(ValueError):
            await voice.frame(value.model_copy(update={"voice_id": "old"}))
        assert not (await voice.frame(value.model_copy(update={"sequence": 3})))["accepted"]
        assert voice.status.state == "error"
        with pytest.raises(ValueError):
            VoiceFrame(voice_id="active", sequence=1, pcm="a" * 2000)

    async def test_interrupt_cancels_only_owned_turn_and_blocks_late_audio(
        self, voice: VoiceService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gate = asyncio.Event()

        async def stream(*args, **kwargs):
            yield b"\x00\x00"
            await gate.wait()
            yield b"\x01\x01"

        monkeypatch.setattr("core.voice.service.synthesize", stream)
        voice.status.voice_id, voice.status.state = "voice", "thinking"
        voice.round, voice.turn = 1, "foreground"
        voice.speaker = asyncio.create_task(voice._speak(1, "foreground"))
        voice.text_queue.put_nowait("你好")
        await asyncio.sleep(0)
        assert voice.events[-1].kind == "audio"
        await voice._interrupt()
        gate.set()
        await asyncio.sleep(0)
        assert not voice.events
        voice.cancel.assert_awaited_once_with("foreground")
        assert voice.turn == ""
        voice.turn_event("background", "text.delta", "后台任务")
        assert not voice.events

    async def test_mute_and_end_release_worker_and_no_old_session(
        self, voice: VoiceService
    ) -> None:
        voice.status.voice_id, voice.status.state = "voice", "listening"
        voice._kill_worker = AsyncMock()
        voice.turn = "foreground"
        await voice.mute(VoiceMute(voice_id="voice", muted=True))
        assert voice.status.state == "muted"
        assert voice.events[-1].kind == "interrupt"
        await voice.stop()
        assert voice.status.state == "off" and not voice.events
        with pytest.raises(ValueError):
            voice.poll(VoicePoll(voice_id="voice", after=0))
        assert voice._kill_worker.await_count == 2

    async def test_lost_client_lease_closes_worker_and_owned_turn(
        self, voice: VoiceService
    ) -> None:
        voice.status.voice_id, voice.status.state = "voice", "listening"
        voice.turn = "foreground"
        voice.lease = time.monotonic() - 10
        voice._kill_worker = AsyncMock()
        client = SimpleNamespace(aclose=AsyncMock())
        voice.fish_client = client
        voice.watchdog = asyncio.create_task(voice._watch())
        await asyncio.wait_for(voice.watchdog, 2)
        assert not voice.status.voice_id and voice.status.state == "off"
        voice._kill_worker.assert_awaited_once()
        voice.cancel.assert_awaited_once_with("foreground")
        client.aclose.assert_awaited_once()

    async def test_worker_crash_is_explicit_and_never_replays_transcript(
        self, voice: VoiceService
    ) -> None:
        voice.status.voice_id, voice.status.state = "voice", "loading"
        stream = asyncio.StreamReader()
        stream.feed_data((json.dumps({"kind": "ready"}) + "\n").encode())
        stream.feed_eof()
        voice._spawn = AsyncMock(return_value=SimpleNamespace(stdout=stream))
        await voice._listen()
        assert voice.status.state == "error"
        assert voice.events[-1].kind == "error"
        voice.submit.assert_not_awaited()
        voice._spawn.assert_awaited_once_with("listen")

    async def test_mute_blocks_late_transcript_before_waiting_for_worker_exit(
        self, voice: VoiceService
    ) -> None:
        voice.status.voice_id, voice.status.state = "voice", "listening"
        exit_worker = asyncio.Event()

        async def kill() -> None:
            assert voice.status.state == "muted"
            await exit_worker.wait()

        voice._kill_worker = kill
        muting = asyncio.create_task(voice.mute(VoiceMute(voice_id="voice", muted=True)))
        await asyncio.sleep(0)
        result = await voice.frame(
            VoiceFrame(voice_id="voice", sequence=1, pcm=base64.b64encode(bytes(1024)).decode())
        )
        assert not result["accepted"]
        exit_worker.set()
        await muting
        voice.submit.assert_not_awaited()

    async def test_provider_failure_does_not_block_local_resource_cleanup(
        self, voice: VoiceService
    ) -> None:
        voice.status.voice_id, voice.status.state = "voice", "speaking"
        voice.turn = "foreground"
        voice.cancel.side_effect = httpx.ConnectError("offline")
        voice._kill_worker = AsyncMock()
        client = SimpleNamespace(aclose=AsyncMock())
        voice.fish_client = client
        await voice.stop()
        assert voice.status.state == "off" and not voice.status.voice_id
        voice._kill_worker.assert_awaited_once()
        client.aclose.assert_awaited_once()

    def test_audio_not_written_to_database_and_overflow_is_explicit(
        self, voice: VoiceService
    ) -> None:
        voice.status.voice_id = "voice"
        for _ in range(129):
            voice._emit("audio", pcm=b"\x00\x00" * 2048)
        assert voice.status.state == "error"
        assert len(voice.events) == 1 and voice.events[0].kind == "error"
        result = voice.poll(VoicePoll(voice_id="voice", after=0))
        assert result["events"][0]["kind"] == "error"
        voice.poll(VoicePoll(voice_id="voice", after=voice.sequence))
        assert not voice.events
        with voice.repo.db.get_connection() as conn:
            assert not conn.execute(
                "SELECT value FROM app_settings WHERE value LIKE '%pcm%'"
            ).fetchall()

    def test_preferences_survive_and_no_automatic_model_switch(self, voice: VoiceService) -> None:
        voice.configure(VoiceOptions(fish_model="s2.1-pro", silence_ms=900))
        restarted = VoiceService(voice.settings, voice.repo.db, voice.submit, voice.cancel)
        assert restarted.options.fish_model == "s2.1-pro"
        assert restarted.options.silence_ms == 900
        assert (
            spoken_text('你好。```python\nprint("秘密")\n```[看这里](https://example.com)')
            == "你好。看这里"
        )
        assert spoken_text("你好```未闭合的代码") == "你好"
        assert spoken_text("。\n！？") == ""

    async def test_fish_402_has_distinct_api_credit_message_and_no_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = []

        def respond(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(402, json={"message": "private upstream details"})

        client_type = httpx.AsyncClient
        monkeypatch.setattr(
            "core.voice.fish.httpx.AsyncClient",
            lambda **kwargs: client_type(transport=httpx.MockTransport(respond)),
        )
        with pytest.raises(FishError, match="独立于网页积分"):
            _ = [chunk async for chunk in synthesize("你好", "secret", "s2.1-pro")]
        assert len(calls) == 1
        assert calls[0].headers["model"] == "s2.1-pro"
        assert b"e4a66454f7a44f63a2cc9e8c044d701d" in calls[0].content

    def test_explicit_optional_key_wins_over_older_keychain_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.setenv("FISH_API_KEY", "new-fish")
        monkeypatch.setattr(
            "core.config.credentials.read_credentials",
            lambda: {"llm_api_key": "primary", "fish_api_key": "old-fish"},
        )
        assert load_settings().fish_api_key == "new-fish"

    def test_primary_environment_does_not_hide_fish_keychain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("core.config.credentials.sys.platform", "darwin")
        monkeypatch.setenv("LLM_API_KEY", "primary-from-env")
        monkeypatch.delenv("FISH_API_KEY", raising=False)
        monkeypatch.setattr(
            "core.config.credentials.read_credentials",
            lambda: {"llm_api_key": "old-primary", "fish_api_key": "fish-store"},
        )
        settings = load_settings()
        assert settings.llm_api_key == "primary-from-env"
        assert settings.fish_api_key == "fish-store"
