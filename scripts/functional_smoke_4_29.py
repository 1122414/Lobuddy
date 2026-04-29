"""Functional smoke checks for the Lobuddy 4.29.0 stabilization work.

This script avoids real model calls. It verifies the config override helpers,
task card action model, and friendly AI error summaries that are easy to
regress during UI/settings changes.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _fail(message: str) -> int:
    print(f"[FAIL] {message}")
    return 1


def _ok(message: str) -> None:
    print(f"[OK] {message}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    try:
        from app.config import _ENV_VAR_MAP, _coerce_setting_value
        from core.agent.nanobot_adapter import NanobotAdapter
        from core.models.task_card import TaskCardModel
    except Exception as exc:
        return _fail(
            "Project imports failed. Check Python 3.11+, pydantic>=2, "
            f"pydantic-settings, PySide6, loguru, and Pillow. Details: {exc}"
        )

    required_env_fields = {
        "llm_api_key",
        "llm_base_url",
        "llm_model",
        "llm_multimodal_model",
        "llm_multimodal_base_url",
        "llm_multimodal_api_key",
        "nanobot_max_iterations",
        "task_timeout",
        "shell_enabled",
        "pet_name",
        "theme_preset",
        "pet_clock_enabled",
        "pet_exp_bar_enabled",
        "conversation_timeline_min_dot_gap_px",
        "history_max_turns",
    }
    missing = required_env_fields - set(_ENV_VAR_MAP)
    if missing:
        return _fail(f"Missing env mappings: {sorted(missing)}")
    _ok("Config env mapping covers key runtime settings")

    bool_cases = {
        "true": True,
        "1": True,
        "yes": True,
        "on": True,
        "false": False,
        "0": False,
        "no": False,
        "off": False,
    }
    for raw, expected in bool_cases.items():
        actual = _coerce_setting_value(raw, False)
        if actual is not expected:
            return _fail(f"Bool coercion failed for {raw!r}: {actual!r}")
    _ok("SQLite bool override aliases are accepted")

    card = TaskCardModel(title="任务", status="running")
    if card.available_actions:
        return _fail("TaskCardModel should not expose future actions by default")
    _ok("Task card hides future actions unless explicitly enabled")

    friendly = NanobotAdapter._friendly_api_error_summary("Incorrect API key provided")
    if "API Key" not in friendly or "高级设置" not in friendly:
        return _fail(f"Invalid-key friendly message is not actionable: {friendly}")
    timeout = NanobotAdapter._friendly_api_error_summary("Request timed out")
    if "超时" not in timeout:
        return _fail(f"Timeout friendly message is not clear: {timeout}")
    _ok("AI provider errors are translated to friendly summaries")

    print("[DONE] Lobuddy 4.29.0 smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
