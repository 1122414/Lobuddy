"""Trusted result evidence, separate from transport completion and model assertions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from core.storage.db import Database


class Outcome(BaseModel):
    turn_id: str
    verdict: Literal["verified", "failed", "unknown"] = "unknown"
    criteria: list[str] = Field(default_factory=list)
    evidence: list[dict[str, JsonValue]] = Field(default_factory=list)
    scenario: str = "chat"
    reason: str = "没有可独立检查的任务验收证据"


class OutcomeRepository:
    def __init__(self, db: Database) -> None:
        self.db = db
        with db.transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS task_acceptance(
                turn_id TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS task_effect(
                id TEXT PRIMARY KEY, turn_id TEXT NOT NULL, state TEXT NOT NULL,
                body TEXT NOT NULL)""")

    def get(self, turn_id: str) -> Outcome:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT body FROM task_acceptance WHERE turn_id=?", (turn_id,)
            ).fetchone()
        return Outcome.model_validate_json(row[0]) if row else Outcome(turn_id=turn_id)

    def save(self, outcome: Outcome) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO task_acceptance VALUES(?,?,?)
                ON CONFLICT(turn_id) DO UPDATE SET body=excluded.body""",
                (outcome.turn_id, outcome.model_dump_json(), datetime.now().isoformat()),
            )

    def claim_effect(self, identity: str, turn_id: str, body: str) -> None:
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT state FROM task_effect WHERE id=? OR turn_id=?", (identity, turn_id)
            ).fetchone()
            if existing:
                raise ValueError("该写操作已执行或结果未知，不能自动重放")
            conn.execute(
                "INSERT INTO task_effect VALUES(?,?,'started',?)", (identity, turn_id, body)
            )

    def finish_effect(self, identity: str, state: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE task_effect SET state=? WHERE id=?", (state, identity))

    def finish_turn(self, turn_id: str, status: str) -> Outcome:
        outcome = self.get(turn_id)
        if status in ("cancelled", "interrupted"):
            outcome.verdict = "unknown"
            outcome.reason = "执行已取消或中断；已发生的副作用不会自动撤销"
        self.save(outcome)
        return outcome
