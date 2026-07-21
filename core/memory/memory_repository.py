"""SQLite repository for memory items, conversation summaries, and conflict candidates."""

import logging
import sqlite3
from datetime import datetime
from typing import List, Optional

from core.memory.memory_schema import (
    ConflictCandidate,
    ConflictStatus,
    ConflictType,
    ConversationSummary,
    MemoryItem,
    MemoryRecallFeedback,
    MemoryRecallReceipt,
    MemoryRevision,
    MemoryRevisionType,
    MemoryStatus,
    MemoryType,
)
from core.storage.base_repo import BaseRepository
from core.storage.db import Database, _ensure_column

logger = logging.getLogger(__name__)


class MemoryRepository(BaseRepository):
    """Repository for memory_item and conversation_summary tables."""

    def __init__(self, db: Optional[Database] = None):
        super().__init__(db)
        self._init_tables()
        self._init_conflict_tables()
        self._init_revision_tables()
        self._init_import_tables()
        self._init_recall_tables()

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
                    priority INTEGER NOT NULL DEFAULT 50,
                    status TEXT NOT NULL DEFAULT 'active',
                    expires_at TEXT,
                    last_used_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            _ensure_column(cursor, "memory_item", "priority INTEGER NOT NULL DEFAULT 50")
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
            self._write_memory_item(conn, item)
        return item

    def save_with_revision(
        self,
        item: MemoryItem,
        revision: MemoryRevision,
    ) -> MemoryItem:
        """Atomically persist a memory and its append-only revision."""
        if revision.memory_id != item.id:
            raise ValueError("Memory revision must reference the saved memory")
        with self.db.transaction() as conn:
            self._write_memory_item(conn, item)
            self._write_revision(conn, revision)
        return item

    def save_many_with_revisions(
        self,
        entries: list[tuple[MemoryItem, MemoryRevision]],
    ) -> list[MemoryItem]:
        """Atomically persist a bounded batch and one revision per memory."""
        if not entries:
            return []
        memory_ids = {item.id for item, _revision in entries}
        if len(memory_ids) != len(entries):
            raise ValueError("Batch memory IDs must be unique")
        for item, revision in entries:
            if revision.memory_id != item.id:
                raise ValueError("Memory revision must reference the saved memory")
        with self.db.transaction() as conn:
            for item, revision in entries:
                self._write_memory_item(conn, item)
                self._write_revision(conn, revision)
        return [item for item, _revision in entries]

    def save_import_batch(
        self,
        package_id: str,
        entries: list[tuple[MemoryItem, MemoryRevision, str]],
    ) -> tuple[list[MemoryItem], list[str]]:
        """Atomically persist review-gated imports and their idempotency records."""
        if not entries:
            return [], []
        seen: set[str] = set()
        for item, revision, entry_digest in entries:
            if revision.memory_id != item.id:
                raise ValueError("Memory revision must reference the imported memory")
            if item.status != MemoryStatus.NEEDS_REVIEW:
                raise ValueError("Imported memories must enter NEEDS_REVIEW")
            if entry_digest in seen:
                raise ValueError("Import batch contains duplicate entry digests")
            seen.add(entry_digest)

        saved: list[MemoryItem] = []
        skipped: list[str] = []
        imported_at = datetime.now().isoformat()
        with self.db.transaction() as conn:
            placeholders = ", ".join("?" for _entry in entries)
            rows = conn.execute(
                "SELECT entry_digest FROM memory_import_record "
                f"WHERE entry_digest IN ({placeholders})",
                tuple(entry_digest for _item, _revision, entry_digest in entries),
            ).fetchall()
            existing = {row["entry_digest"] for row in rows}
            for item, revision, entry_digest in entries:
                if entry_digest in existing:
                    skipped.append(entry_digest)
                    continue
                self._write_memory_item(conn, item)
                self._write_revision(conn, revision)
                conn.execute(
                    """
                    INSERT INTO memory_import_record (
                        entry_digest, package_id, memory_id, imported_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (entry_digest, package_id, item.id, imported_at),
                )
                saved.append(item)
        return saved, skipped

    def get(self, item_id: str) -> Optional[MemoryItem]:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM memory_item WHERE id = ?", (item_id,)).fetchone()
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
        status: Optional[MemoryStatus] = MemoryStatus.ACTIVE,
    ) -> List[MemoryItem]:
        query = "SELECT * FROM memory_item WHERE (title LIKE ? OR content LIKE ?)"
        params = [f"%{keyword}%", f"%{keyword}%"]
        if status:
            query += " AND status = ?"
            params.append(status.value)
        if memory_type:
            query += " AND memory_type = ?"
            params.append(memory_type.value)
        query += " ORDER BY importance DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_memory_item(r) for r in rows]

    def list_recall_candidates(
        self,
        memory_types: list[MemoryType],
        limit: int = 200,
    ) -> List[MemoryItem]:
        """Return active candidates for the selector's local relevance ranking."""
        unique_types = list(dict.fromkeys(memory_types))
        if not unique_types:
            return []
        placeholders = ", ".join("?" for _ in unique_types)
        query = (
            "SELECT * FROM memory_item "
            f"WHERE status = ? AND memory_type IN ({placeholders}) "
            "ORDER BY importance DESC, updated_at DESC LIMIT ?"
        )
        params = [
            MemoryStatus.ACTIVE.value,
            *(memory_type.value for memory_type in unique_types),
            max(1, min(1000, limit)),
        ]
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_memory_item(row) for row in rows]

    def mark_used(
        self,
        item_ids: list[str],
        used_at: Optional[datetime] = None,
    ) -> int:
        """Record prompt usage without making old content appear newly edited."""
        unique_ids = list(dict.fromkeys(item_id for item_id in item_ids if item_id))
        if not unique_ids:
            return 0
        placeholders = ", ".join("?" for _ in unique_ids)
        timestamp = (used_at or datetime.now()).isoformat()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                f"UPDATE memory_item SET last_used_at = ? WHERE id IN ({placeholders})",
                [timestamp, *unique_ids],
            )
            return cursor.rowcount

    def save_recall_receipts(
        self,
        receipts: list[MemoryRecallReceipt],
    ) -> int:
        """Persist idempotent, content-free evidence for one or more recalls."""
        unique_keys = {(receipt.task_id, receipt.memory_id) for receipt in receipts}
        if len(unique_keys) != len(receipts):
            raise ValueError("Recall receipts must be unique per Task Run and memory")
        if any(receipt.feedback != MemoryRecallFeedback.UNREVIEWED for receipt in receipts):
            raise ValueError("New recall receipts must start unreviewed")
        if not receipts:
            return 0
        inserted = 0
        with self.db.transaction() as conn:
            for receipt in receipts:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO memory_recall_receipt (
                        task_id, session_id, memory_id, memory_type, reason,
                        contributed_chars, memory_updated_at, feedback,
                        selected_at, feedback_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receipt.task_id,
                        receipt.session_id,
                        receipt.memory_id,
                        receipt.memory_type.value,
                        receipt.reason,
                        receipt.contributed_chars,
                        (
                            receipt.memory_updated_at.isoformat()
                            if receipt.memory_updated_at is not None
                            else None
                        ),
                        receipt.feedback.value,
                        receipt.selected_at.isoformat(),
                        (
                            receipt.feedback_at.isoformat()
                            if receipt.feedback_at is not None
                            else None
                        ),
                    ),
                )
                inserted += max(0, cursor.rowcount)
        return inserted

    def list_recall_receipts(self, task_id: str) -> list[MemoryRecallReceipt]:
        """Return one Task Run's content-free recall receipts."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_recall_receipt
                WHERE task_id = ?
                ORDER BY selected_at, memory_id
                """,
                (task_id,),
            ).fetchall()
        return [self._row_to_recall_receipt(row) for row in rows]

    def count_recall_receipts(self, task_id: str) -> int:
        """Return the number of reviewable receipt records for one Task Run."""
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM memory_recall_receipt WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return int(row["count"] if row is not None else 0)

    def record_recall_feedback(
        self,
        task_id: str,
        memory_id: str,
        feedback: MemoryRecallFeedback,
        *,
        revision: MemoryRevision | None = None,
        feedback_at: datetime | None = None,
    ) -> tuple[bool, bool]:
        """Record one final judgment and atomically pause inaccurate active memory."""
        if feedback == MemoryRecallFeedback.UNREVIEWED:
            raise ValueError("Recall feedback must be an explicit judgment")
        if revision is not None:
            if feedback != MemoryRecallFeedback.INACCURATE:
                raise ValueError("Only inaccurate feedback may include a memory revision")
            if revision.memory_id != memory_id:
                raise ValueError("Recall feedback revision must reference the selected memory")
        feedback_time = feedback_at or datetime.now()
        timestamp = feedback_time.isoformat()
        with self.db.transaction() as conn:
            pending = conn.execute(
                """
                SELECT receipt.selected_at, receipt.memory_updated_at,
                       memory.updated_at AS current_memory_updated_at
                FROM memory_recall_receipt AS receipt
                LEFT JOIN memory_item AS memory ON memory.id = receipt.memory_id
                WHERE receipt.task_id = ? AND receipt.memory_id = ?
                  AND receipt.feedback = ?
                """,
                (
                    task_id,
                    memory_id,
                    MemoryRecallFeedback.UNREVIEWED.value,
                ),
            ).fetchone()
            if pending is None:
                return False, False
            if pending["current_memory_updated_at"] is None:
                raise ValueError("Recalled memory no longer exists")
            if (
                pending["memory_updated_at"]
                and pending["memory_updated_at"] != pending["current_memory_updated_at"]
            ):
                raise ValueError("Recalled memory changed after this Task Run")
            if feedback_time < datetime.fromisoformat(pending["selected_at"]):
                raise ValueError("Recall feedback cannot precede memory selection")
            cursor = conn.execute(
                """
                UPDATE memory_recall_receipt
                SET feedback = ?, feedback_at = ?
                WHERE task_id = ? AND memory_id = ? AND feedback = ?
                """,
                (
                    feedback.value,
                    timestamp,
                    task_id,
                    memory_id,
                    MemoryRecallFeedback.UNREVIEWED.value,
                ),
            )
            if cursor.rowcount <= 0:
                return False, False
            paused = False
            if revision is not None:
                changed = conn.execute(
                    """
                    UPDATE memory_item
                    SET status = ?, updated_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        MemoryStatus.NEEDS_REVIEW.value,
                        timestamp,
                        memory_id,
                        MemoryStatus.ACTIVE.value,
                    ),
                )
                self._write_revision(conn, revision)
                paused = changed.rowcount > 0
            return True, paused

    def get_recall_feedback_counts(self, memory_id: str) -> dict[str, int]:
        """Return content-free feedback totals for one memory."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT feedback, COUNT(*) AS count
                FROM memory_recall_receipt
                WHERE memory_id = ?
                GROUP BY feedback
                """,
                (memory_id,),
            ).fetchall()
        counts = {feedback.value: 0 for feedback in MemoryRecallFeedback}
        for row in rows:
            try:
                key = MemoryRecallFeedback(row["feedback"]).value
            except ValueError:
                continue
            counts[key] = int(row["count"])
        counts["total"] = sum(counts.values())
        return counts

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

    def update_status_with_revision(
        self,
        item_id: str,
        status: MemoryStatus,
        revision: MemoryRevision,
    ) -> bool:
        """Atomically update lifecycle status and record why it changed."""
        if revision.memory_id != item_id:
            raise ValueError("Memory revision must reference the updated memory")
        now = datetime.now().isoformat()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE memory_item SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, item_id),
            )
            if cursor.rowcount <= 0:
                return False
            self._write_revision(conn, revision)
            return True

    def update_statuses_with_revisions(
        self,
        updates: list[tuple[str, MemoryStatus]],
        revisions: list[MemoryRevision],
    ) -> bool:
        """Atomically apply related lifecycle decisions and their explanations."""
        memory_ids = {memory_id for memory_id, _status in updates}
        if not memory_ids:
            return False
        if (
            len(revisions) != len(memory_ids)
            or {revision.memory_id for revision in revisions} != memory_ids
        ):
            raise ValueError("Each changed memory must have exactly one revision target")

        placeholders = ", ".join("?" for _memory_id in memory_ids)
        now = datetime.now().isoformat()
        with self.db.transaction() as conn:
            rows = conn.execute(
                f"SELECT id FROM memory_item WHERE id IN ({placeholders})",
                tuple(memory_ids),
            ).fetchall()
            if {row["id"] for row in rows} != memory_ids:
                return False
            for memory_id, status in updates:
                conn.execute(
                    "UPDATE memory_item SET status = ?, updated_at = ? WHERE id = ?",
                    (status.value, now, memory_id),
                )
            for revision in revisions:
                self._write_revision(conn, revision)
        return True

    def delete(self, item_id: str) -> bool:
        with self.db.transaction() as conn:
            cursor = conn.execute("DELETE FROM memory_item WHERE id = ?", (item_id,))
            return cursor.rowcount > 0

    def delete_with_revision(
        self,
        item_id: str,
        revision: MemoryRevision,
    ) -> bool:
        """Permanently remove content while retaining a content-free revision."""
        if revision.memory_id != item_id:
            raise ValueError("Memory revision must reference the forgotten memory")
        with self.db.transaction() as conn:
            exists = conn.execute(
                "SELECT 1 FROM memory_item WHERE id = ?",
                (item_id,),
            ).fetchone()
            if exists is None:
                return False
            self._write_revision(conn, revision)
            cursor = conn.execute("DELETE FROM memory_item WHERE id = ?", (item_id,))
            return cursor.rowcount > 0

    def list_all(
        self,
        status: Optional[MemoryStatus] = None,
        scope: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[MemoryItem]:
        query = "SELECT * FROM memory_item WHERE 1=1"
        params: list = []
        if status:
            query += " AND status = ?"
            params.append(status.value)
        if scope:
            query += " AND scope = ?"
            params.append(scope)
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_memory_item(r) for r in rows]

    def update_content(self, item_id: str, content: str) -> bool:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE memory_item SET content = ?, updated_at = ? WHERE id = ?",
                (content, datetime.now().isoformat(), item_id),
            )
            return cursor.rowcount > 0

    def save_revision(self, revision: MemoryRevision) -> MemoryRevision:
        with self.db.transaction() as conn:
            self._write_revision(conn, revision)
        return revision

    def list_revisions(
        self,
        memory_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[MemoryRevision]:
        query = "SELECT * FROM memory_revision"
        params: list = []
        if memory_id:
            query += " WHERE memory_id = ?"
            params.append(memory_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(1000, limit)))
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_memory_revision(row) for row in rows]

    def count(self, status: Optional[MemoryStatus] = None) -> int:
        query = "SELECT COUNT(*) FROM memory_item WHERE 1=1"
        params: list = []
        if status:
            query += " AND status = ?"
            params.append(status.value)
        with self.db.get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            return row[0] if row else 0

    def list_imported_digests(self) -> set[str]:
        """Return content fingerprints already accepted from portability packages."""
        with self.db.get_connection() as conn:
            rows = conn.execute("SELECT entry_digest FROM memory_import_record").fetchall()
            return {row["entry_digest"] for row in rows}

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
            priority=row["priority"],
            status=MemoryStatus(row["status"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            last_used_at=(
                datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None
            ),
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

    def _init_conflict_tables(self):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS conflict_candidate (
                    id TEXT PRIMARY KEY,
                    existing_item_id TEXT NOT NULL,
                    new_item_id TEXT NOT NULL,
                    conflict_type TEXT NOT NULL DEFAULT 'different_value',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY (existing_item_id) REFERENCES memory_item(id) ON DELETE CASCADE,
                    FOREIGN KEY (new_item_id) REFERENCES memory_item(id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conflict_status
                ON conflict_candidate(status)
                """
            )
            conn.commit()

    def _init_revision_tables(self) -> None:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_revision (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    revision_type TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'system',
                    reason TEXT NOT NULL DEFAULT '',
                    related_memory_id TEXT,
                    previous_content_hash TEXT NOT NULL DEFAULT '',
                    new_content_hash TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_revision_memory
                ON memory_revision(memory_id, created_at DESC)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_revision_created
                ON memory_revision(created_at DESC)
                """
            )
            conn.commit()

    def _init_import_tables(self) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_import_record (
                    entry_digest TEXT PRIMARY KEY,
                    package_id TEXT NOT NULL,
                    memory_id TEXT,
                    imported_at TEXT NOT NULL,
                    FOREIGN KEY (memory_id) REFERENCES memory_item(id) ON DELETE SET NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_import_package
                ON memory_import_record(package_id)
                """
            )
            conn.commit()

    def _init_recall_tables(self) -> None:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_recall_receipt (
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    memory_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    contributed_chars INTEGER NOT NULL DEFAULT 0,
                    memory_updated_at TEXT,
                    feedback TEXT NOT NULL DEFAULT 'unreviewed',
                    selected_at TEXT NOT NULL,
                    feedback_at TEXT,
                    PRIMARY KEY (task_id, memory_id)
                )
                """
            )
            _ensure_column(cursor, "memory_recall_receipt", "memory_updated_at TEXT")
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_recall_memory
                ON memory_recall_receipt(memory_id, selected_at DESC)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_recall_task
                ON memory_recall_receipt(task_id, selected_at)
                """
            )
            conn.commit()

    def save_conflict_candidate(self, candidate: ConflictCandidate) -> ConflictCandidate:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO conflict_candidate (
                    id, existing_item_id, new_item_id, conflict_type, status,
                    created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.id,
                    candidate.existing_item_id,
                    candidate.new_item_id,
                    candidate.conflict_type.value,
                    candidate.status.value,
                    candidate.created_at.isoformat(),
                    candidate.resolved_at.isoformat() if candidate.resolved_at else None,
                ),
            )
        return candidate

    def get_conflict_candidate(self, candidate_id: str) -> Optional[ConflictCandidate]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM conflict_candidate WHERE id = ?", (candidate_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_conflict_candidate(row)

    def list_conflict_candidates(
        self, status: Optional[ConflictStatus] = None
    ) -> List[ConflictCandidate]:
        query = "SELECT * FROM conflict_candidate"
        params: list = []
        if status:
            query += " WHERE status = ?"
            params.append(status.value)
        query += " ORDER BY created_at DESC"
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_conflict_candidate(r) for r in rows]

    def update_conflict_status(
        self,
        candidate_id: str,
        status: ConflictStatus,
    ) -> bool:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE conflict_candidate SET status = ?, resolved_at = ? WHERE id = ?",
                (status.value, datetime.now().isoformat(), candidate_id),
            )
            return cursor.rowcount > 0

    def resolve_conflict_atomic(
        self,
        candidate_id: str,
        accept_new: bool,
        revisions: list[MemoryRevision],
    ) -> Optional[ConflictCandidate]:
        """Resolve both memory statuses, the candidate, and revisions in one transaction."""
        now = datetime.now()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM conflict_candidate WHERE id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                return None
            candidate = self._row_to_conflict_candidate(row)
            if candidate.status != ConflictStatus.PENDING:
                return None
            conflict_memory_ids = {
                candidate.existing_item_id,
                candidate.new_item_id,
            }
            if (
                len(revisions) != len(conflict_memory_ids)
                or {revision.memory_id for revision in revisions}
                != conflict_memory_ids
            ):
                raise ValueError(
                    "Conflict resolution requires one revision for each memory"
                )

            if accept_new:
                status_updates = (
                    (MemoryStatus.DEPRECATED, candidate.existing_item_id),
                    (MemoryStatus.ACTIVE, candidate.new_item_id),
                )
                resolution = ConflictStatus.RESOLVED
            else:
                status_updates = (
                    (MemoryStatus.DEPRECATED, candidate.new_item_id),
                    (MemoryStatus.ACTIVE, candidate.existing_item_id),
                )
                resolution = ConflictStatus.REJECTED

            for status, memory_id in status_updates:
                cursor = conn.execute(
                    "UPDATE memory_item SET status = ?, updated_at = ? WHERE id = ?",
                    (status.value, now.isoformat(), memory_id),
                )
                if cursor.rowcount <= 0:
                    raise ValueError("Conflict references a missing memory item")
            conn.execute(
                """
                UPDATE conflict_candidate
                SET status = ?, resolved_at = ?
                WHERE id = ?
                """,
                (resolution.value, now.isoformat(), candidate_id),
            )
            for revision in revisions:
                self._write_revision(conn, revision)

        candidate.status = resolution
        candidate.resolved_at = now
        return candidate

    @staticmethod
    def _write_memory_item(conn: sqlite3.Connection, item: MemoryItem) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_item (
                id, memory_type, scope, title, content, source,
                source_session_id, source_message_id, confidence, importance,
                priority, status, expires_at, last_used_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                item.priority,
                item.status.value,
                item.expires_at.isoformat() if item.expires_at else None,
                item.last_used_at.isoformat() if item.last_used_at else None,
                item.created_at.isoformat(),
                item.updated_at.isoformat(),
            ),
        )

    @staticmethod
    def _write_revision(
        conn: sqlite3.Connection,
        revision: MemoryRevision,
    ) -> None:
        conn.execute(
            """
            INSERT INTO memory_revision (
                id, memory_id, revision_type, actor, reason,
                related_memory_id, previous_content_hash,
                new_content_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision.id,
                revision.memory_id,
                revision.revision_type.value,
                revision.actor,
                revision.reason,
                revision.related_memory_id,
                revision.previous_content_hash,
                revision.new_content_hash,
                revision.created_at.isoformat(),
            ),
        )

    @staticmethod
    def _row_to_memory_revision(row: sqlite3.Row) -> MemoryRevision:
        return MemoryRevision(
            id=row["id"],
            memory_id=row["memory_id"],
            revision_type=MemoryRevisionType(row["revision_type"]),
            actor=row["actor"],
            reason=row["reason"],
            related_memory_id=row["related_memory_id"],
            previous_content_hash=row["previous_content_hash"],
            new_content_hash=row["new_content_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_recall_receipt(row: sqlite3.Row) -> MemoryRecallReceipt:
        try:
            feedback = MemoryRecallFeedback(row["feedback"])
        except ValueError:
            feedback = MemoryRecallFeedback.UNREVIEWED
        feedback_at = (
            datetime.fromisoformat(row["feedback_at"])
            if row["feedback_at"] and feedback != MemoryRecallFeedback.UNREVIEWED
            else None
        )
        return MemoryRecallReceipt(
            task_id=row["task_id"],
            session_id=row["session_id"],
            memory_id=row["memory_id"],
            memory_type=MemoryType(row["memory_type"]),
            reason=row["reason"],
            contributed_chars=max(0, int(row["contributed_chars"] or 0)),
            memory_updated_at=(
                datetime.fromisoformat(row["memory_updated_at"])
                if row["memory_updated_at"]
                else None
            ),
            feedback=feedback,
            selected_at=datetime.fromisoformat(row["selected_at"]),
            feedback_at=feedback_at,
        )

    @staticmethod
    def _row_to_conflict_candidate(row: sqlite3.Row) -> ConflictCandidate:
        return ConflictCandidate(
            id=row["id"],
            existing_item_id=row["existing_item_id"],
            new_item_id=row["new_item_id"],
            conflict_type=ConflictType(row["conflict_type"]),
            status=ConflictStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
        )
