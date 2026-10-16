"""Evidence-bearing relationship proposals; model output never grants authority."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RelationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["preference", "shared", "inferred", "temporary"]
    key: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=1000)
    source_ids: list[str] = Field(min_length=1, max_length=10)
    quote: str = Field(default="", max_length=1000)
    scope: Literal["global", "session"] = "global"
    sensitive: bool = False


class SummaryFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["goal", "decision", "correction", "pending", "shared"]
    content: str = Field(min_length=1, max_length=300)
    source_ids: list[str] = Field(min_length=1, max_length=5)


class RelationAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memories: list[RelationProposal] = Field(default_factory=list, max_length=5)
    summary: list[SummaryFact] = Field(default_factory=list, max_length=8)


class RelationReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    relation_id: str = Field(min_length=1, max_length=128)


class RelationResolve(RelationReference):
    approved: bool


class RelationForget(RelationReference):
    delete_history: bool = False


class RelationEdit(RelationReference):
    content: str = Field(min_length=1, max_length=1000)


class RelationView(BaseModel):
    id: str
    key: str
    kind: str
    content: str
    scope: str
    status: Literal["pending", "applying", "active", "rejected", "superseded", "forgotten"]
    reason: str
    session_id: str
    source_ids: list[str]
    revision: int
    updated_at: str


class RelationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = True
