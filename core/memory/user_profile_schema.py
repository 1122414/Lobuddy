"""User profile data schema for MEMORY feature."""

from enum import Enum

from pydantic import BaseModel, Field


class ProfileSection(str, Enum):
    """Valid sections in USER.md."""

    BASIC_NOTES = "Basic Notes"
    PREFERENCES = "Preferences"
    WORK_AND_PROJECTS = "Work And Projects"
    COMMUNICATION_STYLE = "Communication Style"
    LONG_TERM_GOALS = "Long-Term Goals"
    BOUNDARIES_AND_DISLIKES = "Boundaries And Dislikes"
    OPEN_QUESTIONS = "Open Questions"


class PatchAction(str, Enum):
    """Valid patch actions."""

    ADD = "add"
    UPDATE = "update"
    REMOVE = "remove"
    UNCERTAIN = "uncertain"


class ProfilePatchItem(BaseModel):
    """Single patch item for profile update."""

    section: ProfileSection
    action: PatchAction
    content: str = Field(..., min_length=1, max_length=500)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str | None = None


class ProfilePatch(BaseModel):
    """Collection of patch items from AI analysis."""

    items: list[ProfilePatchItem] = Field(default_factory=list, max_length=8)


class UserProfile(BaseModel):
    """Complete user profile structure."""

    sections: dict[ProfileSection, list[str]] = Field(default_factory=dict)
