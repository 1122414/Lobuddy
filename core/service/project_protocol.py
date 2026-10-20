"""Explicit project membership and scoped, source-backed recent context."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from core.service.delegation_protocol import DelegationModel, DelegationView


class ProjectCreate(DelegationModel):
    name: str = Field(min_length=1, max_length=100)
    goal: str = Field(default="", max_length=2000)


class ProjectReference(DelegationModel):
    project_id: str = Field(min_length=1, max_length=128)


class ProjectChange(ProjectReference):
    revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)
    goal: str = Field(default="", max_length=2000)
    status: Literal["active", "paused", "completed"] = "active"


class ProjectView(ProjectCreate):
    id: str
    revision: int = 1
    status: Literal["active", "paused", "completed"] = "active"
    created_at: float
    updated_at: float


class ProjectBind(DelegationModel):
    revision: int = Field(ge=0)
    session_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(default="", max_length=128)


class SourceShare(DelegationModel):
    kind: Literal["text", "file", "url"] = "text"
    category: Literal["material", "recent", "decision", "pending", "shared"] = "material"
    title: str = Field(min_length=1, max_length=100)
    text: str = Field(default="", max_length=12000)
    locator: str = Field(default="", max_length=4096)
    project_id: str = Field(default="", max_length=128)
    session_id: str = Field(default="", max_length=128)
    source_message_id: str = Field(default="", max_length=128)
    expires_at: float | None = Field(default=None, gt=0)
    sensitive_confirmed: bool = False

    @model_validator(mode="after")
    def scoped(self) -> SourceShare:
        if bool(self.project_id) == bool(self.session_id):
            raise ValueError("请选择一个项目，或仅用于一个会话")
        if self.kind == "text" and (not self.text.strip() or self.locator):
            raise ValueError("文本分享需要正文，不能携带文件地址")
        if self.kind != "text" and (not self.locator or self.text):
            raise ValueError("文件或链接需要明确来源，不能代填正文")
        if self.category == "recent" and self.expires_at is None:
            raise ValueError("近况必须指定有效期")
        return self


class SourceReference(DelegationModel):
    source_id: str = Field(min_length=1, max_length=128)


class SourceChange(SourceReference):
    revision: int = Field(ge=1)


class SourceCorrect(SourceChange):
    text: str = Field(min_length=1, max_length=12000)
    sensitive_confirmed: bool = False


class SourceMove(SourceChange):
    project_id: str = Field(default="", max_length=128)
    session_id: str = Field(default="", max_length=128)

    @model_validator(mode="after")
    def target(self) -> SourceMove:
        if bool(self.project_id) == bool(self.session_id):
            raise ValueError("选择唯一项目或会话归属")
        return self


class SourceView(DelegationModel):
    id: str
    revision: int = 1
    kind: Literal["text", "file", "url"]
    category: Literal["material", "recent", "decision", "pending", "shared"]
    title: str
    text: str
    locator: str = ""
    project_id: str = ""
    session_id: str = ""
    source_message_id: str = ""
    sha256: str
    status: Literal["active", "changed", "missing", "expired", "forgotten"] = "active"
    sensitive: bool = False
    expires_at: float | None = None
    created_at: float
    checked_at: float
    reason: str = ""


class ProjectOverview(DelegationModel):
    project: ProjectView
    sources: list[SourceView]
    delegations: list[DelegationView]
