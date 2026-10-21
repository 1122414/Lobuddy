"""Opt-in synthetic audio through real local ASR, DSH and Fish; not a physical-mic test."""

import argparse
import asyncio
import base64
import json
import math
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

from core.agent.dsh.runtime import DshRuntime
from core.config.credentials import load_settings
from core.service.application import ApplicationService
from core.service.protocol import RpcRequest
from core.storage.db import Database
from core.voice.fish import synthesize
from core.voice.protocol import VoiceFrame, VoicePoll, VoiceStart


async def run(model_dir: Path, rounds: int, clip: Path) -> None:
    settings = load_settings()
    if not clip.exists():
        chunks = [
            chunk
            async for chunk in synthesize(
                "你好，請只回答我在。", settings.fish_api_key, "s2.1-pro-free"
            )
        ]
        audio = np.frombuffer(b"".join(chunks), dtype="<i2")
        pcm = np.interp(np.arange(0, len(audio), 1.5), np.arange(len(audio)), audio).astype("<i2")
        clip.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(clip), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(pcm.tobytes())
    with wave.open(str(clip)) as source:
        assert source.getframerate() == 16000 and source.getnchannels() == 1
        samples = source.readframes(source.getnframes())
    latencies = []
    with tempfile.TemporaryDirectory(prefix="lobuddy-voice-real-") as temporary:
        settings.data_dir = Path(temporary) / "data"
        settings.workspace_path = Path(temporary) / "workspace"
        settings.workspace_path.mkdir()
        db = Database(settings)
        db.init_database(allow_desktop=True)
        runtime = DshRuntime(
            home=settings.data_dir / "dsh-home",
            workspace=settings.workspace_path,
            plugin=Path(__file__).resolve().parents[1] / "bridge/dsh/dist/index.js",
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )
        engine_events = []
        service = ApplicationService(
            settings,
            db,
            runtime,
            lambda event: engine_events.append((time.monotonic(), event.kind, event.turn_id)),
        )
        service.voice.models = model_dir.resolve()
        session = await service.handle(
            RpcRequest(jsonrpc="2.0", id="session", method="session.create", params={})
        )
        voice = service.voice
        session_id = session.get("id") if isinstance(session, dict) else None
        if not isinstance(session_id, str):
            raise TypeError("语音验收未取得有效会话 ID")
        status = await voice.start(VoiceStart(session_id=session_id))
        identity = status.voice_id
        assert identity, status.error
        sequence = 0
        cursor = 0
        received = []
        running = True

        async def poll() -> None:
            nonlocal cursor
            while running:
                result = voice.poll(VoicePoll(voice_id=identity, after=cursor))
                if result["status"]["state"] == "error":
                    raise RuntimeError(result["status"]["error"])
                for event in result["events"]:
                    cursor = event["sequence"]
                    received.append((time.monotonic(), event))
                await asyncio.sleep(0.04)

        collector = asyncio.create_task(poll())
        try:
            async with asyncio.timeout(40):
                while voice.status.state == "loading":
                    await asyncio.sleep(0.05)
            assert voice.status.state == "listening", voice.status.error
            await service._ensure_engine()
            for index in range(rounds):
                old = len(received)
                old_engine = len(engine_events)
                data = bytes(1024 * 10) + samples
                data += bytes((-len(data)) % 1024)
                ended = time.monotonic()
                for offset in range(0, len(data), 1024):
                    sequence += 1
                    await voice.frame(
                        VoiceFrame(
                            voice_id=identity,
                            sequence=sequence,
                            pcm=base64.b64encode(data[offset : offset + 1024]).decode(),
                        )
                    )
                    await asyncio.sleep(0.032)
                ended = time.monotonic()
                async with asyncio.timeout(60):
                    while not any(event["kind"] == "audio.end" for _, event in received[old:]):
                        if collector.done():
                            await collector
                        sequence += 1
                        await voice.frame(
                            VoiceFrame(
                                voice_id=identity,
                                sequence=sequence,
                                pcm=base64.b64encode(bytes(1024)).decode(),
                            )
                        )
                        await asyncio.sleep(0.032)
                events = received[old:]
                transcripts = [
                    event["text"] for _, event in events if event["kind"] == "transcript"
                ]
                audio_times = [timestamp for timestamp, event in events if event["kind"] == "audio"]
                assert len(transcripts) == 1 and audio_times
                latency = audio_times[0] - ended
                asr_time = next(
                    timestamp for timestamp, event in events if event["kind"] == "transcript"
                )
                first_text = next(
                    (
                        timestamp
                        for timestamp, kind, _ in engine_events[old_engine:]
                        if kind in ("text.delta", "text.final")
                    ),
                    audio_times[0],
                )
                latencies.append(latency)
                print(
                    json.dumps(
                        {
                            "round": index + 1,
                            "transcript": transcripts[0],
                            "response_seconds": round(latency, 3),
                            "asr_seconds": round(asr_time - ended, 3),
                            "model_first_text_seconds": round(first_text - asr_time, 3),
                            "text_to_audio_seconds": round(audio_times[0] - first_text, 3),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            print(
                json.dumps(
                    {
                        "rounds": rounds,
                        "p95_seconds": round(sorted(latencies)[math.ceil(rounds * 0.95) - 1], 3),
                        "physical_microphone": False,
                    }
                ),
                flush=True,
            )
        finally:
            running = False
            collector.cancel()
            await asyncio.gather(collector, return_exceptions=True)
            await service.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--clip", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(run(args.model_dir, args.rounds, args.clip))


if __name__ == "__main__":
    main()
