"""Domain models for privacy-preserving user presence."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ActivityCategory(str, Enum):
    DEVELOPMENT = "development"
    COMMUNICATION = "communication"
    BROWSER = "browser"
    PRODUCTIVITY = "productivity"
    MEDIA = "media"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class InterventionKind(str, Enum):
    GREETING = "greeting"
    RETURNED = "returned"
    REST = "rest"
    LATE_NIGHT = "late_night"
    FAILURE_SUPPORT = "failure_support"
    RECOVERY = "recovery"
    CHECK_IN = "check_in"


class CompanionMood(str, Enum):
    """A user-authored, non-clinical description of the current moment."""

    GOOD = "good"
    STEADY = "steady"
    TIRED = "tired"
    TENSE = "tense"
    LOW = "low"


class CompanionEnergy(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CompanionSupportMode(str, Enum):
    LISTEN = "listen"
    ENCOURAGE = "encourage"
    FOCUS = "focus"
    PRACTICAL = "practical"
    QUIET = "quiet"


class CompanionFeedbackAction(str, Enum):
    HELPFUL = "helpful"
    LATER = "later"
    MUTE_KIND = "mute_kind"


INTERVENTION_KIND_LABELS: dict[InterventionKind, str] = {
    InterventionKind.GREETING: "日常问候",
    InterventionKind.RETURNED: "回来欢迎",
    InterventionKind.REST: "休息提醒",
    InterventionKind.LATE_NIGHT: "深夜关怀",
    InterventionKind.FAILURE_SUPPORT: "失败安慰",
    InterventionKind.RECOVERY: "恢复鼓励",
    InterventionKind.CHECK_IN: "状态回应",
}

COMPANION_MOOD_LABELS: dict[CompanionMood, str] = {
    CompanionMood.GOOD: "还不错",
    CompanionMood.STEADY: "还算平稳",
    CompanionMood.TIRED: "有点累",
    CompanionMood.TENSE: "有点绷",
    CompanionMood.LOW: "有些低落",
}

COMPANION_ENERGY_LABELS: dict[CompanionEnergy, str] = {
    CompanionEnergy.LOW: "电量不多",
    CompanionEnergy.MEDIUM: "还能继续",
    CompanionEnergy.HIGH: "精力不错",
}

COMPANION_SUPPORT_LABELS: dict[CompanionSupportMode, str] = {
    CompanionSupportMode.LISTEN: "陪我聊聊",
    CompanionSupportMode.ENCOURAGE: "给点鼓励",
    CompanionSupportMode.FOCUS: "陪我专注",
    CompanionSupportMode.PRACTICAL: "帮我理清",
    CompanionSupportMode.QUIET: "先安静陪着",
}


def intervention_kind_label(kind: InterventionKind) -> str:
    return INTERVENTION_KIND_LABELS.get(kind, "主动关怀")


def companion_mood_label(mood: CompanionMood) -> str:
    return COMPANION_MOOD_LABELS[mood]


def companion_energy_label(energy: CompanionEnergy) -> str:
    return COMPANION_ENERGY_LABELS[energy]


def companion_support_label(support_mode: CompanionSupportMode) -> str:
    return COMPANION_SUPPORT_LABELS[support_mode]


class ObservationSnapshot(BaseModel):
    """A short-lived observation; window titles and input content are never included."""

    observed_at: datetime = Field(default_factory=datetime.now)
    available: bool = True
    idle_seconds: float = Field(default=0.0, ge=0.0)
    foreground_app: str = ""
    activity_category: ActivityCategory = ActivityCategory.UNKNOWN

    def privacy_filtered(self) -> "ObservationSnapshot":
        return self.model_copy(
            update={
                "foreground_app": "",
                "activity_category": ActivityCategory.UNKNOWN,
            }
        )


class CompanionIntervention(BaseModel):
    event_id: int | None = None
    kind: InterventionKind
    title: str = "温柔提醒"
    message: str
    reason: str = ""
    state_hint: str = "happy"
    duration_ms: int = Field(default=4500, ge=1000, le=15000)
    created_at: datetime = Field(default_factory=datetime.now)


class CompanionCheckIn(BaseModel):
    """A minimal, expiring statement authored by the user."""

    id: int | None = None
    mood: CompanionMood
    energy: CompanionEnergy
    support_mode: CompanionSupportMode
    created_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime

    @model_validator(mode="after")
    def validate_expiry(self) -> "CompanionCheckIn":
        if self.expires_at <= self.created_at:
            raise ValueError("Companion Check-in expiry must be after creation")
        return self

    def is_active(self, now: datetime) -> bool:
        return self.created_at <= now < self.expires_at


class CompanionCheckInResult(BaseModel):
    accepted: bool
    check_in: CompanionCheckIn
    intervention: CompanionIntervention
    persisted: bool


class CompanionFeedbackResult(BaseModel):
    accepted: bool
    action: CompanionFeedbackAction
    kind: InterventionKind | None = None
    message: str
    snoozed_until: datetime | None = None


class CompanionPreferenceSummary(BaseModel):
    helpful_count: int = 0
    later_count: int = 0
    muted_kinds: list[InterventionKind] = Field(default_factory=list)
    snoozed_until: datetime | None = None


class CompanionPollResult(BaseModel):
    snapshot: ObservationSnapshot
    intervention: CompanionIntervention | None = None
