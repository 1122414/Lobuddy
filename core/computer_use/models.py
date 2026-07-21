"""Domain models for recoverable computer-use plans and checkpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ComputerActionType(StrEnum):
    MOVE = "move"
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    SCROLL = "scroll"
    TYPE_TEXT = "type_text"
    PRESS_KEY = "press_key"
    HOTKEY = "hotkey"


class ComputerPlanStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class ComputerCheckpointStatus(StrEnum):
    ACTION_COMPLETED = "action_completed"
    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"
    ACTION_FAILED = "action_failed"


class ComputerTargetSource(StrEnum):
    NATIVE_CONTROL = "native_control"
    VISION = "vision"
    COMBINED = "combined"


class ComputerTarget(BaseModel):
    """One visible target grounded in the current desktop observation."""

    id: str = Field(min_length=1, max_length=80)
    label: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=80)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(default=0, ge=0)
    height: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: ComputerTargetSource = ComputerTargetSource.VISION

    def contains(self, x: int, y: int, *, tolerance: int = 12) -> bool:
        if self.width <= 0 or self.height <= 0:
            return abs(self.x - x) <= tolerance and abs(self.y - y) <= tolerance
        return (
            self.x - tolerance <= x <= self.x + self.width + tolerance
            and self.y - tolerance <= y <= self.y + self.height + tolerance
        )

    @property
    def center(self) -> tuple[int, int]:
        if self.width <= 0 or self.height <= 0:
            return self.x, self.y
        return self.x + self.width // 2, self.y + self.height // 2

    def display_summary(self) -> str:
        label = self.label or "未命名目标"
        return f"{label} · {self.role or '可见元素'}"


class ComputerSemanticSnapshot(BaseModel):
    """Ephemeral native-control metadata used to ground visual analysis."""

    foreground_app: str = ""
    targets: list[ComputerTarget] = Field(default_factory=list)


class ComputerPlan(BaseModel):
    id: str
    session_id: str
    task_id: str = ""
    goal: str
    target_app: str = ""
    allowed_actions: list[ComputerActionType] = Field(default_factory=list)
    max_actions: int = Field(default=12, ge=1, le=50)
    completed_actions: int = Field(default=0, ge=0)
    status: ComputerPlanStatus = ComputerPlanStatus.PENDING_APPROVAL
    authorized_until: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def authorization_is_valid(self, now: datetime | None = None) -> bool:
        now = now or utc_now()
        return (
            self.status == ComputerPlanStatus.ACTIVE
            and self.authorized_until is not None
            and self.authorized_until > now
            and self.completed_actions < self.max_actions
        )


class ComputerAction(BaseModel):
    action: ComputerActionType
    description: str = Field(default="", max_length=300)
    observation_id: str = Field(default="", max_length=80)
    target_id: str = Field(default="", max_length=80)
    target_label: str = Field(default="", max_length=200)
    target_role: str = Field(default="", max_length=80)
    expected_outcome: str = Field(default="", max_length=500)
    x: int | None = None
    y: int | None = None
    scroll_delta: int = Field(default=0, ge=-20, le=20)
    text: str = Field(default="", max_length=1000)
    key: str = Field(default="", max_length=30)
    hotkey: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_required_fields(self) -> "ComputerAction":
        if self.action in {
            ComputerActionType.MOVE,
            ComputerActionType.CLICK,
            ComputerActionType.DOUBLE_CLICK,
        } and (self.x is None or self.y is None):
            raise ValueError("Pointer actions require x and y coordinates")
        if self.action == ComputerActionType.SCROLL and self.scroll_delta == 0:
            raise ValueError("Scroll action requires a non-zero scroll_delta")
        if self.action == ComputerActionType.TYPE_TEXT and not self.text:
            raise ValueError("type_text action requires text")
        if self.action == ComputerActionType.PRESS_KEY and not self.key:
            raise ValueError("press_key action requires key")
        if self.action == ComputerActionType.HOTKEY and len(self.hotkey) < 2:
            raise ValueError("hotkey action requires at least two keys")
        return self

    def audit_summary(self) -> str:
        if self.action == ComputerActionType.TYPE_TEXT:
            return f"{self.action.value}: text_length={len(self.text)}"
        elif self.action == ComputerActionType.HOTKEY:
            detail = "+".join(self.hotkey)
        elif self.action == ComputerActionType.PRESS_KEY:
            detail = self.key
        elif self.action == ComputerActionType.SCROLL:
            detail = f"delta={self.scroll_delta}"
        else:
            detail = f"x={self.x}, y={self.y}"
        return f"{self.action.value}: {detail}; {self.description}".strip()

    def target_summary(self) -> str:
        label = self.target_label.strip() or "未命名目标"
        role = self.target_role.strip()
        return f"{label} · {role}" if role else label


class ComputerActionResult(BaseModel):
    success: bool
    plan_id: str
    checkpoint_id: str = ""
    step_index: int = 0
    message: str
    target_summary: str = ""
    expected_outcome: str = ""


class ComputerObservation(BaseModel):
    observation_id: str = ""
    plan_id: str
    width: int
    height: int
    analysis: str
    foreground_app: str = ""
    targets: list[ComputerTarget] = Field(default_factory=list)
    observed_at: datetime = Field(default_factory=utc_now)


class ComputerVerification(BaseModel):
    plan_id: str
    checkpoint_id: str
    verified: bool
    summary: str
    expected_outcome: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ComputerCheckpoint(BaseModel):
    id: str
    plan_id: str
    step_index: int = Field(ge=1)
    action_type: ComputerActionType
    action_summary: str
    observation_id: str = ""
    target_summary: str = ""
    target_source: ComputerTargetSource | None = None
    expected_outcome: str = ""
    status: ComputerCheckpointStatus
    result_summary: str = ""
    verification_summary: str = ""
    verification_attempts: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime
