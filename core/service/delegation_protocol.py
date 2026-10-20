"""Explicit, versioned delegations; execution authority is never inferred from chat."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.service.outcomes import Outcome
from core.service.schedule_rules import RepeatRule


class DelegationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class DelegationWait(DelegationModel):
    kind: Literal["none", "time", "user", "event"] = "none"
    at: float | None = Field(default=None, ge=0)
    timezone: str = "Asia/Shanghai"
    event: Literal["", "app_returned", "focus_finished", "delegation_completed"] = ""
    subject_id: str = Field(default="", max_length=128)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("时区无效") from error
        return value

    @model_validator(mode="after")
    def consistent(self) -> DelegationWait:
        if (self.kind == "time") != (self.at is not None):
            raise ValueError("时间等待必须有明确时间，其他等待不能带时间")
        if (self.kind == "event") != bool(self.event):
            raise ValueError("事件等待必须指定事件")
        if (self.event == "delegation_completed") != bool(self.subject_id):
            raise ValueError("委托完成事件必须指定委托")
        return self


class DelegationSpec(DelegationModel):
    goal: str = Field(min_length=1, max_length=2000)
    kind: Literal["reminder", "source-digest", "organize-files"] = "reminder"
    session_id: str = Field(default="", max_length=128)
    source_message_id: str = Field(default="", max_length=128)
    project_id: str = Field(default="", max_length=128)
    sources: list[str] = Field(default_factory=list, max_length=6)
    source_directory: str = Field(default="", max_length=2000)
    output_directory: str = Field(default="", max_length=2000)
    criteria: list[str] = Field(min_length=1, max_length=10)
    wait: DelegationWait = Field(default_factory=DelegationWait)
    repeat: RepeatRule = Field(default_factory=RepeatRule)
    max_tool_calls: int = Field(default=12, ge=1, le=50)
    timeout_seconds: int = Field(default=120, ge=1, le=600)

    @field_validator("goal")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("目标不能为空")
        return value.strip()

    @field_validator("sources", "criteria")
    @classmethod
    def bounded_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 2000 for value in values):
            raise ValueError("来源和验收条件不能空白或过长")
        return values

    @model_validator(mode="after")
    def scoped_inputs(self) -> DelegationSpec:
        if self.repeat.frequency != "once" and self.wait.kind != "time":
            raise ValueError("周期规则只适用于时间等待")
        if self.repeat.end_at is not None and (
            self.wait.at is None or self.repeat.end_at < self.wait.at
        ):
            raise ValueError("结束时间不得早于首次提醒")
        if self.repeat.frequency != "once" and self.wait.at is not None:
            first = datetime.fromtimestamp(self.wait.at, ZoneInfo(self.wait.timezone))
            if (
                first.strftime("%H:%M") != self.repeat.local_time
                or first.second != 0
                or first.fold != 0
            ):
                raise ValueError("首次提醒须与重复规则的当地时刻一致（重复时刻取第一次）")
            if self.repeat.frequency == "weekly" and first.weekday() not in self.repeat.weekdays:
                raise ValueError("首次提醒须在所选星期内")
        criteria = {
            "source-digest": ["资料来源覆盖且引用可追溯"],
            "organize-files": ["副本数量和内容校验通过，原文件保留"],
            "reminder": ["通知按规则投递（不代表已读）"],
        }
        if self.criteria != criteria[self.kind]:
            raise ValueError("当前委托仅支持该场景列出的可验证验收条件")
        if self.kind == "source-digest" and not self.sources:
            raise ValueError("资料归纳需要明确来源")
        if self.kind != "source-digest" and self.sources:
            raise ValueError("只有资料归纳可指定资料列表")
        if self.kind == "organize-files":
            if not self.source_directory.strip() or not self.output_directory.strip():
                raise ValueError("文件整理需要明确输入和输出目录")
        elif self.source_directory or self.output_directory:
            raise ValueError("当前委托类型不能包含整理目录")
        if self.kind == "reminder" and self.wait.kind == "none":
            raise ValueError("提醒需要明确的等待条件")
        return self


class DelegationReference(DelegationModel):
    delegation_id: str = Field(min_length=1, max_length=128)


class DelegationChange(DelegationReference):
    revision: int = Field(ge=1)


class DelegationConfirm(DelegationChange):
    expires_at: float = Field(gt=0)


class DelegationEdit(DelegationChange):
    spec: DelegationSpec


DelegationStatus = Literal[
    "draft",
    "scheduled",
    "ready",
    "running",
    "waiting_user",
    "waiting_event",
    "paused",
    "completed",
    "cancelled",
    "failed",
    "needs_review",
]


class DelegationView(DelegationModel):
    id: str
    revision: int
    spec: DelegationSpec
    status: DelegationStatus = "draft"
    created_at: float
    updated_at: float
    authorized_at: float | None = None
    expires_at: float | None = None
    active_run_id: str = ""
    reason: str = "等待你确认目标、范围与验收条件"


class DelegationRun(DelegationModel):
    id: str
    delegation_id: str
    revision: int
    trigger_id: str
    workflow_version: str
    turn_id: str = ""
    status: Literal["reserved", "running", "completed", "cancelled", "failed", "interrupted"] = (
        "reserved"
    )
    verdict: Literal["verified", "failed", "unknown"] = "unknown"
    created_at: float
    finished_at: float | None = None
    reason: str = "尚未执行"


class DelegationDetail(DelegationModel):
    delegation: DelegationView
    runs: list[DelegationRun]
    revisions: list[DelegationView]
    outcomes: list[Outcome] = Field(default_factory=list)
