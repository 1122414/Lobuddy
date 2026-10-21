"""Single voice owner, local worker lifecycle, round isolation and bounded audio delivery."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import importlib.util
import json
import os
import re
import sys
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import JsonValue

from core.config import Settings
from core.storage.db import Database
from core.storage.settings_repo import SettingsRepository
from core.voice.fish import FishError, synthesize
from core.voice.protocol import (
    MODEL_REVISION,
    VoiceEvent,
    VoiceFrame,
    VoiceMute,
    VoiceOptions,
    VoicePoll,
    VoiceReference,
    VoiceStart,
    VoiceStatus,
)


def spoken_text(text: str) -> str:
    text = re.sub(r"```.*?(?:```|$)", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`|!\[[^]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*#_>|]", "", text).strip()
    return text if re.search(r"\w", text) else ""


class VoiceService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        submit: Callable[[str, str, str], Awaitable[str]],
        cancel: Callable[[str], Awaitable[None]],
        prepare: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.settings, self.submit, self.cancel = settings, submit, cancel
        self.prepare = prepare
        self.fish_client: httpx.AsyncClient | None = None
        self.repo = SettingsRepository(db)
        self.options = VoiceOptions.model_validate_json(
            self.repo.get_setting("voice_options") or "{}"
        )
        self.models = settings.data_dir / "voice-models" / "small"
        self.status = VoiceStatus(
            fish_configured=bool(settings.fish_api_key),
            silence_ms=self.options.silence_ms,
            fish_model=self.options.fish_model,
        )
        self.events: deque[VoiceEvent] = deque(maxlen=128)
        self.sequence = 0
        self.round = 0
        self.frame_sequence = 0
        self.turn = ""
        self.lease = 0.0
        self.worker: asyncio.subprocess.Process | None = None
        self.download_worker: asyncio.subprocess.Process | None = None
        self.listener: asyncio.Task[None] | None = None
        self.downloader: asyncio.Task[None] | None = None
        self.watchdog: asyncio.Task[None] | None = None
        self.speaker: asyncio.Task[None] | None = None
        self.text_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=32)
        self.text = ""
        self.sent = 0
        self.lock = asyncio.Lock()

    def view(self) -> VoiceStatus:
        ready = self.models / "ready"
        self.status.model_ready = bool(
            importlib.util.find_spec("faster_whisper")
            and ready.is_file()
            and ready.read_text(encoding="ascii") == MODEL_REVISION
        )
        return self.status

    def configure(self, options: VoiceOptions) -> VoiceStatus:
        if self.status.voice_id:
            raise ValueError("请先结束语音再修改设置")
        self.options = options
        self.repo.set_setting("voice_options", options.model_dump_json())
        self.status.silence_ms = options.silence_ms
        self.status.fish_model = options.fish_model
        return self.view()

    async def _spawn(self, mode: str) -> asyncio.subprocess.Process:
        # Workers never receive provider keys; no automatic downloads while listening.
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "PATH",
                "HOME",
                "TMPDIR",
                "SYSTEMROOT",
                "SSL_CERT_FILE",
                "SSL_CERT_DIR",
            }
        }
        environment.update(
            {
                "PYTHONUNBUFFERED": "1",
                "PYTHONNOUSERSITE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "HF_HUB_DISABLE_XET": "1",
                "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            }
        )
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "core.voice.worker",
            mode,
            str(self.models),
            "--silence-ms",
            str(self.options.silence_ms),
            cwd=Path(__file__).resolve().parents[2],
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=65536,
        )

    def download(self) -> VoiceStatus:
        if not self.status.downloading and not self.view().model_ready:
            self.status.downloading = True
            self.status.error = ""
            self.downloader = asyncio.create_task(self._download())
        return self.view()

    async def _download(self) -> None:
        try:
            self.models.mkdir(parents=True, exist_ok=True)
            self.download_worker = await self._spawn("download")
            code = await self.download_worker.wait()
            if code or not self.view().model_ready:
                self.status.error = "本地模型下载或校验失败，请检查网络后重试；文字仍可用"
        except OSError:
            self.status.error = "语音组件未安装，无法下载本地模型"
        finally:
            self.status.downloading = False

    async def start(self, params: VoiceStart) -> VoiceStatus:
        async with self.lock:
            if self.status.voice_id:
                raise ValueError("已有语音会话，请先结束")
            if not self.view().model_ready:
                self.status.error = "请先在设置中下载本地语音模型"
                return self.view()
            if not self.settings.fish_api_key:
                self.status.error = "请先配置 Fish Audio 凭据"
                return self.view()
            self.fish_client = httpx.AsyncClient(trust_env=False, timeout=30)
            self.status.voice_id = str(uuid.uuid4())
            self.status.session_id, self.status.state, self.status.error = (
                params.session_id,
                "loading",
                "",
            )
            self.events.clear()
            self.sequence = self.round = self.frame_sequence = 0
            self.lease = time.monotonic()
            self.listener = asyncio.create_task(self._listen())
            self.watchdog = asyncio.create_task(self._watch())
            return self.view()

    def _check(self, params: VoiceReference) -> None:
        if not self.status.voice_id or params.voice_id != self.status.voice_id:
            raise ValueError("语音会话已失效")

    async def _listen(self) -> None:
        try:
            base_round = self.round
            self.worker = await self._spawn("listen")
            assert self.worker.stdout
            line = await asyncio.wait_for(self.worker.stdout.readline(), 30)
            if json.loads(line).get("kind") != "ready":
                raise ValueError("Worker handshake failed")
            if self.prepare:
                await self.prepare()
            self.status.state = "listening"
            while line := await self.worker.stdout.readline():
                packet = json.loads(line)
                if self.status.state in ("muted", "off", "error"):
                    continue
                kind = packet.get("kind")
                if kind == "speech":
                    self.round = base_round + int(packet["round"])
                    self._emit("interrupt")
                    await self._interrupt(clear_events=False)
                    self.status.state = "listening"
                elif base_round + int(packet.get("round", -1)) == self.round:
                    if kind == "transcript":
                        text = str(packet.get("text", "")).strip()
                        if text:
                            self._emit("transcript", text=text)
                            self.status.state = "thinking"
                            self.turn = await self.submit(
                                self.status.session_id,
                                text,
                                f"voice-{self.status.voice_id}-{self.round}",
                            )
                            self.text, self.sent = "", 0
                            self.text_queue = asyncio.Queue(maxsize=32)
                            self.speaker = asyncio.create_task(self._speak(self.round, self.turn))
                    elif kind in ("error", "overload"):
                        self._fail("本地识别未完成，请稍后再说；未发送不完整文字")
            raise RuntimeError("Worker stopped")
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, RuntimeError, TimeoutError):
            self._fail("语音或模型服务准备失败，请结束语音后重新开启")

    async def frame(self, params: VoiceFrame) -> dict[str, JsonValue]:
        self._check(params)
        if self.status.state in ("loading", "muted", "off", "error"):
            return {"accepted": False}
        if params.sequence <= self.frame_sequence:
            return {"accepted": False}
        if params.sequence != self.frame_sequence + 1:
            self._fail("音频帧丢失，请重新开启语音")
            return {"accepted": False}
        data = base64.b64decode(params.pcm, validate=True)
        if len(data) != 1024:
            raise ValueError("Invalid PCM frame")
        self.frame_sequence = params.sequence
        if not self.worker or not self.worker.stdin:
            raise ValueError("语音工作进程不可用")
        self.worker.stdin.write((json.dumps({"pcm": params.pcm}) + "\n").encode())
        await asyncio.wait_for(self.worker.stdin.drain(), 1)
        return {"accepted": True}

    def poll(self, params: VoicePoll) -> dict[str, Any]:
        self._check(params)
        self.lease = time.monotonic()
        if params.playing and self.status.state == "listening":
            self.status.state = "speaking"
        elif (
            not params.playing
            and self.status.state == "speaking"
            and self.speaker
            and self.speaker.done()
        ):
            self.status.state = "listening"
        while self.events and self.events[0].sequence <= params.after:
            self.events.popleft()
        return {
            "status": self.view().model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in self.events],
        }

    def _emit(self, kind: Any, *, text: str = "", pcm: bytes = b"") -> None:
        if len(self.events) == self.events.maxlen:
            self.events.clear()
            self.status.state = "error"
            self.status.error = "音频播放端未及时响应，请重新开启语音"
            kind, text, pcm = "error", self.status.error, b""
        self.sequence += 1
        self.events.append(
            VoiceEvent(
                voice_id=self.status.voice_id,
                session_id=self.status.session_id,
                turn_id=self.turn,
                round_id=self.round,
                sequence=self.sequence,
                kind=kind,
                text=text,
                pcm=base64.b64encode(pcm).decode(),
            )
        )

    def _fail(self, message: str) -> None:
        self.status.error = message
        self.status.state = "error"
        self._emit("error", text=message)

    async def _speak(self, identity: int, turn: str) -> None:
        try:
            while (text := await self.text_queue.get()) is not None:
                clean = spoken_text(text)
                if not clean:
                    continue
                async for pcm in synthesize(
                    clean,
                    self.settings.fish_api_key,
                    self.options.fish_model,
                    client=self.fish_client,
                ):
                    if (
                        identity != self.round
                        or turn != self.turn
                        or self.status.state in ("error", "muted", "off")
                    ):
                        return
                    self.status.state = "speaking"
                    self._emit("audio", pcm=pcm)
            if identity == self.round and turn == self.turn:
                self._emit("audio.end")
                self.status.state = "listening"
        except FishError as error:
            self._fail(str(error))

    def turn_event(self, turn_id: str, kind: str, output: str) -> None:
        if turn_id != self.turn or not self.speaker or self.speaker.done():
            return
        if self.text_queue.qsize() >= 30:
            self.speaker.cancel()
            self._fail("回答超过语音播放容量，文字结果仍可查看")
            return
        if kind in ("text.delta", "text.final"):
            self.text = output
            # Wait while a code fence is open; do not narrate code or tool parameters.
            if self.text[:].count("```") % 2:
                return
            remaining = self.text[self.sent :]
            ends = list(re.finditer(r"[。！？!?\n]", remaining))
            if ends and self.text_queue.qsize() < 30:
                end = ends[-1].end() + self.sent
                self.text_queue.put_nowait(self.text[self.sent : end])
                self.sent = end
        elif kind == "turn.completed":
            if self.text_queue.qsize() < 30:
                self.text_queue.put_nowait(output[self.sent :])
                self.text_queue.put_nowait(None)
        elif kind in ("turn.failed", "turn.interrupted"):
            self.speaker.cancel()
            self._fail("本轮模型对话未完成，请查看文字任务状态后重试")
        elif kind == "turn.cancelled":
            self.speaker.cancel()
            self._emit("interrupt")
            self.status.state = "listening"

    async def _interrupt(self, *, clear_events: bool = True) -> None:
        if self.speaker:
            self.speaker.cancel()
            await asyncio.gather(self.speaker, return_exceptions=True)
            self.speaker = None
        if clear_events:
            self.events.clear()
        old, self.turn = self.turn, ""
        if old:
            with contextlib.suppress(RuntimeError, ValueError, TimeoutError, httpx.HTTPError):
                await asyncio.wait_for(self.cancel(old), 5)

    async def _kill_worker(self) -> None:
        if self.listener:
            self.listener.cancel()
            await asyncio.gather(self.listener, return_exceptions=True)
            self.listener = None
        await self._terminate(self.worker)
        self.worker = None

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process | None) -> None:
        if process and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 3)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()

    async def mute(self, params: VoiceMute) -> VoiceStatus:
        self._check(params)
        async with self.lock:
            self.status.state = "muted"
            await self._kill_worker()
            await self._interrupt()
            self.round += 1
            self._emit("interrupt")
            self.frame_sequence = 0
            if params.muted:
                self.status.state = "muted"
            else:
                self.status.state = "loading"
                self.listener = asyncio.create_task(self._listen())
            return self.view()

    async def _watch(self) -> None:
        while self.status.voice_id:
            await asyncio.sleep(1)
            if time.monotonic() - self.lease > 5:
                await self.stop()
                return

    async def stop(self) -> VoiceStatus:
        async with self.lock:
            if self.watchdog and self.watchdog is not asyncio.current_task():
                self.watchdog.cancel()
                await asyncio.gather(self.watchdog, return_exceptions=True)
            self.watchdog = None
            self.status.state = "off"
            await self._kill_worker()
            await self._interrupt()
            self.events.clear()
            if self.fish_client:
                await self.fish_client.aclose()
                self.fish_client = None
            self.status.voice_id = self.status.session_id = ""
            self.status.state = "off"
            return self.view()

    async def close(self) -> None:
        await self.stop()
        if self.downloader:
            self.downloader.cancel()
            await asyncio.gather(self.downloader, return_exceptions=True)
        await self._terminate(self.download_worker)
