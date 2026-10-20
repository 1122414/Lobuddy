"""Baseline benchmark for Lobuddy - lightweight version without PySide6 dependency."""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

# Mock nanobot before imports
sys.modules["nanobot"] = MagicMock()
sys.modules["nanobot.bus"] = MagicMock()
sys.modules["nanobot.bus.events"] = MagicMock()

from app.config import Settings
from core.runtime.token_meter import TokenMeter
from core.tools.tool_policy import ToolPolicy
from core.safety.guardrails import SafetyGuardrails
from core.storage.ability_repo import AbilityRepository
from core.storage.settings_repo import SettingsRepository
from core.storage.pet_repo import PetRepository
from core.storage.db import Database


TEST_TASKS = [
    {"id": "qa_1", "input": "What is Python?", "type": "simple_qa"},
    {"id": "qa_2", "input": "Explain recursion", "type": "simple_qa"},
    {"id": "tool_1", "input": "Read file workspace/test.txt", "type": "tool_call"},
    {"id": "tool_2", "input": "List files in workspace", "type": "tool_call"},
    {"id": "long_1", "input": "A" * 5000, "type": "long_session"},
    {"id": "long_2", "input": "B" * 10000, "type": "long_session"},
    {"id": "img_1", "input": "Analyze this image", "type": "image_analysis", "image": "test.png"},
    {"id": "multi_1", "input": "Task 1", "type": "multi_turn"},
    {"id": "multi_2", "input": "Task 2", "type": "multi_turn"},
    {"id": "edge_1", "input": "", "type": "edge_case"},
]


async def run_benchmark():
    """Run baseline benchmark."""
    print("Starting Lobuddy baseline benchmark...")

    # Create a temporary workspace for the benchmark
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    metrics = {
        "timestamp": datetime.now().isoformat(),
        "tasks": [],
        "summary": {
            "total_tasks": len(TEST_TASKS),
            "successful": 0,
            "failed": 0,
            "avg_latency_ms": 0,
            "total_tokens": 0,
        },
    }

    latencies = []
    total_tokens = 0

    # Initialize components
    settings = Settings(llm_api_key="test-key", llm_model="gpt-4o-mini")
    meter = TokenMeter()
    policy = ToolPolicy()
    guardrails = SafetyGuardrails(settings.workspace_path)

    for task_def in TEST_TASKS:
        print(f"  Running task: {task_def['id']} ({task_def['type']})")

        start = time.perf_counter()
        try:
            # Simulate task processing
            await asyncio.sleep(0.01)  # Simulate async work

            # Test token metering
            prompt_tokens = len(task_def["input"]) // 4
            completion_tokens = 50
            meter.increment_turn(task_def["id"])
            meter.record_usage(task_def["id"], "user_input", prompt_tokens=prompt_tokens)
            meter.record_usage(task_def["id"], "output", completion_tokens=completion_tokens)

            # Test tool policy
            if task_def["type"] == "tool_call":
                meter.record_usage(task_def["id"], "tool_result", prompt_tokens=25)
                assert policy.is_tool_allowed("read_file") is True
                assert policy.is_tool_allowed("exec") is False

            # Test guardrails
            if "workspace" in task_def["input"]:
                result = guardrails.validate_path("workspace/test.txt")
                assert result is None  # Within workspace

            # Test dangerous command detection
            if task_def["type"] == "tool_call":
                assert policy.is_command_dangerous("rm -rf /") is True
                assert policy.is_command_dangerous("ls -la") is False

            success = True
            error = None
        except Exception as e:
            success = False
            error = str(e)

        end = time.perf_counter()
        latency_ms = (end - start) * 1000
        latencies.append(latency_ms)

        task_tokens = prompt_tokens + completion_tokens
        total_tokens += task_tokens

        metrics["tasks"].append(
            {
                "task_id": task_def["id"],
                "type": task_def["type"],
                "success": success,
                "latency_ms": round(latency_ms, 2),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": task_tokens,
                "error": error,
            }
        )

        if success:
            metrics["summary"]["successful"] += 1
        else:
            metrics["summary"]["failed"] += 1

    metrics["summary"]["avg_latency_ms"] = (
        round(sum(latencies) / len(latencies), 2) if latencies else 0
    )
    metrics["summary"]["total_prompt_tokens"] = sum(t["prompt_tokens"] for t in metrics["tasks"])
    metrics["summary"]["total_completion_tokens"] = sum(
        t["completion_tokens"] for t in metrics["tasks"]
    )
    metrics["summary"]["total_tokens"] = total_tokens

    # Save metrics
    output_path = reports_dir / "baseline_metrics.json"
    with open(output_path, "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"\nBenchmark complete. Results saved to {output_path}")
    print(f"Success rate: {metrics['summary']['successful']}/{metrics['summary']['total_tasks']}")
    print(f"Avg latency: {metrics['summary']['avg_latency_ms']}ms")
    print(f"Total tokens: {metrics['summary']['total_tokens']}")

    return metrics


if __name__ == "__main__":
    asyncio.run(run_benchmark())
