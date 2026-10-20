"""Versioned desktop protocol. Pydantic is the source for generated TypeScript."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from core.service.companion import CompanionPreferences
from core.service.companionship import (
    CompanionActivity,
    CompanionFeedback,
    CompanionPolicy,
    CompanionPreference,
    CompanionTrigger,
)
from core.service.delegation_protocol import (
    DelegationChange,
    DelegationConfirm,
    DelegationEdit,
    DelegationReference,
    DelegationSpec,
)
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
from core.service.learning_protocol import LearningPolicy
from core.service.project_protocol import (
    ProjectBind,
    ProjectChange,
    ProjectCreate,
    ProjectReference,
    SourceChange,
    SourceCorrect,
    SourceMove,
    SourceShare,
)
from core.service.relationship_protocol import (
    RelationEdit,
    RelationForget,
    RelationPolicy,
    RelationReference,
    RelationResolve,
)
from core.service.schedule_protocol import (
    NotificationBatchReference,
    NotificationReference,
    RecoveryRequest,
    RuntimePower,
)
from core.service.settings_service import SettingsPatch
from core.service.themes import ThemeReference, ThemeSave
from core.service.topics import TopicReference
from core.service.workflow_protocol import WorkflowProposal, WorkflowReference
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
    workflow_id: str = Field(default="", max_length=64)
    workflow_input: dict[str, JsonValue] = Field(default_factory=dict)
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
    delegation_id: str = ""
    run_id: str = ""
    project_id: str = ""
    workflow_version: str = ""
    workflow_input: dict[str, JsonValue] = Field(default_factory=dict)
    output_text: str = ""
    error: str = ""


class ServiceEvent(Parameters):
    delegation_id: str = ""
    run_id: str = ""
    project_id: str = ""
    session_id: str
    task_id: str
    turn_id: str
    sequence: int = Field(ge=1)
    kind: str
    data: dict[str, JsonValue]


METHODS: dict[str, type[BaseModel]] = {
    "project.list": Empty,
    "project.create": ProjectCreate,
    "project.get": ProjectReference,
    "project.edit": ProjectChange,
    "project.bind": ProjectBind,
    "project.selection": SessionReference,
    "source.share": SourceShare,
    "source.import_file": SourceShare,
    "source.list": Empty,
    "source.correct": SourceCorrect,
    "source.move": SourceMove,
    "source.forget": SourceChange,
    "schedule.get": DelegationReference,
    "runtime.power": RuntimePower,
    "notification.list": Empty,
    "jev.status": Empty,
    "notification.next": Empty,
    "notification.displayed": NotificationBatchReference,
    "notification.read": NotificationReference,
    "delegation.recover": RecoveryRequest,
    "delegation.create": DelegationSpec,
    "delegation.list": Empty,
    "delegation.get": DelegationReference,
    "delegation.confirm": DelegationConfirm,
    "delegation.edit": DelegationEdit,
    "delegation.pause": DelegationChange,
    "delegation.resume": DelegationChange,
    "delegation.cancel": DelegationChange,
    "delegation.run": DelegationChange,
    "workflow.list": Empty,
    "workflow.propose": WorkflowProposal,
    "workflow.evaluate": WorkflowReference,
    "workflow.disable": WorkflowReference,
    "workflow.enable": WorkflowReference,
    "workflow.rollback": WorkflowReference,
    "relationship.list": Empty,
    "relationship.sources": RelationReference,
    "relationship.resolve": RelationResolve,
    "relationship.forget": RelationForget,
    "relationship.edit": RelationEdit,
    "relationship.policy": Empty,
    "relationship.configure": RelationPolicy,
    "learning.get": Empty,
    "learning.configure": LearningPolicy,
    "companionship.overview": Empty,
    "companionship.topics": Empty,
    "companionship.topic.unblock": TopicReference,
    "companionship.get": Empty,
    "companionship.configure": CompanionPolicy,
    "companionship.activity": CompanionActivity,
    "companionship.trigger": CompanionTrigger,
    "companionship.poll": Empty,
    "companionship.feedback": CompanionFeedback,
    "preference.save": CompanionPreference,
    "theme.list": Empty,
    "theme.save": ThemeSave,
    "theme.apply": ThemeReference,
    "theme.delete": ThemeReference,
    "theme.from_image": ImageReference,
    "companion.get": Empty,
    "companion.save": CompanionPreferences,
    "companion.import": ImageImport,
    "image.import": ImageImport,
    "image.get": ImageReference,
    "memory.list": MemoryQuery,
    "memory.save": MemorySave,
    "memory.delete": MemoryReference,
    "history.search": HistorySearch,
    "history.summaries": SessionReference,
    "skill.list": Empty,
    "skill.get": SkillReference,
    "skill.versions": SkillReference,
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
    "task.outcome": TurnReference,
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

# Reads and idempotent presence updates do not consume the durable request budget.
TRANSIENT_METHODS = frozenset(
    {
        "project.list",
        "project.get",
        "project.selection",
        "source.list",
        "source.share",
        "source.import_file",
        "source.correct",
        "source.move",
        "source.forget",
        "schedule.get",
        "notification.list",
        "jev.status",
        "notification.next",
        "notification.displayed",
        "delegation.list",
        "delegation.get",
        "workflow.list",
        "learning.get",
        "relationship.list",
        "relationship.sources",
        "relationship.policy",
        "companionship.get",
        "companionship.overview",
        "companionship.topics",
        "companionship.poll",
        "companionship.activity",
        "companionship.trigger",
        "companion.get",
        "theme.list",
        "theme.from_image",
        "image.get",
        "service.health",
        "session.list",
        "session.history",
        "task.list",
        "task.get",
        "task.outcome",
        "approval.list",
        "pet.get",
        "progress.get",
        "settings.get",
        "focus.get",
        "memory.list",
        "history.search",
        "history.summaries",
        "skill.list",
        "skill.get",
        "skill.versions",
        "skill.candidates",
    }
)
