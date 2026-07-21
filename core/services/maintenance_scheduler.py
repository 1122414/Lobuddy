"""Maintenance scheduler — registerable periodic tasks with configurable intervals.

All maintenance runs on a background thread, never blocking the UI.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class MaintenanceTask:
    name: str
    fn: Callable[[], object]
    interval_seconds: float
    enabled: bool = True
    last_run_at: float = 0.0
    run_count: int = 0
    fail_count: int = 0

    def should_run(self, now: float) -> bool:
        return self.enabled and (now - self.last_run_at) >= self.interval_seconds


class MaintenanceScheduler:
    """Background scheduler for periodic maintenance tasks."""

    def __init__(self, start_delay_seconds: float = 30.0, poll_interval_seconds: float = 10.0):
        self._tasks: dict[str, MaintenanceTask] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._start_delay = start_delay_seconds
        self._poll_interval = poll_interval_seconds
        self._lock = threading.Lock()

    def register(self, task: MaintenanceTask) -> None:
        with self._lock:
            self._tasks[task.name] = task

    def unregister(self, name: str) -> None:
        with self._lock:
            self._tasks.pop(name, None)

    def set_enabled(self, name: str, enabled: bool) -> None:
        with self._lock:
            if name in self._tasks:
                self._tasks[name].enabled = enabled

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="maint-scheduler")
        self._thread.start()
        logger.info("Maintenance scheduler started (delay=%ss)", self._start_delay)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._thread and not self._thread.is_alive():
            self._thread = None
        logger.info("Maintenance scheduler stopped")

    def get_status(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "name": t.name,
                    "enabled": t.enabled,
                    "interval_seconds": t.interval_seconds,
                    "last_run_at": t.last_run_at,
                    "run_count": t.run_count,
                    "fail_count": t.fail_count,
                }
                for t in self._tasks.values()
            ]

    def _run(self) -> None:
        if self._stop_event.wait(self._start_delay):
            return
        while not self._stop_event.is_set():
            now = time.time()
            with self._lock:
                tasks_to_run = [t for t in self._tasks.values() if t.should_run(now)]
            for task in tasks_to_run:
                attempted_at = time.time()
                try:
                    result = task.fn()
                    with self._lock:
                        task.last_run_at = attempted_at
                        task.run_count += 1
                    logger.info("Maintenance [%s]: %s", task.name, result)
                except Exception as e:
                    with self._lock:
                        task.last_run_at = attempted_at
                        task.fail_count += 1
                    logger.error("Maintenance [%s] failed: %s", task.name, e)
            self._stop_event.wait(self._poll_interval)
