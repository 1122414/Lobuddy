"""Chat history model for Lobuddy."""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Single chat message with optional image attachment."""

    id: str
    session_id: str = "default"
    role: str  # "user" or "assistant"
    content: str
    image_path: Optional[str] = None  # Path to attached image
    created_at: datetime = Field(default_factory=datetime.now)


class ChatSession(BaseModel):
    """Chat session with message history."""

    id: str = "default"
    pet_id: str = "default"
    title: str = "Chat History"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    messages: List[ChatMessage] = Field(default_factory=list)

    def add_message(self, role: str, content: str) -> ChatMessage:
        """Add message to session."""
        msg = ChatMessage(id=str(uuid.uuid4()), session_id=self.id, role=role, content=content)
        self.messages.append(msg)
        self.updated_at = datetime.now()
        return msg

    def get_recent_messages(self, limit: int = 50) -> List[ChatMessage]:
        """Get recent messages."""
        return self.messages[-limit:]

    def clear(self):
        """Clear all messages."""
        self.messages.clear()
        self.updated_at = datetime.now()
