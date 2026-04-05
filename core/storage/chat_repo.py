"""Chat repository for conversation history."""

from datetime import datetime
from typing import List, Optional

from core.models.chat import ChatMessage, ChatSession
from core.storage.db import Database, get_database


class ChatRepository:
    """Repository for chat history operations."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
        self._init_tables()

    def _init_tables(self):
        """Initialize chat tables."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_session (
                    id TEXT PRIMARY KEY,
                    pet_id TEXT NOT NULL DEFAULT 'default',
                    title TEXT NOT NULL DEFAULT 'New Chat',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_message (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES chat_session(id) ON DELETE CASCADE
                )
            """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_session_updated 
                ON chat_session(updated_at DESC)
            """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_message_session 
                ON chat_message(session_id, created_at ASC)
            """
            )

            conn.commit()

    def get_or_create_session(
        self, session_id: str = "default", pet_id: str = "default", title: str = "New Chat"
    ) -> ChatSession:
        """Get existing session or create new."""
        session = self.get_session(session_id)
        if session is None:
            session = ChatSession(id=session_id, pet_id=pet_id, title=title)
            self.save_session(session)
        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Get chat session by ID with messages."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM chat_session WHERE id = ?", (session_id,))
            row = cursor.fetchone()

            if not row:
                return None

            session = ChatSession(
                id=row["id"],
                pet_id=row["pet_id"],
                title=row["title"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            session.messages = self.get_messages(session_id)
            return session

    def get_all_sessions(self, limit: int = 20) -> List[ChatSession]:
        """Get all chat sessions ordered by update time."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM chat_session 
                ORDER BY updated_at DESC
                LIMIT ?
            """,
                (limit,),
            )

            sessions = []
            for row in cursor.fetchall():
                sessions.append(
                    ChatSession(
                        id=row["id"],
                        pet_id=row["pet_id"],
                        title=row["title"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"]),
                        messages=[],  # Don't load messages for list view
                    )
                )
            return sessions

    def save_session(self, session: ChatSession):
        """Save or update chat session."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO chat_session (id, pet_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    updated_at = excluded.updated_at
            """,
                (
                    session.id,
                    session.pet_id,
                    session.title,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def update_session_title(self, session_id: str, title: str):
        """Update session title."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE chat_session SET title = ?, updated_at = ? WHERE id = ?",
                (title, datetime.now().isoformat(), session_id),
            )
            conn.commit()

    def get_messages(self, session_id: str, limit: int = 1000) -> List[ChatMessage]:
        """Get messages for session."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM chat_message 
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
            """,
                (session_id, limit),
            )

            messages = []
            for row in cursor.fetchall():
                messages.append(
                    ChatMessage(
                        id=row["id"],
                        session_id=row["session_id"],
                        role=row["role"],
                        content=row["content"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                    )
                )
            return messages

    def save_message(self, message: ChatMessage):
        """Save chat message."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO chat_message (id, session_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    message.id,
                    message.session_id,
                    message.role,
                    message.content,
                    message.created_at.isoformat(),
                ),
            )
            conn.commit()

            cursor.execute(
                "UPDATE chat_session SET updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), message.session_id),
            )
            conn.commit()

    def delete_session(self, session_id: str):
        """Delete session and all its messages."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chat_session WHERE id = ?", (session_id,))
            conn.commit()

    def clear_session(self, session_id: str):
        """Clear all messages in session."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chat_message WHERE session_id = ?", (session_id,))
            conn.commit()
