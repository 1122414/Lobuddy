"""Memory data schema for Lobuddy structured memory system."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class MemoryType(str, Enum):
    """Valid memory types."""

    USER_PROFILE = "user_profile"
    SYSTEM_PROFILE = "system_profile"
    PROJECT_MEMORY = "project_memory"
    CONVERSATION_SUMMARY = "conversation_summary"
    EPISODIC_MEMORY = "episodic_memory"
    PROCEDURAL_MEMORY = "procedural_memory"


class MemoryStatus(str, Enum):
    """Valid memory item statuses."""

    ACTIVE = "active"
    NEEDS_REVIEW = "needs_review"
    DEPRECATED = "deprecated"


class MemoryItem(BaseModel):
    """A single memory item stored in SQLite."""

    id: str = Field(..., description="Unique identifier")
    memory_type: MemoryType = Field(..., description="Type of memory")
    scope: str = Field(default="global", description="Scope filter")
    title: str = Field(default="", description="Short title for indexing")
    content: str = Field(..., description="Memory content")
    source: str = Field(default="ai", description="Source: ai, user, manual, migration")
    source_session_id: Optional[str] = Field(default=None, description="Originating session")
    source_message_id: Optional[str] = Field(default=None, description="Originating message")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence score")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="Importance score")
    priority: int = Field(default=50, ge=1, le=100, description="Injection priority")
    status: MemoryStatus = Field(default=MemoryStatus.ACTIVE, description="Lifecycle status")
    expires_at: Optional[datetime] = Field(default=None, description="Optional expiration")
    last_used_at: Optional[datetime] = Field(default=None, description="Last prompt injection")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at

    def touch(self) -> None:
        self.last_used_at = datetime.now()
        self.updated_at = datetime.now()


class ConversationSummary(BaseModel):
    """A rolling or session-level conversation summary."""

    id: str = Field(..., description="Unique identifier")
    session_id: str = Field(..., description="Associated chat session")
    summary_type: str = Field(default="rolling", description="rolling | session_end")
    content: str = Field(..., description="Summary text")
    from_message_id: Optional[str] = Field(default=None, description="First message in range")
    to_message_id: Optional[str] = Field(default=None, description="Last message in range")
    token_estimate: int = Field(default=0, ge=0, description="Estimated token count")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class MemoryPatchAction(str, Enum):
    """Valid patch actions for memory updates."""

    ADD = "add"
    UPDATE = "update"
    MERGE = "merge"
    REMOVE = "remove"
    DEPRECATE = "deprecate"
    UNCERTAIN = "uncertain"


class MemoryPatchItem(BaseModel):
    """Single patch item from AI analysis."""

    memory_type: MemoryType = Field(..., description="Target memory type")
    action: MemoryPatchAction = Field(..., description="Patch action")
    content: str = Field(..., min_length=1, max_length=2000, description="Memory content")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence score")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="Importance score")
    reason: Optional[str] = Field(default=None, description="Why this patch was proposed")
    scope: str = Field(default="global", description="Scope for the memory")
    title: str = Field(default="", description="Short title")


class MemoryPatch(BaseModel):
    """Collection of memory patch items."""

    items: list[MemoryPatchItem] = Field(default_factory=list)

    @field_validator("items")
    @classmethod
    def validate_item_count(cls, value: list[MemoryPatchItem]) -> list[MemoryPatchItem]:
        if len(value) > 16:
            raise ValueError("MemoryPatch supports at most 16 items")
        return value


class ConflictStatus(str, Enum):
    """Conflict candidate resolution status."""

    PENDING = "pending"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class ConflictType(str, Enum):
    """Type of memory conflict detected."""

    SAME_TITLE = "same_title"
    DIFFERENT_VALUE = "different_value"


class ConflictCandidate(BaseModel):
    """A detected conflict between two memory items sharing the same identity key."""

    id: str = Field(..., description="Unique conflict candidate identifier")
    existing_item_id: str = Field(..., description="ID of the existing memory item")
    new_item_id: str = Field(..., description="ID of the conflicting new memory item")
    conflict_type: ConflictType = Field(..., description="Type of conflict detected")
    status: ConflictStatus = Field(default=ConflictStatus.PENDING, description="Resolution status")
    created_at: datetime = Field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = Field(default=None)


class MemoryRevisionType(str, Enum):
    """User-visible reasons a structured memory changed state."""

    LEARNED = "learned"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    RETIRED = "retired"
    RESTORED = "restored"
    FORGOTTEN = "forgotten"
    CONFLICT_RESOLVED = "conflict_resolved"
    FLAGGED_INACCURATE = "flagged_inaccurate"
    EXPIRED = "expired"


class MemoryRevision(BaseModel):
    """Content-minimized, append-only history for one memory."""

    id: str = Field(..., description="Unique revision identifier")
    memory_id: str = Field(..., description="Memory affected by this revision")
    revision_type: MemoryRevisionType
    actor: str = Field(default="system", min_length=1, max_length=80)
    reason: str = Field(default="", max_length=500)
    related_memory_id: Optional[str] = Field(default=None)
    previous_content_hash: str = Field(default="", max_length=64)
    new_content_hash: str = Field(default="", max_length=64)
    created_at: datetime = Field(default_factory=datetime.now)


class MemoryContextEvidence(BaseModel):
    """Content-minimized evidence that one memory entered the current prompt."""

    memory_id: str = Field(..., description="Selected memory identifier")
    memory_type: MemoryType = Field(..., description="Selected memory type")
    reason: str = Field(default="", max_length=120, description="Privacy-safe selection reason")
    chars: int = Field(default=0, ge=0, description="Characters contributed to the prompt")


class MemoryRecallFeedback(str, Enum):
    """Explicit user judgment about one memory used by one Task Run."""

    UNREVIEWED = "unreviewed"
    HELPFUL = "helpful"
    NOT_RELEVANT = "not_relevant"
    INACCURATE = "inaccurate"


class MemoryRecallReceipt(BaseModel):
    """Content-free receipt linking one selected memory to one Task Run."""

    task_id: str = Field(..., min_length=1, max_length=128)
    session_id: str = Field(default="", max_length=128)
    memory_id: str = Field(..., min_length=1, max_length=160)
    memory_type: MemoryType
    reason: str = Field(default="", max_length=120)
    contributed_chars: int = Field(default=0, ge=0)
    memory_updated_at: Optional[datetime] = None
    feedback: MemoryRecallFeedback = MemoryRecallFeedback.UNREVIEWED
    selected_at: datetime = Field(default_factory=datetime.now)
    feedback_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_feedback_time(self) -> "MemoryRecallReceipt":
        reviewed = self.feedback != MemoryRecallFeedback.UNREVIEWED
        if reviewed != (self.feedback_at is not None):
            raise ValueError("feedback_at must exist exactly when recall feedback is reviewed")
        if self.feedback_at is not None and self.feedback_at < self.selected_at:
            raise ValueError("feedback_at cannot precede selected_at")
        return self


class PromptContextBundle(BaseModel):
    """Bundle of context segments injected into AI prompts.

    Injection order (and corresponding budget names):
      User Profile → memory_hot_user_profile_tokens
      System Profile → memory_hot_system_profile_tokens
      Project Context → memory_hot_project_context_tokens
      Current Session Summary
      Relevant Past Memory
      Available Skills
    """

    user_profile: str = Field(default="", description="Compact user profile")
    system_profile: str = Field(default="", description="System behavior profile")
    project_context: str = Field(default="", description="Current project-specific context")
    session_summary: str = Field(default="", description="Current session summary")
    retrieved_memories: str = Field(default="", description="Relevant past memories")
    active_skills: str = Field(default="", description="Available skill summaries")
    total_chars: int = Field(default=0, description="Total injected characters")
    memory_budget_report: dict[str, int] = Field(
        default_factory=dict, description="Per-section budget consumption"
    )
    memory_evidence: list[MemoryContextEvidence] = Field(
        default_factory=list,
        description="Content-minimized evidence for selected structured memories",
    )
    privacy_active: bool = Field(
        default=False,
        description="Whether privacy mode suppressed memory selection",
    )
    injection_enabled: bool = Field(
        default=True,
        description="Whether structured memory injection is enabled",
    )

    @property
    def selected_count(self) -> int:
        return len(self.memory_evidence)

    def type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for evidence in self.memory_evidence:
            key = evidence.memory_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def is_empty(self) -> bool:
        return (
            not self.user_profile
            and not self.system_profile
            and not self.project_context
            and not self.session_summary
            and not self.retrieved_memories
            and not self.active_skills
        )

    def build_injection_text(self) -> str:
        parts: list[str] = []
        if self.user_profile:
            parts.append(f"### User Profile\n\n{self.user_profile}")
        if self.system_profile:
            parts.append(f"### System Profile\n\n{self.system_profile}")
        if self.project_context:
            parts.append(f"### Project Context\n\n{self.project_context}")
        if self.session_summary:
            parts.append(f"### Current Session Summary\n\n{self.session_summary}")
        if self.retrieved_memories:
            parts.append(f"### Relevant Past Memory\n\n{self.retrieved_memories}")
        if self.active_skills:
            parts.append(f"### Available Skills\n\n{self.active_skills}")
        if not parts:
            return ""
        header = (
            "## Lobuddy Memory Context\n\n"
            "The following is relevant, user-governed context maintained by Lobuddy. "
            "It may be incomplete or outdated: use it only when it helps, never invent details "
            "from it, and always follow the user's current request or correction first.\n\n"
        )
        return header + "\n\n---\n\n".join(parts) + "\n\n"
