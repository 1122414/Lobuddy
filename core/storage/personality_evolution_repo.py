"""Atomic persistence for append-only Personality Evolution revisions."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime

from core.models.personality import PetPersonality, PersonalityDimension
from core.personality.evolution_models import (
    PersonalityEvolutionKind,
    PersonalityEvolutionRevision,
)
from core.storage.base_repo import BaseRepository
from core.storage.db import Database


class PersonalityEvolutionConflict(RuntimeError):
    """The pet changed after an evolution decision was prepared."""


class PersonalityEvolutionRepository(BaseRepository):
    """Keep personality state and its append-only evidence in one transaction."""

    def __init__(self, db: Database | None = None) -> None:
        super().__init__(db)
        self._init_table()

    def _init_table(self) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS personality_evolution_revision (
                    id TEXT PRIMARY KEY,
                    pet_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    task_id TEXT,
                    reason TEXT NOT NULL DEFAULT '',
                    adjustments_json TEXT NOT NULL DEFAULT '{}',
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    restored_from_revision_id TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (pet_id) REFERENCES pet_state(id) ON DELETE CASCADE,
                    FOREIGN KEY (restored_from_revision_id)
                        REFERENCES personality_evolution_revision(id),
                    UNIQUE (pet_id, sequence)
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_personality_evolution_task
                ON personality_evolution_revision(pet_id, task_id)
                WHERE kind = 'task_completed' AND task_id IS NOT NULL
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_personality_evolution_created
                ON personality_evolution_revision(pet_id, sequence DESC)
                """
            )
            conn.commit()

    def ensure_baseline(
        self,
        pet_id: str,
        personality: PetPersonality,
    ) -> PersonalityEvolutionRevision:
        """Create one migration baseline without changing personality state."""
        with self.db.transaction() as conn:
            current = self._load_pet_personality(conn, pet_id)
            existing = self._first_revision(conn, pet_id)
            if existing is not None:
                return self._row_to_revision(existing)
            if current.model_dump() != personality.model_dump():
                personality = current
            return self._insert_baseline(conn, pet_id, personality, datetime.now())

    def apply_task_evolution(
        self,
        *,
        pet_id: str,
        task_id: str,
        expected_before: PetPersonality,
        after: PetPersonality,
        adjustments: dict[str, float],
        reason: str,
    ) -> tuple[PersonalityEvolutionRevision, bool]:
        """Atomically update current state and append one idempotent task revision."""
        if not task_id:
            raise ValueError("Personality Evolution requires a task id")
        now = datetime.now()
        with self.db.transaction() as conn:
            existing = conn.execute(
                """
                SELECT * FROM personality_evolution_revision
                WHERE pet_id = ? AND task_id = ? AND kind = ?
                LIMIT 1
                """,
                (pet_id, task_id, PersonalityEvolutionKind.TASK_COMPLETED.value),
            ).fetchone()
            if existing is not None:
                return self._row_to_revision(existing), False

            current = self._load_pet_personality(conn, pet_id)
            if current.model_dump() != expected_before.model_dump():
                raise PersonalityEvolutionConflict(
                    "Pet personality changed before the evolution could be recorded"
                )
            self._ensure_baseline_in_transaction(conn, pet_id, current, now)
            revision = PersonalityEvolutionRevision(
                id=str(uuid.uuid4()),
                pet_id=pet_id,
                sequence=self._next_sequence(conn, pet_id),
                kind=PersonalityEvolutionKind.TASK_COMPLETED,
                actor="task",
                task_id=task_id,
                reason=reason,
                adjustments=adjustments,
                before=current,
                after=after,
                created_at=now,
            )
            self._update_current_personality(conn, pet_id, after, now)
            self._insert_revision(conn, revision)
            return revision, True

    def restore(
        self,
        *,
        pet_id: str,
        target_revision_id: str,
        reason: str,
    ) -> tuple[PersonalityEvolutionRevision, bool]:
        """Restore a historical result by appending a new revision."""
        now = datetime.now()
        with self.db.transaction() as conn:
            target_row = conn.execute(
                """
                SELECT * FROM personality_evolution_revision
                WHERE id = ? AND pet_id = ?
                """,
                (target_revision_id, pet_id),
            ).fetchone()
            if target_row is None:
                raise ValueError("Personality Evolution version not found")
            target = self._row_to_revision(target_row)
            current = self._load_pet_personality(conn, pet_id)
            if current.model_dump() == target.after.model_dump():
                return target, False

            self._ensure_baseline_in_transaction(conn, pet_id, current, now)
            adjustments = {
                dimension.value: round(
                    float(getattr(target.after, dimension.value))
                    - float(getattr(current, dimension.value)),
                    4,
                )
                for dimension in PersonalityDimension
                if getattr(target.after, dimension.value) != getattr(current, dimension.value)
            }
            revision = PersonalityEvolutionRevision(
                id=str(uuid.uuid4()),
                pet_id=pet_id,
                sequence=self._next_sequence(conn, pet_id),
                kind=PersonalityEvolutionKind.RESTORED,
                actor="user",
                reason=reason,
                adjustments=adjustments,
                before=current,
                after=target.after.model_copy(deep=True),
                restored_from_revision_id=target.id,
                created_at=now,
            )
            self._update_current_personality(conn, pet_id, revision.after, now)
            self._insert_revision(conn, revision)
            return revision, True

    def get(self, revision_id: str) -> PersonalityEvolutionRevision | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM personality_evolution_revision WHERE id = ?",
                (revision_id,),
            ).fetchone()
        return self._row_to_revision(row) if row is not None else None

    def list_revisions(
        self,
        pet_id: str = "default",
        *,
        limit: int = 100,
    ) -> list[PersonalityEvolutionRevision]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM personality_evolution_revision
                WHERE pet_id = ?
                ORDER BY sequence DESC
                LIMIT ?
                """,
                (pet_id, max(1, min(1000, limit))),
            ).fetchall()
        return [self._row_to_revision(row) for row in rows]

    def count(self, pet_id: str = "default") -> int:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM personality_evolution_revision
                WHERE pet_id = ?
                """,
                (pet_id,),
            ).fetchone()
        return int(row["total"]) if row is not None else 0

    def _ensure_baseline_in_transaction(
        self,
        conn: sqlite3.Connection,
        pet_id: str,
        personality: PetPersonality,
        now: datetime,
    ) -> PersonalityEvolutionRevision | None:
        existing = self._first_revision(conn, pet_id)
        if existing is not None:
            return None
        return self._insert_baseline(conn, pet_id, personality, now)

    def _insert_baseline(
        self,
        conn: sqlite3.Connection,
        pet_id: str,
        personality: PetPersonality,
        now: datetime,
    ) -> PersonalityEvolutionRevision:
        revision = PersonalityEvolutionRevision(
            id=str(uuid.uuid4()),
            pet_id=pet_id,
            sequence=1,
            kind=PersonalityEvolutionKind.BASELINE,
            actor="system",
            reason="成长版本历史从当前状态开始",
            before=personality.model_copy(deep=True),
            after=personality.model_copy(deep=True),
            created_at=now,
        )
        self._insert_revision(conn, revision)
        return revision

    @staticmethod
    def _first_revision(
        conn: sqlite3.Connection,
        pet_id: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT * FROM personality_evolution_revision
            WHERE pet_id = ?
            ORDER BY sequence ASC
            LIMIT 1
            """,
            (pet_id,),
        ).fetchone()

    @staticmethod
    def _next_sequence(conn: sqlite3.Connection, pet_id: str) -> int:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
            FROM personality_evolution_revision
            WHERE pet_id = ?
            """,
            (pet_id,),
        ).fetchone()
        return int(row["next_sequence"])

    @staticmethod
    def _load_pet_personality(
        conn: sqlite3.Connection,
        pet_id: str,
    ) -> PetPersonality:
        row = conn.execute(
            "SELECT personality_json FROM pet_state WHERE id = ?",
            (pet_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Pet not found")
        value = row["personality_json"]
        return PetPersonality.model_validate_json(value) if value else PetPersonality()

    @staticmethod
    def _update_current_personality(
        conn: sqlite3.Connection,
        pet_id: str,
        personality: PetPersonality,
        now: datetime,
    ) -> None:
        cursor = conn.execute(
            """
            UPDATE pet_state
            SET personality_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (personality.model_dump_json(), now.isoformat(), pet_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Pet not found")

    @staticmethod
    def _insert_revision(
        conn: sqlite3.Connection,
        revision: PersonalityEvolutionRevision,
    ) -> None:
        conn.execute(
            """
            INSERT INTO personality_evolution_revision (
                id, pet_id, sequence, kind, actor, task_id, reason,
                adjustments_json, before_json, after_json,
                restored_from_revision_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision.id,
                revision.pet_id,
                revision.sequence,
                revision.kind.value,
                revision.actor,
                revision.task_id,
                revision.reason,
                json.dumps(revision.adjustments, ensure_ascii=False, sort_keys=True),
                revision.before.model_dump_json(),
                revision.after.model_dump_json(),
                revision.restored_from_revision_id,
                revision.created_at.isoformat(),
            ),
        )

    @staticmethod
    def _row_to_revision(row: sqlite3.Row) -> PersonalityEvolutionRevision:
        return PersonalityEvolutionRevision(
            id=row["id"],
            pet_id=row["pet_id"],
            sequence=int(row["sequence"]),
            kind=PersonalityEvolutionKind(row["kind"]),
            actor=row["actor"],
            task_id=row["task_id"],
            reason=row["reason"],
            adjustments=json.loads(row["adjustments_json"] or "{}"),
            before=PetPersonality.model_validate_json(row["before_json"]),
            after=PetPersonality.model_validate_json(row["after_json"]),
            restored_from_revision_id=row["restored_from_revision_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
