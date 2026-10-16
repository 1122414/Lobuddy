"""Synchronous domain notifications; presentation layers own thread dispatch."""

from collections.abc import Callable
from threading import RLock
from typing import Generic, ParamSpec

P = ParamSpec("P")


class EventHook(Generic[P]):
    def __init__(self) -> None:
        self._handlers: list[Callable[P, None]] = []
        self._lock = RLock()

    def connect(self, handler: Callable[P, None]) -> None:
        with self._lock:
            if handler not in self._handlers:
                self._handlers.append(handler)

    def disconnect(self, handler: Callable[P, None]) -> None:
        with self._lock:
            self._handlers.remove(handler)

    def emit(self, *args: P.args, **kwargs: P.kwargs) -> None:
        with self._lock:
            handlers = tuple(self._handlers)
        for handler in handlers:
            handler(*args, **kwargs)
