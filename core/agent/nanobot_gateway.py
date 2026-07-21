"""Gateway layer for nanobot internal API access.

This module provides a stable facade over nanobot's internal APIs,
reducing coupling to implementation details like _loop, _process_message,
and _tasks.
"""

from typing import Any


class NanobotGateway:
    """Stable gateway to nanobot internals."""

    _USAGE_FIELDS = (
        "prompt_tokens",
        "completion_tokens",
        "cached_tokens",
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
    )

    def __init__(self, bot: Any) -> None:
        self._bot = bot

    @property
    def _loop(self) -> Any:
        return self._bot._loop

    def get_or_create_session(self, session_key: str) -> Any:
        """Get or create a session by key."""
        return self._loop.sessions.get_or_create(session_key)

    def save_session(self, session: Any) -> None:
        """Persist session state."""
        self._loop.sessions.save(session)

    def get_tool(self, name: str) -> Any:
        """Get a registered tool by name."""
        return self._loop.tools.get(name)

    def register_tool(self, tool: Any) -> None:
        """Register a custom tool."""
        self._loop.tools.register(tool)

    def unregister_tool(self, name: str) -> None:
        """Unregister a tool by name."""
        self._loop.tools.unregister(name)

    def list_tools(self) -> list[Any]:
        """Return registered tools through the stable gateway Interface."""
        return [
            tool
            for name in self._loop.tools.tool_names
            if (tool := self._loop.tools.get(name)) is not None
        ]

    def get_last_usage(self) -> dict[str, int]:
        """Return content-free provider usage from the last completed Agent Loop."""
        raw = getattr(self._loop, "_last_usage", {}) or {}
        if not isinstance(raw, dict):
            return {}
        usage: dict[str, int] = {}
        for name in self._USAGE_FIELDS:
            value = raw.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            try:
                normalized = int(value)
            except (OverflowError, ValueError):
                continue
            usage[name] = max(0, normalized)
        return usage

    def get_tasks(self) -> list[Any]:
        """Get list of running tasks for cancellation."""
        return list(getattr(self._loop, "_tasks", []))

    async def process_message(self, message: Any, session_key: str) -> Any:
        """Send a message through nanobot's processing pipeline."""
        return await self._loop._process_message(message, session_key=session_key)

    def cancel(self) -> None:
        """Cancel the bot's current operation if supported."""
        if hasattr(self._bot, "cancel") and callable(self._bot.cancel):
            self._bot.cancel()
