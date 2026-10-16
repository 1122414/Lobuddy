"""Durable, single-owner learning queue with conservative daily reservations."""

import json
from datetime import datetime

from core.service.learning_protocol import LearningBudget, LearningJobView, LearningPolicy
from core.storage.db import Database


class LearningRepository:
    def __init__(self, db: Database) -> None:
        self.db = db
        with db.transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS learning_schema (version INTEGER PRIMARY KEY)")
            conn.execute("""CREATE TABLE IF NOT EXISTS learning_job (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, source_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL, error TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '{}', UNIQUE(kind, source_id))""")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS learning_budget (
                day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0)"""
            )
            conn.execute("INSERT OR IGNORE INTO learning_schema VALUES (1)")

    def recover(self, now: float) -> None:
        # The process cannot know whether a request reached the provider. Keep its reservation.
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE learning_job SET status='interrupted', updated_at=?, "
                "error='上次运行中断，保留预算；等待安全处理' WHERE status='running'",
                (now,),
            )

    @staticmethod
    def day(now: float) -> str:
        return datetime.fromtimestamp(now).date().isoformat()

    def enqueue(self, kind: str, source_id: str, now: float) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO learning_job(id, kind, source_id, updated_at) VALUES(?,?,?,?)",
                (kind + ":" + source_id, kind, source_id, now),
            )

    def jobs(self, limit: int = 30) -> list[LearningJobView]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM learning_job ORDER BY updated_at DESC, id LIMIT ?", (limit,)
            ).fetchall()
        return [
            LearningJobView.model_validate({**dict(row), "result": json.loads(row["result"])})
            for row in rows
        ]

    def usage(self, now: float) -> LearningBudget:
        day = self.day(now)
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM learning_budget WHERE day=?", (day,)).fetchone()
        return LearningBudget.model_validate(dict(row)) if row else LearningBudget(day=day)

    def claim(
        self,
        kind: str,
        now: float,
        policy: LearningPolicy,
        *,
        calls: int,
        input_tokens: int,
        output_tokens: int,
    ) -> tuple[str, str] | None:
        if min(calls, input_tokens, output_tokens) < 0:
            raise ValueError("预算预留不能为负数")
        if not policy.enabled:
            return None
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT id, source_id FROM learning_job WHERE kind=? AND attempts<3 "
                "AND (status='pending' OR (status IN ('interrupted','failed') AND updated_at<=?)) "
                "ORDER BY updated_at, id LIMIT 1",
                (kind, now - 300),
            ).fetchone()
            if row is None:
                return None
            day = self.day(now)
            conn.execute("INSERT OR IGNORE INTO learning_budget(day) VALUES(?)", (day,))
            used = conn.execute("SELECT * FROM learning_budget WHERE day=?", (day,)).fetchone()
            for key, amount, ceiling in (
                ("calls", calls, policy.daily_calls),
                ("input_tokens", input_tokens, policy.daily_input_tokens),
                ("output_tokens", output_tokens, policy.daily_output_tokens),
            ):
                if amount and used[key] + amount > ceiling:
                    return None
            conn.execute(
                "UPDATE learning_budget SET calls=calls+?, input_tokens=input_tokens+?, "
                "output_tokens=output_tokens+? WHERE day=?",
                (calls, input_tokens, output_tokens, day),
            )
            conn.execute(
                "UPDATE learning_job SET status='running', attempts=attempts+1, "
                "updated_at=?, error='' WHERE id=?",
                (now, row["id"]),
            )
            return str(row["id"]), str(row["source_id"])

    def finish(self, identity: str, status: str, now: float, result: str, error: str = "") -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE learning_job SET status=?, updated_at=?, result=?, error=? "
                "WHERE id=? AND status='running'",
                (status, now, result, error, identity),
            )
