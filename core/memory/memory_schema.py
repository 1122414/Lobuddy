"""Memory data schema for Lobuddy 5.2 memory system."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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
    scope: str = Field(default="global", description="Scope filter (e.g., project name)")
    title: str = Field(default="", description="Short title for indexing")
    content: str = Field(..., description="Memory content")
    source: str = Field(default="ai", description="Source: ai, user, manual, migration")
    source_session_id: Optional[str] = Field(default=None, description="Originating session")
    source_message_id: Optional[str] = Field(default=None, description="Originating message")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence score")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="Importance score")
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

    items: list[MemoryPatchItem] = Field(default_factory=list, max_length=16)


class PromptContextBundle(BaseModel):
    """Bundle of context segments injected into AI prompts."""

    user_profile: str = Field(default="", description="Compact user profile")
    system_profile: str = Field(default="", description="System behavior profile")
    session_summary: str = Field(default="", description="Current session summary")
    retrieved_memories: str = Field(default="", description="Relevant past memories")
    active_skills: str = Field(default="", description="Available skill summaries")
    total_chars: int = Field(default=0, description="Total injected characters")

    def is_empty(self) -> bool:
        return self.total_chars == 0

    def build_injection_text(self) -> str:
        parts: list[str] = []
        if self.user_profile:
            parts.append(f"### User Profile\n\n{self.user_profile}")
        if self.system_profile:
            parts.append(f"### System Profile\n\n{self.system_profile}")
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
            "以下是我的实时记忆。我不使用 Dream 机制，所有记忆都是即时持久化的。\n\n"
        )
        return header + "\n\n---\n\n".join(parts) + "\n\n"
