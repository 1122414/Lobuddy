import logging
import sqlite3
from datetime import datetime
from typing import List, Optional

from core.models.chat import ChatMessage, ChatSession
from core.storage.base_repo import BaseRepository, _parse_iso
from core.storage.db import Database

logger = logging.getLogger("lobuddy.chat_repo")


class ChatRepository(BaseRepository):
    def __init__(self, db: Optional[Database] = None):
        super().__init__(db)
        self._init_tables()

    def _init_tables(self):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_session (
                    id TEXT PRIMARY KEY,
                    pet_id TEXT NOT NULL DEFAULT 'default',
                    title TEXT NOT NULL DEFAULT 'New Chat',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_message (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    image_path TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES chat_session(id) ON DELETE CASCADE
                )
            """)
            self._ensure_column(cursor, "chat_message", "image_path TEXT")
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_session_updated 
                ON chat_session(updated_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_message_session 
                ON chat_message(session_id, created_at ASC)
            """)
            conn.commit()

    def get_or_create_session(
        self, session_id: str = "default", pet_id: str = "default", title: str = "New Chat"
    ) -> ChatSession:
        session = self.get_session(session_id)
        if session is None:
            session = ChatSession(id=session_id, pet_id=pet_id, title=title)
            self.save_session(session)
        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM chat_session WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return None
            session = ChatSession(
                id=row["id"],
                pet_id=row["pet_id"],
                title=row["title"],
                created_at=_parse_iso(row["created_at"]),
                updated_at=_parse_iso(row["updated_at"]),
            )
            session.messages = self.get_messages(session_id)
            return session

    def get_all_sessions(self, limit: int = 20) -> List[ChatSession]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_session ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                ChatSession(
                    id=row["id"],
                    pet_id=row["pet_id"],
                    title=row["title"],
                    created_at=_parse_iso(row["created_at"]),
                    updated_at=_parse_iso(row["updated_at"]),
                    messages=[],
                )
                for row in rows
            ]

    def save_session(self, session: ChatSession):
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO chat_session (id, pet_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    updated_at = excluded.updated_at
                """,
                (
                    session.id, session.pet_id, session.title,
                    session.created_at.isoformat(), session.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def update_session_title(self, session_id: str, title: str):
        with self.db.get_connection() as conn:
            now = datetime.now().isoformat()
            conn.execute(
                """
                INSERT OR IGNORE INTO chat_session (id, pet_id, title, created_at, updated_at)
                VALUES (?, 'default', ?, ?, ?)
                """,
                (session_id, title, now, now),
            )
            conn.execute(
                "UPDATE chat_session SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, session_id),
            )
            conn.commit()

    def get_messages(self, session_id: str, limit: int = 1000) -> List[ChatMessage]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM chat_message
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
            messages = []
            for row in rows:
                try:
                    messages.append(ChatMessage(
                        id=row["id"],
                        session_id=row["session_id"],
                        role=row["role"],
                        content=row["content"],
                        image_path=row["image_path"],
                        created_at=_parse_iso(row["created_at"]),
                    ))
                except Exception as msg_err:
                    logger.warning(f"Skipping malformed message in session {session_id}: {msg_err}")
            return messages

    def save_message(self, message: ChatMessage):
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO chat_message (id, session_id, role, content, image_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id, message.session_id, message.role,
                    message.content, message.image_path, message.created_at.isoformat(),
                ),
            )
            conn.execute(
                "UPDATE chat_session SET updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), message.session_id),
            )

    def delete_session(self, session_id: str):
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM chat_session WHERE id = ?", (session_id,))
            conn.commit()

    def clear_session(self, session_id: str):
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM chat_message WHERE session_id = ?", (session_id,))
            conn.commit()
