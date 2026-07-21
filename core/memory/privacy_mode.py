"""Privacy mode manager for ephemeral sessions."""

import logging
from typing import Callable, Optional

from core.config import Settings

logger = logging.getLogger(__name__)

Listener = Callable[[str, bool], None]


class PrivacyModeManager:
    """Manages per-session privacy mode state.

    When privacy mode is active for a session:
    - No long-term business memories are written to memory table
    - Exit analysis is skipped
    - Historical memories are not injected into prompts
    - Chat history is saved according to privacy_mode_allow_chat_history setting
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sessions: dict[str, bool] = {}
        self._listeners: list[Listener] = []

    def add_listener(self, listener: Listener) -> None:
        """Register a callback invoked when privacy state changes.

        Signature: listener(session_id: str, is_active: bool) -> None
        """
        self._listeners.append(listener)

    def update_settings(self, settings: Settings) -> None:
        """Apply new defaults while preserving explicit state for existing sessions."""
        self._settings = settings

    def remove_listener(self, listener: Listener) -> None:
        """Remove a previously registered listener."""
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    def _notify(self, session_id: str, is_active: bool) -> None:
        for listener in self._listeners:
            try:
                listener(session_id, is_active)
            except Exception:
                pass

    def is_privacy_active(self, session_id: Optional[str]) -> bool:
        """Check if privacy mode is active for a given session.

        Returns False if session_id is empty/None.
        New sessions inherit the default from settings.privacy_mode_enabled.
        """
        if not session_id:
            return False
        if session_id not in self._sessions:
            self._sessions[session_id] = self._settings.privacy_mode_enabled
        return self._sessions[session_id]

    def enable_privacy(self, session_id: str) -> None:
        """Enable privacy mode for a session."""
        if not session_id:
            return
        self._sessions[session_id] = True
        self._notify(session_id, True)
        logger.info("Privacy mode enabled for session %s", session_id)

    def disable_privacy(self, session_id: str) -> None:
        """Disable privacy mode for a session."""
        if not session_id:
            return
        self._sessions[session_id] = False
        self._notify(session_id, False)
        logger.info("Privacy mode disabled for session %s", session_id)
