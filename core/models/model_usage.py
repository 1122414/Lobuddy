"""Provider-backed or explicitly estimated model usage evidence."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ModelUsageSource(str, Enum):
    """Evidence quality for one model usage measurement."""

    PROVIDER = "provider"
    LOCAL_ESTIMATE = "local_estimate"
    UNAVAILABLE = "unavailable"


class ModelUsageEvidence(BaseModel):
    """Content-free model resource evidence for one Task Run."""

    provider_model: str = Field(default="", max_length=160)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    source: ModelUsageSource = ModelUsageSource.UNAVAILABLE

    @model_validator(mode="after")
    def validate_evidence(self) -> "ModelUsageEvidence":
        if self.cached_tokens > self.prompt_tokens:
            raise ValueError("cached_tokens must be a subset of prompt_tokens")
        if self.source == ModelUsageSource.UNAVAILABLE and self.total_tokens:
            raise ValueError("unavailable usage cannot contain measured tokens")
        if self.source != ModelUsageSource.UNAVAILABLE and not self.total_tokens:
            raise ValueError("available usage must contain at least one token")
        return self

    @property
    def total_tokens(self) -> int:
        """Cached tokens are already included in provider prompt totals."""
        return self.prompt_tokens + self.completion_tokens

    @property
    def available(self) -> bool:
        return self.total_tokens > 0 and self.source != ModelUsageSource.UNAVAILABLE
