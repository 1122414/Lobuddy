"""Local-only VAD/ASR subprocess. Audio is bounded in memory and never written to disk."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort  # type: ignore[import-untyped]
from faster_whisper import WhisperModel  # type: ignore[import-untyped]
from faster_whisper.vad import get_vad_model  # type: ignore[import-untyped]

from core.voice.protocol import MODEL_REVISION


class StreamingVAD:
    """Carry Silero v6 recurrent state between 32 ms frames (pinned faster-whisper 1.2.1)."""

    def __init__(self) -> None:
        ort.disable_telemetry_events()
        self.session = get_vad_model().session
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)

    def probability(self, frame: Any) -> float:
        data = np.concatenate([self.context, frame.reshape(1, 512)], axis=1)
        output, self.h, self.c = self.session.run(None, {"input": data, "h": self.h, "c": self.c})
        self.context = frame[-64:].reshape(1, 64)
        return float(output.reshape(-1)[0])


def download(path: Path) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(
        "Systran/faster-whisper-small",
        revision=MODEL_REVISION,
        local_dir=path,
        allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"],
    )
    # Constructing validates the complete snapshot before marking it ready.
    WhisperModel(str(path), device="cpu", compute_type="int8", local_files_only=True)
    (path / "ready").write_text(MODEL_REVISION, encoding="ascii")


def run(path: Path, silence_ms: int) -> None:
    model = WhisperModel(
        str(path), device="cpu", compute_type="int8", cpu_threads=4, local_files_only=True
    )
    vad = StreamingVAD()
    lock = threading.Lock()

    def emit(value: dict[str, Any]) -> None:
        with lock:
            print(json.dumps(value, ensure_ascii=False), flush=True)

    def transcribe(audio: Any, identity: int) -> None:
        try:
            segments, _ = model.transcribe(
                audio,
                beam_size=1,
                language="zh",
                condition_on_previous_text=False,
                vad_filter=False,
                temperature=0,
                no_speech_threshold=0.6,
            )
            text = "".join(s.text for s in segments if s.avg_logprob > -1).strip()
            emit({"kind": "transcript", "round": identity, "text": text[:4000]})
        except (RuntimeError, ValueError, OSError):
            emit({"kind": "error", "round": identity})

    emit({"kind": "ready"})
    previous: deque[Any] = deque(maxlen=10)
    frames: list[Any] = []
    active, voiced, silent, identity = False, 0, 0, 0
    pending = None
    with ThreadPoolExecutor(max_workers=1) as executor:
        for line in sys.stdin:
            if len(line) > 4096:
                raise ValueError("Frame too large")
            packet = json.loads(line)
            frame = np.frombuffer(base64.b64decode(packet["pcm"], validate=True), dtype="<i2")
            if len(frame) != 512:
                raise ValueError("Invalid frame")
            audio = frame.astype(np.float32) / 32768
            probability = vad.probability(audio)
            previous.append(audio)
            voiced = voiced + 1 if probability >= 0.6 else 0
            if not active and voiced >= 3:
                identity += 1
                active, silent = True, 0
                frames = list(previous)
                emit({"kind": "speech", "round": identity})
            elif active:
                frames.append(audio)
                silent = silent + 32 if probability < 0.35 else 0
                if silent >= silence_ms or len(frames) >= 938:
                    active = False
                    # Bound queued ASR work; never replay stale utterances later.
                    if pending is None or pending.done():
                        pending = executor.submit(transcribe, np.concatenate(frames), identity)
                    else:
                        emit({"kind": "overload", "round": identity})
                    frames = []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["download", "listen"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--silence-ms", type=int, default=700)
    args = parser.parse_args()
    if args.mode == "download":
        download(args.path)
    else:
        run(args.path, args.silence_ms)


if __name__ == "__main__":
    main()
