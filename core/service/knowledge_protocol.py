"""Validated knowledge-management inputs shared with the desktop."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.skills.skill_schema import SkillRecord


class KnowledgeParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MemoryQuery(KnowledgeParameters):
    query: str = Field(default="", max_length=200)


class MemoryReference(KnowledgeParameters):
    memory_id: str = Field(min_length=1, max_length=128)


class MemorySave(KnowledgeParameters):
    memory_id: str | None = Field(default=None, max_length=128)
    memory_type: Literal[
        "user_profile",
        "system_profile",
        "project_memory",
        "conversation_summary",
        "episodic_memory",
        "procedural_memory",
    ]
    title: str = Field(max_length=100)
    content: str = Field(min_length=1, max_length=2000)


class SkillReference(KnowledgeParameters):
    skill_id: str = Field(min_length=1, max_length=128)


class SkillToggle(SkillReference):
    enabled: bool


class SkillSave(KnowledgeParameters):
    skill_id: str | None = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    description: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=64000)


class SkillDetail(BaseModel):
    record: SkillRecord
    content: str | None
    content_error: str = ""


class HistorySearch(KnowledgeParameters):
    session_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=200)
    scope: Literal["current_session", "all_sessions"] = "current_session"


class CandidateResolve(KnowledgeParameters):
    candidate_id: str = Field(min_length=1, max_length=128)
    approved: bool
