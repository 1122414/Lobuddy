import json
import os
import subprocess
import sys
import tempfile
import time


def test_process_with_active_subagent_can_exit():
    script = {"responses": [{"__sleep": 30}]}
    fd, script_path = tempfile.mkstemp(suffix=".json", text=True)
    with os.fdopen(fd, "w") as f:
        json.dump(script, f)

    code = f"""
import asyncio
import multiprocessing as mp
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["LOBUDDY_SUBAGENT_TEST_SCRIPT"] = {repr(script_path)}

from app.config import Settings
from core.agent.subagent_factory import SubagentFactory

settings = Settings(
    llm_api_key="test-key",
    llm_base_url="https://api.openai.com/v1",
    llm_model="kimi-2.5",
    llm_multimodal_model="qwen3.5-omni-plus",
    workspace_path=Path(tempfile.mkdtemp()),
    task_timeout=60,
    nanobot_max_iterations=5,
)
factory = SubagentFactory(settings)

started = threading.Event()
_original_start = mp.Process.start

def _patched_start(self):
    _original_start(self)
    started.set()

mp.Process.start = _patched_start

async def run():
    await factory.run_subagent("image_analysis", "hang", media_paths=[])

thread = threading.Thread(target=lambda: asyncio.run(run()), daemon=True)
thread.start()
assert started.wait(timeout=5), "Subagent process did not start in time"
time.sleep(0.5)
sys.exit(0)
"""

    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        proc.wait(timeout=5)
        stderr = proc.stderr.read() if proc.stderr else ""
        assert proc.returncode == 0, f"Child exited with code {proc.returncode}. stderr: {stderr}"
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        raise AssertionError("Process with active subagent did not exit within 5 seconds")
    finally:
        os.unlink(script_path)
