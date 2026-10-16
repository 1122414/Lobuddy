"""Real DSH attachment, vision, usage and exactly-once growth acceptance."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from scripts.smoke_headless_service import Client


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="lobuddy-p5-image-") as directory:
        base = Path(directory)
        source = base / "shapes.png"
        image = Image.new("RGB", (400, 200), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 170, 170), fill="red")
        draw.ellipse((220, 20, 370, 170), fill="blue")
        image.save(source)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.service",
            "--data-dir",
            str(base / "data"),
            "--workspace",
            str(base / "workspace"),
            cwd=root,
            env=os.environ.copy(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        client = Client(process)

        async def call(method: str, params: dict[str, Any]) -> Any:
            return await client.request(str(uuid.uuid4()), method, params)

        try:
            attachment = await call("image.import", {"path": str(source)})
            session = await call("session.create", {})
            request_id = str(uuid.uuid4())
            params = {
                "session_id": session["id"],
                "text": "只按图片描述左边和右边各是什么颜色、什么形状。",
                "image_id": attachment["image_id"],
            }
            turn = await client.request(request_id, "turn.send", params)
            await asyncio.wait_for(client.completed(turn["turn_id"], False), 150)
            result = await call("task.get", {"turn_id": turn["turn_id"]})
            assert result["status"] == "completed", result["status"]
            assert all(
                word in result["output_text"] for word in ("红", "蓝", "方", "圆")
            ), "Image contents not correctly recognized"
            progress = await call("progress.get", {})
            assert progress["usage"]["input"] > 0 and progress["usage"]["output"] > 0
            again = await client.request(request_id, "turn.send", params)
            assert again["turn_id"] == turn["turn_id"]
            assert await call("progress.get", {}) == progress
            history = await call("session.history", {"session_id": session["id"]})
            assert len(history) == 2 and history[0]["image_path"] == attachment["image_id"]
            print(
                "PASS: real DSH image admission and correct two-shape vision response", flush=True
            )
            print(
                "PASS: observed model usage, durable image history and duplicate request without reward duplication",
                flush=True,
            )
        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
