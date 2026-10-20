"""Observable decision evidence contains no copies of private notification text."""

from typing import Literal

from pydantic import Field

from core.agent.jev import JevAnswers, JevModel


class JevDecision(JevModel):
    action: Literal["notify", "defer", "quiet"] = "defer"
    reason: str
    mode: Literal["shadow", "active"]
    status: Literal["running", "decided", "fallback", "interrupted", "stale"]
    model: str = ""
    answers: JevAnswers | None = None
    created_at: float
    not_before: float
    elapsed_ms: float = 0
    input_tokens: int | None = None
    output_tokens: int | None = None


class JevStatus(JevModel):
    mode: Literal["off", "shadow", "active"]
    configured: bool
    model: str
    calls_today: int
    request_bytes_today: int
    daily_calls: int
    daily_request_bytes: int
    running: bool
    recent: list[JevDecision] = Field(default_factory=list)
