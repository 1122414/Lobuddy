"""Token meter integration for recording nanobot task usage."""

import logging
from typing import Any

from core.runtime.token_meter import TokenMeter

logger = logging.getLogger("lobuddy.token_meter")


class TokenMeterIntegration:
    """Records token usage from nanobot results with fallback estimation."""

    def __init__(self, token_meter: TokenMeter, model: str):
        self.token_meter = token_meter
        self.model = model

    def record_task_usage(
        self,
        session_key: str,
        prompt: str,
        raw_output: str,
        result: Any,
        tools_used: list[str],
    ) -> None:
        """Record token usage for a completed task.

        Prefers actual usage from nanobot result, falls back to tiktoken,
        then heuristic estimation.
        """
        prompt_tokens = None
        completion_tokens = None

        # Try to extract real usage from nanobot result
        if hasattr(result, "usage") and result.usage:
            usage = result.usage
            if hasattr(usage, "prompt_tokens") and isinstance(usage.prompt_tokens, int):
                prompt_tokens = usage.prompt_tokens
            if hasattr(usage, "completion_tokens") and isinstance(usage.completion_tokens, int):
                completion_tokens = usage.completion_tokens

        # Fallback to tiktoken estimation
        if prompt_tokens is None or completion_tokens is None:
            try:
                import tiktoken

                encoder = tiktoken.encoding_for_model(self.model)
                if prompt_tokens is None:
                    prompt_tokens = len(encoder.encode(prompt))
                if completion_tokens is None:
                    completion_tokens = len(encoder.encode(raw_output))
            except Exception:
                logger.warning(
                    f"tiktoken unavailable for model={self.model}, "
                    "recording zero tokens"
                )
                if prompt_tokens is None:
                    prompt_tokens = 0
                if completion_tokens is None:
                    completion_tokens = 0

        self.token_meter.increment_turn(session_key)

        # Estimate system + history + user_input breakdown
        system_tokens = min(300, prompt_tokens // 3)
        history_tokens = max(0, prompt_tokens - system_tokens - len(prompt) // 4)
        user_input_tokens = prompt_tokens - system_tokens - history_tokens

        self.token_meter.record_usage(session_key, "system", prompt_tokens=system_tokens)
        self.token_meter.record_usage(session_key, "history", prompt_tokens=history_tokens)
        self.token_meter.record_usage(
            session_key, "user_input", prompt_tokens=user_input_tokens
        )
        self.token_meter.record_usage(
            session_key, "output", completion_tokens=completion_tokens
        )
        # Placeholder for skill/memory (Phase 3 will populate)
        self.token_meter.record_usage(session_key, "skill", prompt_tokens=0)
        self.token_meter.record_usage(session_key, "memory", prompt_tokens=0)

        # Record tool result tokens (0 if no tools used)
        tool_result_tokens = 50 * len(tools_used)
        self.token_meter.record_usage(
            session_key, "tool_result", prompt_tokens=tool_result_tokens
        )

        logger.debug(
            f"Token usage recorded for session={session_key}: "
            f"prompt={prompt_tokens}, completion={completion_tokens}, "
            f"tools={len(tools_used)}"
        )
