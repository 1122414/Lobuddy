import json
from datetime import datetime
from typing import List, Optional

from core.models.model_usage import ModelUsageEvidence, ModelUsageSource
from core.models.pet import TaskRecord, TaskResult, TaskStatus
from core.models.task_run import (
    RunUpdate,
    RunUpdateKind,
    RunUpdateStatus,
    TaskRunOutcomeEvidence,
)
from core.storage.base_repo import BaseRepository, _parse_iso
from core.storage.db import Database, _ensure_column


class TaskRepository(BaseRepository):
    def __init__(self, db: Optional[Database] = None):
        super().__init__(db)
        self._init_task_run_schema()

    def _init_task_run_schema(self) -> None:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            _ensure_column(
                cursor,
                "task_record",
                "session_id TEXT NOT NULL DEFAULT ''",
            )
            _ensure_column(
                cursor,
                "task_record",
                "estimated_duration_seconds INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                cursor,
                "task_record",
                "estimated_token_usage INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                cursor,
                "task_record",
                "attempt_no INTEGER NOT NULL DEFAULT 1",
            )
            _ensure_column(cursor, "task_record", "parent_task_id TEXT")
            _ensure_column(
                cursor,
                "task_record",
                "has_image INTEGER NOT NULL DEFAULT 0",
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_run_update (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    update_key TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    stage_family TEXT NOT NULL DEFAULT '',
                    depends_on_json TEXT NOT NULL DEFAULT '[]',
                    estimated_duration_seconds INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES task_record(id) ON DELETE CASCADE
                )
                """,
            )
            _ensure_column(
                cursor,
                "task_run_update",
                "stage_family TEXT NOT NULL DEFAULT ''",
            )
            _ensure_column(
                cursor,
                "task_run_update",
                "depends_on_json TEXT NOT NULL DEFAULT '[]'",
            )
            _ensure_column(
                cursor,
                "task_run_update",
                "estimated_duration_seconds INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                cursor,
                "task_run_update",
                "duration_ms INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(cursor, "task_result", "model_name TEXT NOT NULL DEFAULT ''")
            _ensure_column(
                cursor,
                "task_result",
                "prompt_tokens INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                cursor,
                "task_result",
                "completion_tokens INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                cursor,
                "task_result",
                "cached_tokens INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                cursor,
                "task_result",
                "usage_source TEXT NOT NULL DEFAULT 'unavailable'",
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_task_run_update_task
                ON task_run_update(task_id, created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_task_parent
                ON task_record(parent_task_id)
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_task_single_retry
                ON task_record(parent_task_id)
                WHERE parent_task_id IS NOT NULL
                """
            )
            conn.commit()

    def create_task(
        self,
        task: TaskRecord,
        update: Optional[RunUpdate] = None,
    ) -> None:
        if update is not None and update.task_id != task.id:
            raise ValueError("Run Update must reference the created Task Run")
        with self.db.transaction() as conn:
            self._insert_task(conn, task)
            if update is not None:
                self._insert_run_update(conn, update)

    def create_retry(
        self,
        previous_update: RunUpdate,
        new_task: TaskRecord,
        queued_update: RunUpdate,
    ) -> None:
        """Atomically link an old attempt to a newly queued Task Run."""
        if queued_update.task_id != new_task.id:
            raise ValueError("Queued update must reference the retry Task Run")
        if previous_update.task_id != new_task.parent_task_id:
            raise ValueError("Retry lineage must reference the previous Task Run")
        with self.db.transaction() as conn:
            previous = conn.execute(
                "SELECT 1 FROM task_record WHERE id = ?",
                (previous_update.task_id,),
            ).fetchone()
            if previous is None:
                raise ValueError("Previous Task Run does not exist")
            self._insert_run_update(conn, previous_update)
            self._insert_task(conn, new_task)
            self._insert_run_update(conn, queued_update)

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM task_record WHERE id = ?", (task_id,)).fetchone()
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
        update: Optional[RunUpdate] = None,
    ) -> bool:
        if update is not None and update.task_id != task_id:
            raise ValueError("Run Update must reference the changed Task Run")
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

            cursor = conn.execute(
                f"UPDATE task_record SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            if cursor.rowcount <= 0:
                return False
            if update is not None:
                self._insert_run_update(conn, update)
            return True

    def get_recent_tasks(self, limit: int = 10) -> List[TaskRecord]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM task_record ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_task(row) for row in rows]

    def get_pending_tasks(self) -> List[TaskRecord]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_record
                WHERE status IN ('created', 'queued')
                ORDER BY created_at ASC
                """
            ).fetchall()
            return [self._row_to_task(row) for row in rows]

    def get_retry_for_parent(self, task_id: str) -> Optional[TaskRecord]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM task_record
                WHERE parent_task_id = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        return self._row_to_task(row) if row else None

    def get_incomplete_tasks(self) -> List[TaskRecord]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_record
                WHERE status IN ('created', 'queued', 'running')
                ORDER BY created_at ASC
                """
            ).fetchall()
            return [self._row_to_task(row) for row in rows]

    def get_completed_durations(
        self,
        difficulty: str,
        limit: int = 20,
    ) -> list[int]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT started_at, finished_at
                FROM task_record
                WHERE difficulty = ?
                  AND status = 'success'
                  AND started_at IS NOT NULL
                  AND finished_at IS NOT NULL
                ORDER BY finished_at DESC
                LIMIT ?
                """,
                (difficulty, limit),
            ).fetchall()
        durations: list[int] = []
        for row in rows:
            started_at = _parse_iso(row["started_at"])
            finished_at = _parse_iso(row["finished_at"])
            duration = int((finished_at - started_at).total_seconds())
            if duration > 0:
                durations.append(duration)
        return durations

    def get_completed_stage_durations(
        self,
        stage_family: str,
        limit: int = 20,
    ) -> list[int]:
        """Return recent successful measured durations for one Work Stage family."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT duration_ms
                FROM task_run_update
                WHERE stage_family = ?
                  AND status = ?
                  AND duration_ms > 0
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (
                    stage_family,
                    RunUpdateStatus.SUCCESS.value,
                    max(1, min(100, limit)),
                ),
            ).fetchall()
        return [int(row["duration_ms"]) for row in rows]

    def get_completed_token_usage(
        self,
        difficulty: str,
        provider_model: str,
        limit: int = 20,
    ) -> list[int]:
        """Return comparable per-Task Run usage without prompts or responses."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT r.prompt_tokens, r.completion_tokens
                FROM task_result AS r
                JOIN task_record AS t ON t.id = r.task_id
                WHERE t.difficulty = ?
                  AND r.model_name = ?
                  AND t.status = 'success'
                  AND r.usage_source IN ('provider', 'local_estimate')
                  AND r.prompt_tokens >= 0
                  AND r.completion_tokens >= 0
                  AND r.cached_tokens BETWEEN 0 AND r.prompt_tokens
                  AND (r.prompt_tokens + r.completion_tokens) > 0
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (difficulty, provider_model, max(1, min(100, limit))),
            ).fetchall()
        return [int(row["prompt_tokens"]) + int(row["completion_tokens"]) for row in rows]

    @staticmethod
    def _upsert_task_result(conn, result: TaskResult) -> None:
        conn.execute(
            """
            INSERT INTO task_result (
                task_id, success, raw_result, summary, error_message,
                model_name, prompt_tokens, completion_tokens, cached_tokens,
                usage_source, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                success = excluded.success,
                raw_result = excluded.raw_result,
                summary = excluded.summary,
                error_message = excluded.error_message,
                model_name = excluded.model_name,
                prompt_tokens = excluded.prompt_tokens,
                completion_tokens = excluded.completion_tokens,
                cached_tokens = excluded.cached_tokens,
                usage_source = excluded.usage_source,
                created_at = excluded.created_at
            """,
            (
                result.task_id,
                int(result.success),
                result.raw_result,
                result.summary,
                result.error_message,
                result.usage_evidence.provider_model,
                result.usage_evidence.prompt_tokens,
                result.usage_evidence.completion_tokens,
                result.usage_evidence.cached_tokens,
                result.usage_evidence.source.value,
                result.created_at.isoformat(),
            ),
        )

    def save_task_result(self, result: TaskResult) -> None:
        with self.db.get_connection() as conn:
            self._upsert_task_result(conn, result)
            conn.commit()

    def save_result_and_status(
        self,
        result: TaskResult,
        status: TaskStatus,
        finished_at: datetime,
        update: Optional[RunUpdate] = None,
    ) -> None:
        if update is not None and update.task_id != result.task_id:
            raise ValueError("Run Update must reference the completed Task Run")
        with self.db.transaction() as conn:
            self._upsert_task_result(conn, result)
            cursor = conn.execute(
                "UPDATE task_record SET status = ?, finished_at = ? WHERE id = ?",
                (status.value, finished_at.isoformat(), result.task_id),
            )
            if cursor.rowcount <= 0:
                raise ValueError("Task Run does not exist")
            if update is not None:
                self._insert_run_update(conn, update)

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
                    usage_evidence=self._usage_evidence(row),
                    created_at=_parse_iso(row["created_at"]),
                )
            return None

    def get_outcome_evidence(
        self,
        task_id: str,
    ) -> Optional[TaskRunOutcomeEvidence]:
        """Read only content-free outcome facts for cross-domain verification."""
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT task_record.id, task_record.session_id,
                       task_record.status, task_result.success
                FROM task_record
                LEFT JOIN task_result
                  ON task_result.task_id = task_record.id
                WHERE task_record.id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return TaskRunOutcomeEvidence(
            task_id=row["id"],
            session_id=row["session_id"],
            status=TaskStatus(row["status"]),
            result_success=bool(row["success"]) if row["success"] is not None else False,
        )

    def append_run_update(self, update: RunUpdate) -> RunUpdate:
        with self.db.transaction() as conn:
            exists = conn.execute(
                "SELECT 1 FROM task_record WHERE id = ?",
                (update.task_id,),
            ).fetchone()
            if exists is None:
                raise ValueError("Task Run does not exist")
            self._insert_run_update(conn, update)
        return update

    @staticmethod
    def _insert_task(conn, task: TaskRecord) -> None:
        conn.execute(
            """
            INSERT INTO task_record (
                id, input_text, task_type, status, difficulty, reward_exp,
                session_id, estimated_duration_seconds, estimated_token_usage, attempt_no,
                parent_task_id, has_image, created_at, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.id,
                task.input_text,
                task.task_type,
                task.status.value,
                task.difficulty.value,
                task.reward_exp,
                task.session_id,
                task.estimated_duration_seconds,
                task.estimated_token_usage,
                task.attempt_no,
                task.parent_task_id,
                int(task.has_image),
                task.created_at.isoformat(),
                task.started_at.isoformat() if task.started_at else None,
                task.finished_at.isoformat() if task.finished_at else None,
            ),
        )

    def list_run_updates(
        self,
        task_id: str,
        limit: int = 100,
    ) -> list[RunUpdate]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_run_update
                WHERE task_id = ?
                ORDER BY created_at ASC, rowid ASC
                LIMIT ?
                """,
                (task_id, max(1, min(500, limit))),
            ).fetchall()
        return [
            RunUpdate(
                id=row["id"],
                task_id=row["task_id"],
                kind=RunUpdateKind(row["kind"]),
                key=row["update_key"],
                title=row["title"],
                detail=row["detail"],
                status=RunUpdateStatus(row["status"]),
                progress=row["progress"],
                stage_family=row["stage_family"],
                depends_on=tuple(json.loads(row["depends_on_json"] or "[]")),
                estimated_duration_seconds=row["estimated_duration_seconds"],
                duration_ms=row["duration_ms"],
                created_at=_parse_iso(row["created_at"]),
            )
            for row in rows
        ]

    @staticmethod
    def _insert_run_update(conn, update: RunUpdate) -> None:
        conn.execute(
            """
            INSERT INTO task_run_update (
                id, task_id, kind, update_key, title, detail,
                status, progress, stage_family, depends_on_json,
                estimated_duration_seconds, duration_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                update.id,
                update.task_id,
                update.kind.value,
                update.key,
                update.title,
                update.detail,
                update.status.value,
                update.progress,
                update.stage_family,
                json.dumps(update.depends_on, ensure_ascii=False),
                update.estimated_duration_seconds,
                update.duration_ms,
                update.created_at.isoformat(),
            ),
        )

    def _row_to_task(self, row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            input_text=row["input_text"],
            task_type=row["task_type"],
            status=TaskStatus(row["status"]),
            difficulty=row["difficulty"],
            reward_exp=row["reward_exp"],
            session_id=row["session_id"],
            estimated_duration_seconds=row["estimated_duration_seconds"],
            estimated_token_usage=row["estimated_token_usage"],
            attempt_no=row["attempt_no"],
            parent_task_id=row["parent_task_id"],
            has_image=bool(row["has_image"]),
            created_at=_parse_iso(row["created_at"]),
            started_at=_parse_iso(row["started_at"]) if row["started_at"] else None,
            finished_at=_parse_iso(row["finished_at"]) if row["finished_at"] else None,
        )

    @staticmethod
    def _usage_source(value: str) -> ModelUsageSource:
        try:
            return ModelUsageSource(value)
        except ValueError:
            return ModelUsageSource.UNAVAILABLE

    @classmethod
    def _usage_evidence(cls, row) -> ModelUsageEvidence:
        """Normalize legacy or corrupt rows without turning them into trusted evidence."""

        def token_value(name: str) -> int:
            try:
                return max(0, int(row[name] or 0))
            except (TypeError, ValueError):
                return 0

        source = cls._usage_source(str(row["usage_source"] or ""))
        prompt_tokens = token_value("prompt_tokens")
        completion_tokens = token_value("completion_tokens")
        provider_model = str(row["model_name"] or "")[:160]
        if source == ModelUsageSource.UNAVAILABLE or not (prompt_tokens + completion_tokens):
            return ModelUsageEvidence(provider_model=provider_model)
        return ModelUsageEvidence(
            provider_model=provider_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=min(token_value("cached_tokens"), prompt_tokens),
            source=source,
        )
