"""Persistence for rate-limited interventions and explicit user feedback."""

from datetime import datetime, timedelta
from typing import Optional

from core.companion.models import (
    CompanionCheckIn,
    CompanionEnergy,
    CompanionFeedbackAction,
    CompanionMood,
    CompanionPreferenceSummary,
    CompanionSupportMode,
    InterventionKind,
)
from core.storage.base_repo import BaseRepository
from core.storage.db import Database


class CompanionEventRepository(BaseRepository):
    """Store intervention metadata without observation content."""

    def __init__(self, db: Optional[Database] = None) -> None:
        super().__init__(db)
        self._init_table()

    def _init_table(self) -> None:
        with self.db.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS companion_intervention (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_companion_intervention_created
                ON companion_intervention(created_at)
                """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS companion_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intervention_id INTEGER NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(intervention_id)
                        REFERENCES companion_intervention(id) ON DELETE CASCADE
                )
                """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_companion_feedback_kind_action
                ON companion_feedback(kind, action, created_at)
                """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS companion_checkin (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mood TEXT NOT NULL,
                    energy TEXT NOT NULL,
                    support_mode TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """)
            conn.commit()

    def record(self, kind: InterventionKind, created_at: datetime) -> int:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO companion_intervention (kind, created_at) VALUES (?, ?)",
                (kind.value, created_at.isoformat()),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create companion intervention")
            return int(cursor.lastrowid)

    def count_since(
        self,
        since: datetime,
        kind: InterventionKind | None = None,
    ) -> int:
        query = "SELECT COUNT(*) FROM companion_intervention WHERE created_at >= ?"
        params: list[object] = [since.isoformat()]
        if kind is not None:
            query += " AND kind = ?"
            params.append(kind.value)
        with self.db.get_connection() as conn:
            return int(conn.execute(query, params).fetchone()[0])

    def last_at(self, kind: InterventionKind | None = None) -> datetime | None:
        query = "SELECT created_at FROM companion_intervention"
        params: tuple[object, ...] = ()
        if kind is not None:
            query += " WHERE kind = ?"
            params = (kind.value,)
        query += " ORDER BY created_at DESC LIMIT 1"
        with self.db.get_connection() as conn:
            row = conn.execute(query, params).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def record_feedback(
        self,
        intervention_id: int,
        action: CompanionFeedbackAction,
        created_at: datetime,
    ) -> InterventionKind | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT kind FROM companion_intervention WHERE id = ?",
                (intervention_id,),
            ).fetchone()
            if row is None:
                return None
            kind = InterventionKind(row["kind"])
            conn.execute(
                """
                INSERT INTO companion_feedback (
                    intervention_id, kind, action, created_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(intervention_id) DO UPDATE SET
                    action = excluded.action,
                    created_at = excluded.created_at
                """,
                (intervention_id, kind.value, action.value, created_at.isoformat()),
            )
        return kind

    def is_kind_muted(self, kind: InterventionKind) -> bool:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM companion_feedback
                WHERE kind = ? AND action = ?
                LIMIT 1
                """,
                (kind.value, CompanionFeedbackAction.MUTE_KIND.value),
            ).fetchone()
        return row is not None

    def snoozed_until(self, snooze_minutes: int) -> datetime | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT created_at FROM companion_feedback
                WHERE action = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (CompanionFeedbackAction.LATER.value,),
            ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["created_at"]) + timedelta(minutes=snooze_minutes)

    def get_feedback_summary(self, snooze_minutes: int) -> CompanionPreferenceSummary:
        with self.db.get_connection() as conn:
            counts = {
                row["action"]: int(row["total"])
                for row in conn.execute(
                    """
                    SELECT action, COUNT(*) AS total
                    FROM companion_feedback
                    GROUP BY action
                    """
                )
            }
            muted_kinds = [
                InterventionKind(row["kind"])
                for row in conn.execute(
                    """
                    SELECT DISTINCT kind FROM companion_feedback
                    WHERE action = ?
                    ORDER BY kind
                    """,
                    (CompanionFeedbackAction.MUTE_KIND.value,),
                )
            ]
        return CompanionPreferenceSummary(
            helpful_count=counts.get(CompanionFeedbackAction.HELPFUL.value, 0),
            later_count=counts.get(CompanionFeedbackAction.LATER.value, 0),
            muted_kinds=muted_kinds,
            snoozed_until=self.snoozed_until(snooze_minutes),
        )

    def clear_feedback_preferences(self) -> int:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM companion_feedback WHERE action IN (?, ?)",
                (
                    CompanionFeedbackAction.LATER.value,
                    CompanionFeedbackAction.MUTE_KIND.value,
                ),
            )
            return max(0, int(cursor.rowcount))

    def save_check_in(self, check_in: CompanionCheckIn) -> CompanionCheckIn:
        """Replace prior state so the database never becomes a mood history."""
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM companion_checkin")
            cursor = conn.execute(
                """
                INSERT INTO companion_checkin (
                    mood, energy, support_mode, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    check_in.mood.value,
                    check_in.energy.value,
                    check_in.support_mode.value,
                    check_in.created_at.isoformat(),
                    check_in.expires_at.isoformat(),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create Companion Check-in")
            check_in_id = int(cursor.lastrowid)
        return check_in.model_copy(update={"id": check_in_id})

    def active_check_in(self, now: datetime) -> CompanionCheckIn | None:
        """Return the current state and eagerly remove expired data."""
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM companion_checkin WHERE expires_at <= ?",
                (now.isoformat(),),
            )
            row = conn.execute(
                """
                SELECT id, mood, energy, support_mode, created_at, expires_at
                FROM companion_checkin
                WHERE created_at <= ? AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (now.isoformat(), now.isoformat()),
            ).fetchone()
        if row is None:
            return None
        return CompanionCheckIn(
            id=int(row["id"]),
            mood=CompanionMood(row["mood"]),
            energy=CompanionEnergy(row["energy"]),
            support_mode=CompanionSupportMode(row["support_mode"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
        )

    def clear_check_in(self) -> int:
        with self.db.transaction() as conn:
            cursor = conn.execute("DELETE FROM companion_checkin")
            return max(0, int(cursor.rowcount))
