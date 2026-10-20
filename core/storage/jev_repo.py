"""Reserve before network I/O, once per notification even across process loss."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from core.service.jev_protocol import JevDecision
from core.storage.db import Database


class JevRepository:
    def __init__(self, db: Database) -> None:
        self.db = db
        with db.transaction() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS jev_decision (
                notification_id TEXT PRIMARY KEY, context_hash TEXT NOT NULL, body TEXT NOT NULL)"""
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS jev_budget (
                day TEXT PRIMARY KEY, calls INTEGER NOT NULL, request_bytes INTEGER NOT NULL)""")
            for row in conn.execute("SELECT notification_id, body FROM jev_decision").fetchall():
                value = JevDecision.model_validate_json(row["body"])
                if value.status == "running":
                    value.status, value.reason = "interrupted", "上次判断中断，未自动重试"
                    conn.execute(
                        "UPDATE jev_decision SET body=? WHERE notification_id=?",
                        (value.model_dump_json(), row["notification_id"]),
                    )

    @staticmethod
    def day(now: float) -> str:
        return datetime.fromtimestamp(now, ZoneInfo("Asia/Shanghai")).date().isoformat()

    def get(self, identity: str) -> JevDecision | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT body FROM jev_decision WHERE notification_id=?", (identity,)
            ).fetchone()
        return JevDecision.model_validate_json(row[0]) if row else None

    def usage(self, now: float) -> tuple[int, int]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT calls,request_bytes FROM jev_budget WHERE day=?", (self.day(now),)
            ).fetchone()
        return (int(row[0]), int(row[1])) if row else (0, 0)

    def reserve(
        self,
        identity: str,
        digest: str,
        value: JevDecision,
        size: int,
        daily_calls: int,
        daily_bytes: int,
    ) -> bool:
        with self.db.transaction() as conn:
            if conn.execute(
                "SELECT 1 FROM jev_decision WHERE notification_id=?", (identity,)
            ).fetchone():
                return False
            day = self.day(value.created_at)
            conn.execute("INSERT OR IGNORE INTO jev_budget VALUES(?,0,0)", (day,))
            used = conn.execute("SELECT * FROM jev_budget WHERE day=?", (day,)).fetchone()
            accepted = used["calls"] < daily_calls and used["request_bytes"] + size <= daily_bytes
            if accepted:
                conn.execute(
                    "UPDATE jev_budget SET calls=calls+1,request_bytes=request_bytes+? WHERE day=?",
                    (size, day),
                )
            else:
                value.status, value.reason = "fallback", "今日 Jev 预算已用完，延后合并"
            conn.execute(
                "INSERT INTO jev_decision VALUES(?,?,?)",
                (identity, digest, value.model_dump_json()),
            )
        return bool(accepted)

    def finish(self, identity: str, value: JevDecision) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE jev_decision SET body=? WHERE notification_id=?",
                (value.model_dump_json(), identity),
            )

    def recent(self) -> list[JevDecision]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT body FROM jev_decision ORDER BY rowid DESC LIMIT 10"
            ).fetchall()
        return [JevDecision.model_validate_json(row[0]) for row in rows]
