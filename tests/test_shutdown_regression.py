import json
import os
import subprocess
import sys
import tempfile
import time


def test_process_with_active_subagent_can_exit():
    script = {"responses": []}
    fd, script_path = tempfile.mkstemp(suffix=".json", text=True)
    with os.fdopen(fd, "w") as f:
        json.dump(script, f)

    code = f"""
import asyncio
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["LOBUDDY_SUBAGENT_TEST_SCRIPT"] = {repr(script_path)}

import core.agent.subagent_factory as _sf
_original_worker = _sf._run_subagent_worker_process

def _delayed_worker(*args, **kwargs):
    time.sleep(30)
    return _original_worker(*args, **kwargs)

_sf._run_subagent_worker_process = _delayed_worker

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

async def run():
    await factory.run_subagent("image_analysis", "hang", media_paths=[])

thread = threading.Thread(target=lambda: asyncio.run(run()), daemon=True)
thread.start()
time.sleep(1)
sys.exit(0)
"""

    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        raise AssertionError("Process with active subagent did not exit within 5 seconds")
    finally:
        os.unlink(script_path)
