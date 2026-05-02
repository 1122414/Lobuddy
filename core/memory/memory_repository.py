"""SQLite repository for memory items and conversation summaries."""

import logging
import sqlite3
import uuid
from datetime import datetime
from typing import List, Optional

from core.memory.memory_schema import ConversationSummary, MemoryItem, MemoryStatus, MemoryType
from core.storage.base_repo import BaseRepository
from core.storage.db import Database

logger = logging.getLogger(__name__)


class MemoryRepository(BaseRepository):
    """Repository for memory_item and conversation_summary tables."""

    def __init__(self, db: Optional[Database] = None):
        super().__init__(db)
        self._init_tables()

    def _init_tables(self):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_item (
                    id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'global',
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'ai',
                    source_session_id TEXT,
                    source_message_id TEXT,
                    confidence REAL NOT NULL DEFAULT 0.8,
                    importance REAL NOT NULL DEFAULT 0.5,
                    status TEXT NOT NULL DEFAULT 'active',
                    expires_at TEXT,
                    last_used_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_type_status
                ON memory_item(memory_type, status)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_scope
                ON memory_item(scope)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_created
                ON memory_item(created_at DESC)
                """
            )
            if self.db.has_fts5():
                try:
                    cursor.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS memory_item_fts
                        USING fts5(title, content, content='memory_item', content_rowid='rowid')
                        """
                    )
                except sqlite3.OperationalError:
                    logger.debug("FTS5 table already exists or unavailable")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_summary (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    summary_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    from_message_id TEXT,
                    to_message_id TEXT,
                    token_estimate INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_summary_session
                ON conversation_summary(session_id, created_at DESC)
                """
            )
            conn.commit()

    def save(self, item: MemoryItem) -> MemoryItem:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_item (
                    id, memory_type, scope, title, content, source,
                    source_session_id, source_message_id, confidence, importance,
                    status, expires_at, last_used_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.memory_type.value,
                    item.scope,
                    item.title,
                    item.content,
                    item.source,
                    item.source_session_id,
                    item.source_message_id,
                    item.confidence,
                    item.importance,
                    item.status.value,
                    item.expires_at.isoformat() if item.expires_at else None,
                    item.last_used_at.isoformat() if item.last_used_at else None,
                    item.created_at.isoformat(),
                    item.updated_at.isoformat(),
                ),
            )
        return item

    def get(self, item_id: str) -> Optional[MemoryItem]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM memory_item WHERE id = ?", (item_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_memory_item(row)

    def list_by_type(
        self,
        memory_type: MemoryType,
        status: Optional[MemoryStatus] = None,
        scope: Optional[str] = None,
        limit: int = 100,
    ) -> List[MemoryItem]:
        query = "SELECT * FROM memory_item WHERE memory_type = ?"
        params: list = [memory_type.value]
        if status:
            query += " AND status = ?"
            params.append(status.value)
        if scope:
            query += " AND scope = ?"
            params.append(scope)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_memory_item(r) for r in rows]

    def search_by_keyword(
        self,
        keyword: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 10,
    ) -> List[MemoryItem]:
        query = (
            "SELECT * FROM memory_item WHERE status = 'active' "
            "AND (title LIKE ? OR content LIKE ?)"
        )
        params = [f"%{keyword}%", f"%{keyword}%"]
        if memory_type:
            query += " AND memory_type = ?"
            params.append(memory_type.value)
        query += " ORDER BY importance DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_memory_item(r) for r in rows]

    def search_fts(
        self,
        query_text: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 10,
    ) -> List[MemoryItem]:
        if not self.db.has_fts5():
            return self.search_by_keyword(query_text, memory_type, limit)
        sql = (
            "SELECT m.* FROM memory_item m "
            "JOIN memory_item_fts fts ON m.rowid = fts.rowid "
            "WHERE fts.memory_item_fts MATCH ? AND m.status = 'active'"
        )
        params: list = [query_text]
        if memory_type:
            sql += " AND m.memory_type = ?"
            params.append(memory_type.value)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        with self.db.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_memory_item(r) for r in rows]

    def update_status(self, item_id: str, status: MemoryStatus) -> bool:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE memory_item SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, datetime.now().isoformat(), item_id),
            )
            return cursor.rowcount > 0

    def delete(self, item_id: str) -> bool:
        with self.db.transaction() as conn:
            cursor = conn.execute("DELETE FROM memory_item WHERE id = ?", (item_id,))
            return cursor.rowcount > 0

    def save_summary(self, summary: ConversationSummary) -> ConversationSummary:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO conversation_summary (
                    id, session_id, summary_type, content, from_message_id,
                    to_message_id, token_estimate, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.id,
                    summary.session_id,
                    summary.summary_type,
                    summary.content,
                    summary.from_message_id,
                    summary.to_message_id,
                    summary.token_estimate,
                    summary.created_at.isoformat(),
                    summary.updated_at.isoformat(),
                ),
            )
        return summary

    def get_latest_summary(self, session_id: str) -> Optional[ConversationSummary]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM conversation_summary
                WHERE session_id = ? ORDER BY created_at DESC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_conversation_summary(row)

    def list_summaries(self, session_id: str, limit: int = 10) -> List[ConversationSummary]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM conversation_summary
                WHERE session_id = ? ORDER BY created_at DESC LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
            return [self._row_to_conversation_summary(r) for r in rows]

    def _row_to_memory_item(self, row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=row["id"],
            memory_type=MemoryType(row["memory_type"]),
            scope=row["scope"],
            title=row["title"],
            content=row["content"],
            source=row["source"],
            source_session_id=row["source_session_id"],
            source_message_id=row["source_message_id"],
            confidence=row["confidence"],
            importance=row["importance"],
            status=MemoryStatus(row["status"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            last_used_at=datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_conversation_summary(self, row: sqlite3.Row) -> ConversationSummary:
        return ConversationSummary(
            id=row["id"],
            session_id=row["session_id"],
            summary_type=row["summary_type"],
            content=row["content"],
            from_message_id=row["from_message_id"],
            to_message_id=row["to_message_id"],
            token_estimate=row["token_estimate"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
