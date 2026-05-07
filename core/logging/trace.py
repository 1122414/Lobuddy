"""Trace logging system with daily folder organization and full-chain traceability.

Key features:
- Daily folder: logs/YYYY-MM-DD/
- Multi-category log files for targeted tracing
- trace_id via ContextVar for request correlation across all log entries
- Auto-injected function:line via loguru's built-in {function}:{line}
"""

import logging
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Optional

from loguru import logger as _loguru_logger

_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)

CATEGORIES: dict[str, str] = {
    "system": "system.log",
    "agent": "agent.log",
    "tool": "tool.log",
    "task": "task.log",
    "subagent": "subagent.log",
    "security": "security.log",
}

FILE_FORMAT = (
    "{time:HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line}"
    " | [{extra[trace_id]}] | {message}"
)

CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<yellow>[{extra[trace_id]}]</yellow> | <level>{message}</level>"
)


def setup_trace_logging(logs_dir: Path, log_level: str = "INFO") -> None:
    """Configure the trace logging system.

    Sets up:
    - Daily folder structure: logs/YYYY-MM-DD/
    - Category-specific log files (system, agent, tool, task, subagent, security)
    - All-in-one log for backward compatibility
    - Error-only log for quick troubleshooting
    - Console output with color
    - stdlib logging → loguru bridge with SensitiveDataFilter
    """
    from core.logging.log_filter import SensitiveDataFilter

    _loguru_logger.remove()

    _loguru_logger.add(
        sys.stdout,
        level=log_level,
        format=CONSOLE_FORMAT,
    )

    daily_folder = logs_dir / "{time:YYYY-MM-DD}"
    daily_folder_str = str(daily_folder)

    for category, filename in CATEGORIES.items():
        log_path = f"{daily_folder_str}/{filename}"
        _loguru_logger.add(
            log_path,
            level="DEBUG",
            format=FILE_FORMAT,
            rotation="00:00",
            retention="30 days",
            filter=lambda record, cat=category: record["extra"].get("category") == cat,
        )

    _loguru_logger.add(
        f"{daily_folder_str}/all.log",
        level="DEBUG",
        format=FILE_FORMAT,
        rotation="00:00",
        retention="7 days",
    )

    _loguru_logger.add(
        f"{daily_folder_str}/error.log",
        level="ERROR",
        format=FILE_FORMAT,
        rotation="00:00",
        retention="30 days",
    )

    class InterceptHandler(logging.Handler):
        """Routes standard library logging to loguru with sensitive data filter."""

        def __init__(self):
            super().__init__()
            self.addFilter(SensitiveDataFilter())

        def emit(self, record: logging.LogRecord) -> None:
            try:
                level = _loguru_logger.level(record.levelname).name
            except ValueError:
                level = str(record.levelno)

            frame: Any = logging.currentframe()
            depth = 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            _loguru_logger.opt(depth=depth, exception=record.exc_info).patch(
                lambda r: r["extra"].setdefault("trace_id", _trace_id.get() or "-")
            ).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=logging.DEBUG, force=True)


def set_trace_id(trace_id: str) -> None:
    """Set the current trace_id for request correlation across log entries.

    Usage:
        set_trace_id(task_id)
        # ... all subsequent log calls will include this trace_id
    """
    _trace_id.set(trace_id)


def get_trace_id() -> Optional[str]:
    """Get the current trace_id."""
    return _trace_id.get()


def clear_trace_id() -> None:
    """Clear the current trace_id."""
    _trace_id.set(None)


def get_logger(category: str):
    """Get a logger that auto-injects trace_id and category at call time.

    The returned logger automatically includes:
    - category: which log file this entry goes to
    - trace_id: current trace_id from ContextVar (or "-" if not set)

    Usage:
        from core.logging.trace import set_trace_id, get_logger

        agent_log = get_logger("agent")
        tool_log = get_logger("tool")

        set_trace_id("task-abc-123")
        agent_log.info("Starting AI call")
        tool_log.info("Executing tool: search")

    The log entry will appear in:
    - logs/YYYY-MM-DD/agent.log  (category="agent")
    - logs/YYYY-MM-DD/tool.log   (category="tool")
    - logs/YYYY-MM-DD/all.log    (always)
    - stdout                      (always, at configured level)
    """
    return _loguru_logger.patch(
        lambda record: record["extra"].update(
            category=category,
            trace_id=_trace_id.get() or "-",
        )
    )
