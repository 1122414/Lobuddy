"""Token metering for Lobuddy."""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("lobuddy.token_meter")


@dataclass
class TokenUsage:
    """Token usage for a single module."""

    prompt: int = 0
    completion: int = 0

    @property
    def total(self) -> int:
        return self.prompt + self.completion


@dataclass
class SessionMetrics:
    """Token metrics for a session."""

    session_id: str
    turn_count: int = 0
    modules: dict[str, TokenUsage] = field(default_factory=dict)
    total_prompt: int = 0
    total_completion: int = 0
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def total_tokens(self) -> int:
        return self.total_prompt + self.total_completion


class TokenMeter:
    """Records and tracks token consumption."""

    TRUNCATE_THRESHOLD = 2000
    ROLLING_SUMMARY_THRESHOLD = 10

    def __init__(self):
        self.sessions: dict[str, SessionMetrics] = {}
        self._lock = threading.Lock()

    def record_usage(
        self,
        session_id: str,
        module: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> int:
        """Record token usage for a module."""
        with self._lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = SessionMetrics(session_id=session_id)

            metrics = self.sessions[session_id]

            if module not in metrics.modules:
                metrics.modules[module] = TokenUsage()

            usage = metrics.modules[module]
            usage.prompt += prompt_tokens
            usage.completion += completion_tokens
            metrics.total_prompt += prompt_tokens
            metrics.total_completion += completion_tokens

        logger.debug(
            f"Recorded {prompt_tokens}+{completion_tokens} tokens "
            f"for {module} in session {session_id}"
        )
        return prompt_tokens + completion_tokens

    def should_truncate(self, text: str, encoder) -> bool:
        """Check if text exceeds truncation threshold."""
        tokens = len(encoder.encode(text))
        return tokens > self.TRUNCATE_THRESHOLD

    def truncate_text(self, text: str, encoder, max_tokens: int = TRUNCATE_THRESHOLD) -> str:
        """Truncate text to maximum tokens."""
        tokens = encoder.encode(text)
        if len(tokens) <= max_tokens:
            return text
        truncated = encoder.decode(tokens[:max_tokens])
        return truncated + f"\n\n[Content truncated from {len(tokens)} to {max_tokens} tokens]"

    def should_trigger_rolling_summary(self, session_id: str) -> bool:
        """Check if session has exceeded turn threshold."""
        with self._lock:
            if session_id not in self.sessions:
                return False
            return self.sessions[session_id].turn_count > self.ROLLING_SUMMARY_THRESHOLD

    def increment_turn(self, session_id: str):
        """Increment turn count for session."""
        with self._lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = SessionMetrics(session_id=session_id)
            self.sessions[session_id].turn_count += 1

    def get_session_metrics(self, session_id: str) -> Optional[SessionMetrics]:
        """Get metrics for a session."""
        with self._lock:
            return self.sessions.get(session_id)

    def get_last_call_stats(self, session_id: str) -> Optional[dict[str, Any]]:
        """Get stats for the last call in a session."""
        with self._lock:
            metrics = self.sessions.get(session_id)
        if not metrics:
            return None
        return {
            "session_id": metrics.session_id,
            "turn_count": metrics.turn_count,
            "total_prompt": metrics.total_prompt,
            "total_completion": metrics.total_completion,
            "total_tokens": metrics.total_tokens,
            "modules": {
                mod: {
                    "prompt": u.prompt,
                    "completion": u.completion,
                    "total": u.total,
                }
                for mod, u in metrics.modules.items()
            },
        }

    def reset_session(self, session_id: str):
        """Reset metrics for a session."""
        with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]

    def export_metrics(self) -> dict[str, Any]:
        """Export all metrics as dictionary."""
        with self._lock:
            sessions_snapshot = list(self.sessions.items())
        return {
            sid: {
                "session_id": m.session_id,
                "turn_count": m.turn_count,
                "total_prompt": m.total_prompt,
                "total_completion": m.total_completion,
                "total_tokens": m.total_tokens,
                "modules": {
                    mod: {
                        "prompt": u.prompt,
                        "completion": u.completion,
                        "total": u.total,
                    }
                    for mod, u in m.modules.items()
                },
            }
            for sid, m in sessions_snapshot
        }
