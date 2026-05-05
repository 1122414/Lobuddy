import asyncio
import threading
from collections import defaultdict
from typing import Any, Callable

from core.logging.trace import get_logger

event_log = get_logger("event")


class EventBus:
    def __init__(self) -> None:
        self._subscriptions: dict[type, list[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: type, handler: Callable) -> None:
        with self._lock:
            self._subscriptions[event_type].append(handler)

    def publish(self, event: Any) -> None:
        with self._lock:
            handlers = list(self._subscriptions.get(type(event), []))
        event_log.debug("Event published — %s (handlers=%d)", type(event).__name__, len(handlers))
        for handler in handlers:
            if asyncio.iscoroutinefunction(handler):
                asyncio.create_task(handler(event))
            else:
                handler(event)

    async def publish_and_wait(self, event: Any) -> None:
        with self._lock:
            handlers = list(self._subscriptions.get(type(event), []))
        tasks = []
        for handler in handlers:
            if asyncio.iscoroutinefunction(handler):
                tasks.append(asyncio.create_task(handler(event)))
            else:
                handler(event)
        if tasks:
            await asyncio.gather(*tasks)
