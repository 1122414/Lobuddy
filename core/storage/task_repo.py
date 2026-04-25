from datetime import datetime
from typing import List, Optional

from core.models.pet import TaskRecord, TaskResult, TaskStatus
from core.storage.base_repo import BaseRepository, _parse_iso


class TaskRepository(BaseRepository):
    def create_task(self, task: TaskRecord) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO task_record (id, input_text, task_type, status, difficulty, reward_exp, created_at, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id, task.input_text, task.task_type,
                    task.status.value, task.difficulty.value, task.reward_exp,
                    task.created_at.isoformat(),
                    task.started_at.isoformat() if task.started_at else None,
                    task.finished_at.isoformat() if task.finished_at else None,
                ),
            )
            conn.commit()

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM task_record WHERE id = ?", (task_id,)).fetchone()
            if row:
                return self._row_to_task(row)
            return None

    _ALLOWED_UPDATE_FIELDS = {"status", "started_at", "finished_at"}

    def update_task_status(
        self, task_id: str, status: TaskStatus,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> None:
        with self.db.transaction() as conn:
            updates = ["status = ?"]
            params = [status.value, task_id]

            if started_at:
                updates.append("started_at = ?")
                params.insert(-1, started_at.isoformat())
            if finished_at:
                updates.append("finished_at = ?")
                params.insert(-1, finished_at.isoformat())

            for clause in updates:
                field = clause.split(" = ")[0].strip()
                if field not in self._ALLOWED_UPDATE_FIELDS:
                    raise ValueError(f"Invalid update field: {field}")

            conn.execute(
                f"UPDATE task_record SET {', '.join(updates)} WHERE id = ?",
                params,
            )

    def get_recent_tasks(self, limit: int = 10) -> List[TaskRecord]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM task_record ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_task(row) for row in rows]

    def get_pending_tasks(self) -> List[TaskRecord]:
        with self.db.get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM task_record
                WHERE status IN ('created', 'queued')
                ORDER BY created_at ASC
            """).fetchall()
            return [self._row_to_task(row) for row in rows]

    def _upsert_task_result(self, conn, result: TaskResult) -> None:
        conn.execute(
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
                result.task_id, int(result.success), result.raw_result,
                result.summary, result.error_message, result.created_at.isoformat(),
            ),
        )

    def save_task_result(self, result: TaskResult) -> None:
        with self.db.get_connection() as conn:
            self._upsert_task_result(conn, result)
            conn.commit()

    def save_result_and_status(
        self, result: TaskResult, status: TaskStatus, finished_at: datetime
    ) -> None:
        with self.db.transaction() as conn:
            self._upsert_task_result(conn, result)
            conn.execute(
                "UPDATE task_record SET status = ?, finished_at = ? WHERE id = ?",
                (status.value, finished_at.isoformat(), result.task_id),
            )

    def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM task_result WHERE task_id = ?", (task_id,)).fetchone()
            if row:
                return TaskResult(
                    task_id=row["task_id"],
                    success=bool(row["success"]),
                    raw_result=row["raw_result"],
                    summary=row["summary"],
                    error_message=row["error_message"],
                    created_at=_parse_iso(row["created_at"]),
                )
            return None

    def _row_to_task(self, row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            input_text=row["input_text"],
            task_type=row["task_type"],
            status=TaskStatus(row["status"]),
            difficulty=row["difficulty"],
            reward_exp=row["reward_exp"],
            created_at=_parse_iso(row["created_at"]),
            started_at=_parse_iso(row["started_at"]) if row["started_at"] else None,
            finished_at=_parse_iso(row["finished_at"]) if row["finished_at"] else None,
        )
