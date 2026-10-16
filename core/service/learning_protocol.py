"""Validated configuration and observable background-learning state."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class LearningPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = True
    idle_seconds: int = Field(default=60, ge=1, le=3600)
    daily_calls: int = Field(default=30, ge=0, le=500)
    daily_input_tokens: int = Field(default=60000, ge=0, le=1000000)
    daily_output_tokens: int = Field(default=8000, ge=0, le=100000)


class LearningJobView(BaseModel):
    id: str
    kind: str
    status: Literal["pending", "running", "completed", "failed", "interrupted"]
    attempts: int
    updated_at: float
    error: str
    result: dict[str, JsonValue]


class LearningBudget(BaseModel):
    day: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class LearningConsumer(BaseModel):
    setting: str
    enabled: bool
    consumer: str
    behavior: str


LearningState = Literal["disabled", "idle", "waiting", "running", "budget_exhausted", "closed"]


class LearningView(BaseModel):
    policy: LearningPolicy
    state: LearningState
    usage: LearningBudget
    jobs: list[LearningJobView]
    consumers: list[LearningConsumer]
