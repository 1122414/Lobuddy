"""Versioned desktop protocol. Pydantic is the source for generated TypeScript."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from core.service.images import ImageImport, ImageReference
from core.service.knowledge_protocol import (
    CandidateResolve,
    HistorySearch,
    KnowledgeParameters,
    MemoryQuery,
    MemoryReference,
    MemorySave,
    SkillReference,
    SkillSave,
    SkillToggle,
)
from core.service.settings_service import SettingsPatch
from core.services.credential_prompt import CredentialConfigure


class Parameters(KnowledgeParameters):
    model_config = ConfigDict(extra="forbid", strict=True)


class Empty(Parameters):
    pass


class SessionCreate(Parameters):
    title: str = Field(default="新对话", min_length=1, max_length=100)


class SessionReference(Parameters):
    session_id: str = Field(min_length=1, max_length=128)


class TurnSend(SessionReference):
    image_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    text: str = Field(min_length=1, max_length=4000)
    lane: Literal["foreground", "background"] = "foreground"


class TurnReference(Parameters):
    turn_id: str = Field(min_length=1, max_length=128)


class ApprovalResolve(Parameters):
    approval_id: str = Field(min_length=1, max_length=128)
    approved: bool


class FocusStart(Parameters):
    minutes: int = Field(default=25, ge=1, le=240)


class RpcRequest(Parameters):
    jsonrpc: Literal["2.0"]
    id: str = Field(min_length=1, max_length=128)
    method: str
    params: dict[str, JsonValue]


class TurnState(Parameters):
    turn_id: str
    task_id: str
    session_id: str
    engine_id: str
    lane: Literal["foreground", "background"]
    status: Literal["queued", "running", "completed", "cancelled", "failed", "interrupted"]
    input_text: str
    image_id: str | None = None
    output_text: str = ""
    error: str = ""


class ServiceEvent(Parameters):
    session_id: str
    task_id: str
    turn_id: str
    sequence: int = Field(ge=1)
    kind: str
    data: dict[str, JsonValue]


METHODS: dict[str, type[BaseModel]] = {
    "image.import": ImageImport,
    "image.get": ImageReference,
    "memory.list": MemoryQuery,
    "memory.save": MemorySave,
    "memory.delete": MemoryReference,
    "history.search": HistorySearch,
    "history.summaries": SessionReference,
    "skill.list": Empty,
    "skill.get": SkillReference,
    "skill.save": SkillSave,
    "skill.toggle": SkillToggle,
    "skill.archive": SkillReference,
    "skill.candidates": Empty,
    "skill.candidate.resolve": CandidateResolve,
    "service.health": Empty,
    "session.create": SessionCreate,
    "session.list": Empty,
    "session.history": SessionReference,
    "turn.send": TurnSend,
    "turn.cancel": TurnReference,
    "task.list": Empty,
    "task.get": TurnReference,
    "approval.list": Empty,
    "approval.resolve": ApprovalResolve,
    "pet.get": Empty,
    "progress.get": Empty,
    "credential.configure": CredentialConfigure,
    "settings.get": Empty,
    "settings.patch": SettingsPatch,
    "focus.get": Empty,
    "focus.start": FocusStart,
    "focus.pause": Empty,
    "focus.resume": Empty,
    "focus.stop": Empty,
}
