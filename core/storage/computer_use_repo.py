"""SQLite persistence for recoverable computer-use plans and checkpoints."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from core.computer_use.models import (
    ComputerAction,
    ComputerActionType,
    ComputerCheckpoint,
    ComputerCheckpointStatus,
    ComputerPlan,
    ComputerPlanStatus,
    ComputerTargetSource,
    utc_now,
)
from core.storage.base_repo import BaseRepository
from core.storage.db import Database


class ComputerUseRepository(BaseRepository):
    """Persist plan/checkpoint metadata without screenshots or typed text."""

    def __init__(self, db: Database | None = None) -> None:
        super().__init__(db)
        self._init_tables()

    def _init_tables(self) -> None:
        with self.db.get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS computer_use_plan (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL DEFAULT '',
                    goal TEXT NOT NULL,
                    target_app TEXT NOT NULL DEFAULT '',
                    allowed_actions_json TEXT NOT NULL,
                    max_actions INTEGER NOT NULL,
                    completed_actions INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    authorized_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_computer_use_plan_session
                    ON computer_use_plan(session_id, updated_at);
                CREATE TABLE IF NOT EXISTS computer_use_checkpoint (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    action_summary TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_summary TEXT NOT NULL DEFAULT '',
                    verification_summary TEXT NOT NULL DEFAULT '',
                    observation_id TEXT NOT NULL DEFAULT '',
                    target_summary TEXT NOT NULL DEFAULT '',
                    target_source TEXT NOT NULL DEFAULT '',
                    expected_outcome TEXT NOT NULL DEFAULT '',
                    verification_attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES computer_use_plan(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_computer_use_checkpoint_plan
                    ON computer_use_checkpoint(plan_id, step_index);
                """
            )
            self._ensure_plan_columns(conn)
            self._ensure_checkpoint_columns(conn)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_computer_use_plan_task
                ON computer_use_plan(task_id, updated_at)
                """
            )
            conn.commit()

    @staticmethod
    def _ensure_plan_columns(conn) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(computer_use_plan)")
        }
        if "task_id" not in columns:
            conn.execute(
                "ALTER TABLE computer_use_plan ADD COLUMN task_id TEXT NOT NULL DEFAULT ''"
            )

    @staticmethod
    def _ensure_checkpoint_columns(conn) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(computer_use_checkpoint)")
        }
        additions = {
            "observation_id": "TEXT NOT NULL DEFAULT ''",
            "target_summary": "TEXT NOT NULL DEFAULT ''",
            "target_source": "TEXT NOT NULL DEFAULT ''",
            "expected_outcome": "TEXT NOT NULL DEFAULT ''",
            "verification_attempts": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE computer_use_checkpoint ADD COLUMN {name} {definition}")

    def create_or_resume_plan(
        self,
        *,
        session_id: str,
        goal: str,
        target_app: str,
        allowed_actions: list[ComputerActionType],
        max_actions: int,
        task_id: str = "",
    ) -> tuple[ComputerPlan, bool]:
        existing = self.find_resumable(session_id, goal, task_id=task_id)
        if existing is not None:
            return existing, True

        now = utc_now()
        plan = ComputerPlan(
            id=str(uuid.uuid4()),
            session_id=session_id,
            task_id=task_id,
            goal=goal,
            target_app=target_app,
            allowed_actions=allowed_actions,
            max_actions=max_actions,
            created_at=now,
            updated_at=now,
        )
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO computer_use_plan (
                    id, session_id, task_id, goal, target_app, allowed_actions_json,
                    max_actions, completed_actions, status, authorized_until,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.id,
                    plan.session_id,
                    plan.task_id,
                    plan.goal,
                    plan.target_app,
                    json.dumps([item.value for item in plan.allowed_actions]),
                    plan.max_actions,
                    plan.completed_actions,
                    plan.status.value,
                    None,
                    plan.created_at.isoformat(),
                    plan.updated_at.isoformat(),
                ),
            )
        return plan, False

    def get_plan(self, plan_id: str) -> ComputerPlan | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM computer_use_plan WHERE id = ?",
                (plan_id,),
            ).fetchone()
        return self._row_to_plan(row) if row else None

    def find_resumable(
        self,
        session_id: str,
        goal: str,
        *,
        task_id: str = "",
    ) -> ComputerPlan | None:
        with self.db.get_connection() as conn:
            if task_id:
                row = conn.execute(
                    """
                    SELECT * FROM computer_use_plan
                    WHERE session_id = ? AND task_id = ? AND goal = ?
                      AND status IN (?, ?, ?)
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (
                        session_id,
                        task_id,
                        goal,
                        ComputerPlanStatus.PENDING_APPROVAL.value,
                        ComputerPlanStatus.ACTIVE.value,
                        ComputerPlanStatus.PAUSED.value,
                    ),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM computer_use_plan
                    WHERE session_id = ? AND task_id = '' AND goal = ?
                      AND status IN (?, ?, ?)
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (
                        session_id,
                        goal,
                        ComputerPlanStatus.PENDING_APPROVAL.value,
                        ComputerPlanStatus.ACTIVE.value,
                        ComputerPlanStatus.PAUSED.value,
                    ),
                ).fetchone()
        return self._row_to_plan(row) if row else None

    def list_session_plans(
        self,
        session_id: str,
        *,
        limit: int = 100,
    ) -> list[ComputerPlan]:
        """List content-minimized plan state for one session."""
        safe_limit = max(1, min(limit, 500))
        raw_session, agent_session = self._session_aliases(session_id)
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM computer_use_plan
                WHERE session_id IN (?, ?)
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (raw_session, agent_session, safe_limit),
            ).fetchall()
        return [self._row_to_plan(row) for row in rows]

    def list_task_plans(
        self,
        task_id: str,
        *,
        limit: int = 100,
    ) -> list[ComputerPlan]:
        safe_limit = max(1, min(limit, 500))
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM computer_use_plan
                WHERE task_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (task_id, safe_limit),
            ).fetchall()
        return [self._row_to_plan(row) for row in rows]

    def revoke_authorizations(self, session_id: str) -> int:
        """Pause active plans and remove grants without deleting checkpoints."""
        raw_session, agent_session = self._session_aliases(session_id)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE computer_use_plan
                SET status = ?, authorized_until = NULL, updated_at = ?
                WHERE session_id IN (?, ?) AND status = ?
                """,
                (
                    ComputerPlanStatus.PAUSED.value,
                    utc_now().isoformat(),
                    raw_session,
                    agent_session,
                    ComputerPlanStatus.ACTIVE.value,
                ),
            )
            return max(0, cursor.rowcount)

    def revoke_task_authorizations(self, task_id: str) -> int:
        """Revoke grants owned by one Task Run without deleting its evidence."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE computer_use_plan
                SET status = ?, authorized_until = NULL, updated_at = ?
                WHERE task_id = ? AND status = ?
                """,
                (
                    ComputerPlanStatus.PAUSED.value,
                    utc_now().isoformat(),
                    task_id,
                    ComputerPlanStatus.ACTIVE.value,
                ),
            )
            return max(0, cursor.rowcount)

    def revoke_all_authorizations(self) -> int:
        """Process restarts invalidate every in-memory desktop execution grant."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE computer_use_plan
                SET status = ?, authorized_until = NULL, updated_at = ?
                WHERE status = ?
                """,
                (
                    ComputerPlanStatus.PAUSED.value,
                    utc_now().isoformat(),
                    ComputerPlanStatus.ACTIVE.value,
                ),
            )
            return max(0, cursor.rowcount)

    @staticmethod
    def _session_aliases(session_id: str) -> tuple[str, str]:
        raw = session_id.removeprefix("lobuddy:session:")
        return raw, f"lobuddy:session:{raw}"

    def authorize(self, plan_id: str, authorized_until: datetime) -> ComputerPlan:
        self._update_plan(
            plan_id,
            status=ComputerPlanStatus.ACTIVE,
            authorized_until=authorized_until,
        )
        return self._require_plan(plan_id)

    def pause(self, plan_id: str) -> ComputerPlan:
        self._update_plan(
            plan_id,
            status=ComputerPlanStatus.PAUSED,
            authorized_until=None,
        )
        return self._require_plan(plan_id)

    def finish(self, plan_id: str, success: bool) -> ComputerPlan:
        self._update_plan(
            plan_id,
            status=(ComputerPlanStatus.COMPLETED if success else ComputerPlanStatus.FAILED),
            authorized_until=None,
        )
        return self._require_plan(plan_id)

    def record_action(
        self,
        plan: ComputerPlan,
        action: ComputerAction,
        *,
        success: bool,
        result_summary: str,
        target_source: ComputerTargetSource | None = None,
        target_summary: str = "",
    ) -> str:
        checkpoint_id = str(uuid.uuid4())
        now = utc_now().isoformat()
        status = (
            ComputerCheckpointStatus.ACTION_COMPLETED
            if success
            else ComputerCheckpointStatus.ACTION_FAILED
        )
        next_step = plan.completed_actions + 1
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO computer_use_checkpoint (
                    id, plan_id, step_index, action_type, action_summary,
                    status, result_summary, verification_summary,
                    observation_id, target_summary, target_source, expected_outcome,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    plan.id,
                    next_step,
                    action.action.value,
                    action.audit_summary(),
                    status.value,
                    result_summary[:500],
                    action.observation_id,
                    (target_summary or action.target_summary())[:300],
                    target_source.value if target_source is not None else "",
                    action.expected_outcome[:500],
                    now,
                    now,
                ),
            )
            if success:
                conn.execute(
                    """
                    UPDATE computer_use_plan
                    SET completed_actions = completed_actions + 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, plan.id),
                )
        return checkpoint_id

    def record_verification(
        self,
        plan_id: str,
        checkpoint_id: str,
        *,
        verified: bool,
        summary: str,
    ) -> int:
        status = (
            ComputerCheckpointStatus.VERIFIED
            if verified
            else ComputerCheckpointStatus.VERIFICATION_FAILED
        )
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE computer_use_checkpoint
                SET status = ?, verification_summary = ?,
                    verification_attempts = verification_attempts + 1,
                    updated_at = ?
                WHERE id = ? AND plan_id = ?
                """,
                (
                    status.value,
                    summary[:500],
                    utc_now().isoformat(),
                    checkpoint_id,
                    plan_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("Checkpoint does not belong to this plan")
            row = conn.execute(
                """
                SELECT verification_attempts FROM computer_use_checkpoint
                WHERE id = ? AND plan_id = ?
                """,
                (checkpoint_id, plan_id),
            ).fetchone()
            return int(row["verification_attempts"])

    def latest_checkpoint(self, plan_id: str) -> dict | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM computer_use_checkpoint
                WHERE plan_id = ?
                ORDER BY step_index DESC, created_at DESC, rowid DESC
                LIMIT 1
                """,
                (plan_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_checkpoint(
        self,
        plan_id: str,
        checkpoint_id: str,
    ) -> ComputerCheckpoint | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM computer_use_checkpoint
                WHERE id = ? AND plan_id = ?
                """,
                (checkpoint_id, plan_id),
            ).fetchone()
        return self._row_to_checkpoint(row) if row else None

    def latest_checkpoint_model(self, plan_id: str) -> ComputerCheckpoint | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM computer_use_checkpoint
                WHERE plan_id = ?
                ORDER BY step_index DESC, created_at DESC, rowid DESC
                LIMIT 1
                """,
                (plan_id,),
            ).fetchone()
        return self._row_to_checkpoint(row) if row else None

    def list_checkpoints(self, plan_id: str) -> list[dict]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM computer_use_checkpoint
                WHERE plan_id = ?
                ORDER BY step_index, created_at, rowid
                """,
                (plan_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_checkpoint_models(self, plan_id: str) -> list[ComputerCheckpoint]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM computer_use_checkpoint
                WHERE plan_id = ?
                ORDER BY step_index, created_at, rowid
                """,
                (plan_id,),
            ).fetchall()
        return [self._row_to_checkpoint(row) for row in rows]

    def _update_plan(
        self,
        plan_id: str,
        *,
        status: ComputerPlanStatus,
        authorized_until: datetime | None,
    ) -> None:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE computer_use_plan
                SET status = ?, authorized_until = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    authorized_until.isoformat() if authorized_until else None,
                    utc_now().isoformat(),
                    plan_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("Computer-use plan not found")

    def _require_plan(self, plan_id: str) -> ComputerPlan:
        plan = self.get_plan(plan_id)
        if plan is None:
            raise ValueError("Computer-use plan not found")
        return plan

    @staticmethod
    def _row_to_plan(row) -> ComputerPlan:
        return ComputerPlan(
            id=row["id"],
            session_id=row["session_id"],
            task_id=row["task_id"] if "task_id" in row.keys() else "",
            goal=row["goal"],
            target_app=row["target_app"],
            allowed_actions=json.loads(row["allowed_actions_json"]),
            max_actions=row["max_actions"],
            completed_actions=row["completed_actions"],
            status=row["status"],
            authorized_until=(
                datetime.fromisoformat(row["authorized_until"]) if row["authorized_until"] else None
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_checkpoint(row) -> ComputerCheckpoint:
        source = row["target_source"] if "target_source" in row.keys() else ""
        return ComputerCheckpoint(
            id=row["id"],
            plan_id=row["plan_id"],
            step_index=row["step_index"],
            action_type=row["action_type"],
            action_summary=row["action_summary"],
            observation_id=(row["observation_id"] if "observation_id" in row.keys() else ""),
            target_summary=(row["target_summary"] if "target_summary" in row.keys() else ""),
            target_source=source or None,
            expected_outcome=(row["expected_outcome"] if "expected_outcome" in row.keys() else ""),
            status=row["status"],
            result_summary=row["result_summary"],
            verification_summary=row["verification_summary"],
            verification_attempts=(
                row["verification_attempts"] if "verification_attempts" in row.keys() else 0
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
