"""Token meter integration for recording nanobot task usage."""

import logging
import math
from collections.abc import Mapping
from typing import Any

from core.models.model_usage import ModelUsageEvidence, ModelUsageSource
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
        result: Any = None,
        tools_used: list[str] | None = None,
        actual_usage: Mapping[str, Any] | None = None,
    ) -> ModelUsageEvidence:
        """Record one content-free measurement without double-counting tool results."""
        evidence = self.measure(
            prompt=prompt,
            raw_output=raw_output,
            result=result,
            actual_usage=actual_usage,
        )
        if not evidence.available:
            return evidence

        self.token_meter.increment_turn(session_key)
        self.token_meter.record_measurement_source(session_key, evidence.source.value)
        self.token_meter.record_usage(
            session_key,
            "model_input",
            prompt_tokens=evidence.prompt_tokens,
        )
        self.token_meter.record_usage(
            session_key,
            "model_output",
            completion_tokens=evidence.completion_tokens,
        )

        logger.debug(
            "Model usage recorded for session=%s: prompt=%d, completion=%d, "
            "cached=%d, source=%s, tools=%d",
            session_key,
            evidence.prompt_tokens,
            evidence.completion_tokens,
            evidence.cached_tokens,
            evidence.source.value,
            len(tools_used or []),
        )
        return evidence

    def measure(
        self,
        *,
        prompt: str,
        raw_output: str,
        result: Any = None,
        actual_usage: Mapping[str, Any] | None = None,
    ) -> ModelUsageEvidence:
        usage = self._usage_mapping(actual_usage, result)
        prompt_tokens = self._usage_value(
            usage,
            "prompt_tokens",
            "input_tokens",
        )
        completion_tokens = self._usage_value(
            usage,
            "completion_tokens",
            "output_tokens",
        )
        cached_tokens = self._usage_value(
            usage,
            "cached_tokens",
            "cache_read_input_tokens",
        )
        if prompt_tokens > 0 or completion_tokens > 0:
            return ModelUsageEvidence(
                provider_model=self.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=min(cached_tokens, prompt_tokens),
                source=ModelUsageSource.PROVIDER,
            )

        estimated_prompt = self._estimate_tokens(prompt)
        estimated_completion = self._estimate_tokens(raw_output)
        if estimated_prompt <= 0 and estimated_completion <= 0:
            return ModelUsageEvidence(provider_model=self.model)
        return ModelUsageEvidence(
            provider_model=self.model,
            prompt_tokens=estimated_prompt,
            completion_tokens=estimated_completion,
            source=ModelUsageSource.LOCAL_ESTIMATE,
        )

    @staticmethod
    def _usage_mapping(
        actual_usage: Mapping[str, Any] | None,
        result: Any,
    ) -> Mapping[str, Any]:
        if actual_usage:
            return actual_usage
        raw = getattr(result, "usage", None)
        if isinstance(raw, Mapping):
            return raw
        if raw is None:
            return {}
        return {
            name: getattr(raw, name, 0)
            for name in (
                "prompt_tokens",
                "completion_tokens",
                "cached_tokens",
            )
        }

    @staticmethod
    def _usage_value(usage: Mapping[str, Any], *names: str) -> int:
        for name in names:
            value = usage.get(name)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                if isinstance(value, float) and not math.isfinite(value):
                    continue
                return max(0, int(value))
        return 0

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        try:
            import tiktoken

            try:
                encoder = tiktoken.encoding_for_model(self.model)
            except KeyError:
                encoder = tiktoken.get_encoding("cl100k_base")
            return len(encoder.encode(text))
        except Exception:
            return max(1, math.ceil(len(text) / 4))
