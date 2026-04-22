"""Task repository for database operations."""

from datetime import datetime
from typing import List, Optional

from core.models.pet import TaskRecord, TaskResult, TaskStatus
from core.storage.db import Database, get_database


class TaskRepository:
    """Repository for task operations."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()

    def create_task(self, task: TaskRecord) -> None:
        """Insert new task record."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO task_record (id, input_text, task_type, status, difficulty, reward_exp, created_at, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    task.id,
                    task.input_text,
                    task.task_type,
                    task.status.value,
                    task.difficulty.value,
                    task.reward_exp,
                    task.created_at.isoformat(),
                    task.started_at.isoformat() if task.started_at else None,
                    task.finished_at.isoformat() if task.finished_at else None,
                ),
            )
            conn.commit()

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Get task by ID."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM task_record WHERE id = ?", (task_id,))
            row = cursor.fetchone()

            if row:
                return self._row_to_task(row)
            return None

    _ALLOWED_UPDATE_FIELDS = {"status", "started_at", "finished_at"}

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> None:
        """Update task status and timestamps."""
        with self.db.transaction() as conn:
            cursor = conn.cursor()

            updates = ["status = ?"]
            params = [status.value, task_id]

            if started_at:
                updates.append("started_at = ?")
                params.insert(-1, started_at.isoformat())

            if finished_at:
                updates.append("finished_at = ?")
                params.insert(-1, finished_at.isoformat())

            # Validate all fields are in whitelist
            for clause in updates:
                field = clause.split(" = ")[0].strip()
                if field not in self._ALLOWED_UPDATE_FIELDS:
                    raise ValueError(f"Invalid update field: {field}")

            query = f"UPDATE task_record SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)

    def get_recent_tasks(self, limit: int = 10) -> List[TaskRecord]:
        """Get recent tasks ordered by creation time."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM task_record
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    def get_pending_tasks(self) -> List[TaskRecord]:
        """Get tasks with status created or queued."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM task_record
                WHERE status IN ('created', 'queued')
                ORDER BY created_at ASC
            """)
            rows = cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    def save_task_result(self, result: TaskResult) -> None:
        """Save task execution result."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO task_result (task_id, success, raw_result, summary, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    success = excluded.success,
                    raw_result = excluded.raw_result,
                    summary = excluded.summary,
                    error_message = excluded.error_message,
                    created_at = excluded.created_at
            """,
                (
                    result.task_id,
                    int(result.success),
                    result.raw_result,
                    result.summary,
                    result.error_message,
                    result.created_at.isoformat(),
                ),
            )
            conn.commit()

    def save_result_and_status(self, result: TaskResult, status: TaskStatus, finished_at: datetime) -> None:
        """Atomically save task result and update status in one transaction."""
        with self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO task_result (task_id, success, raw_result, summary, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    success = excluded.success,
                    raw_result = excluded.raw_result,
                    summary = excluded.summary,
                    error_message = excluded.error_message,
                    created_at = excluded.created_at
            """,
                (
                    result.task_id,
                    int(result.success),
                    result.raw_result,
                    result.summary,
                    result.error_message,
                    result.created_at.isoformat(),
                ),
            )
            cursor.execute(
                "UPDATE task_record SET status = ?, finished_at = ? WHERE id = ?",
                (status.value, finished_at.isoformat(), result.task_id),
            )

    def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get result for a task."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM task_result WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()

            if row:
                return TaskResult(
                    task_id=row["task_id"],
                    success=bool(row["success"]),
                    raw_result=row["raw_result"],
                    summary=row["summary"],
                    error_message=row["error_message"],
                    created_at=row["created_at"],
                )
            return None

    def _row_to_task(self, row) -> TaskRecord:
        """Convert database row to TaskRecord."""
        return TaskRecord(
            id=row["id"],
            input_text=row["input_text"],
            task_type=row["task_type"],
            status=TaskStatus(row["status"]),
            difficulty=row["difficulty"],
            reward_exp=row["reward_exp"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
