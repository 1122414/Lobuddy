"""Single-owner local scheduling; cursor, run and notification are committed together."""

from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from collections.abc import Callable

from core.service.delegation_protocol import DelegationRun, DelegationView
from core.service.schedule_protocol import NotificationView, ScheduleView
from core.service.schedule_rules import next_occurrence
from core.storage.delegation_repo import DelegationRepository
from core.storage.notification_repo import NotificationRepository


class ScheduleRepository:
    def __init__(
        self,
        delegations: DelegationRepository,
        notifications: NotificationRepository,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.delegations, self.notifications, self.db = delegations, notifications, delegations.db
        self.clock, self.owner = clock, uuid.uuid4().hex
        with self.db.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schedule_owner(id INTEGER PRIMARY KEY CHECK(id=1),owner TEXT,expires REAL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS delegation_schedule(id TEXT PRIMARY KEY,signature TEXT,next_at REAL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS delegation_event(id TEXT PRIMARY KEY,kind TEXT,subject TEXT,at REAL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS delegation_event_consumed(delegation_id TEXT,event_id TEXT,PRIMARY KEY(delegation_id,event_id))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schedule_dispatch(trigger_id TEXT PRIMARY KEY,delegation_id TEXT,revision INTEGER,done INTEGER NOT NULL DEFAULT 0)"
            )

    def event(self, identity: str, kind: str, subject: str = "") -> None:
        if kind not in ("app_returned", "focus_finished", "delegation_completed"):
            raise ValueError("不支持的内部事件")
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO delegation_event VALUES(?,?,?,?)",
                (identity, kind, subject, self.clock()),
            )

    def release(self) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM schedule_owner WHERE id=1 AND owner=?", (self.owner,))

    def _lease(self, conn: sqlite3.Connection) -> bool:
        row = conn.execute("SELECT owner,expires FROM schedule_owner WHERE id=1").fetchone()
        if row and row["owner"] != self.owner and row["expires"] > self.clock():
            return False
        conn.execute(
            "INSERT INTO schedule_owner VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,expires=excluded.expires",
            (self.owner, self.clock() + 10),
        )
        return True

    def _save(self, conn: sqlite3.Connection, value: DelegationView) -> None:
        value.revision += 1
        value.updated_at = self.clock()
        self.delegations._write(conn, value)

    def _fire(
        self, conn: sqlite3.Connection, value: DelegationView, trigger: str, planned: float
    ) -> tuple[str, int, str] | None:
        now = self.clock()
        if value.spec.kind != "reminder":
            if value.spec.kind == "organize-files" or now - planned > 60:
                value.status, value.reason = (
                    "needs_review",
                    "文件写入或逾期执行需重新确认，不自动补跑",
                )
                self._save(conn, value)
                return None
            value.status, value.reason = "ready", "已到约定时间，准备受控只读任务"
            self._save(conn, value)
            conn.execute(
                "INSERT OR IGNORE INTO schedule_dispatch(trigger_id,delegation_id,revision) VALUES(?,?,?)",
                (trigger, value.id, value.revision),
            )
            return value.id, value.revision, trigger
        missed = (value.spec.repeat.frequency == "once" and now - planned > 86400) or (
            not value.spec.repeat.catch_up and now - planned > 60
        )
        identity = str(uuid.uuid5(uuid.NAMESPACE_URL, trigger))
        if conn.execute("SELECT 1 FROM notification WHERE id=?", (identity,)).fetchone():
            return None
        run = DelegationRun(
            id=identity,
            delegation_id=value.id,
            revision=value.revision + 1,
            trigger_id=trigger,
            workflow_version="notification",
            created_at=now,
            status="completed" if missed else "running",
            reason="已错过，不补弹提醒" if missed else "通知已保存，尚未投递",
            finished_at=now if missed else None,
        )
        notice = NotificationView(
            id=identity,
            reason="reminder",
            source_id=run.id,
            delegation_id=value.id,
            text=value.spec.goal
            + (f"（延迟约 {max(1, int((now-planned)/60))} 分钟）" if now - planned > 60 else ""),
            planned_at=planned,
            created_at=now,
            status="missed" if missed else "pending",
        )
        conn.execute("INSERT INTO notification VALUES(?,?)", (identity, notice.model_dump_json()))
        conn.execute(
            "INSERT INTO delegation_run VALUES(?,?,?,NULL,?)",
            (run.id, value.id, trigger, run.model_dump_json()),
        )
        if value.spec.repeat.frequency != "once" and missed:
            cursor = conn.execute(
                "SELECT next_at FROM delegation_schedule WHERE id=?", (value.id,)
            ).fetchone()
            if cursor and cursor[0] is None:
                value.status = "needs_review"
        if value.spec.repeat.frequency == "once":
            value.status = "needs_review" if missed else "waiting_user"
            value.active_run_id = "" if missed else run.id
        value.reason = run.reason
        self._save(conn, value)
        return None

    def tick(self) -> list[tuple[str, int, str]]:
        ready: list[tuple[str, int, str]] = []
        with self.db.transaction() as conn:
            if not self._lease(conn):
                return ready
            for row in conn.execute("SELECT body FROM delegation").fetchall():
                value = DelegationView.model_validate_json(row[0])
                if value.status not in ("scheduled", "waiting_event"):
                    continue
                now = self.clock()
                if not value.expires_at or value.expires_at <= now:
                    value.status, value.reason = (
                        "needs_review",
                        "授权已到期，等待你决定是否重新安排",
                    )
                    self._save(conn, value)
                    continue
                wait = value.spec.wait
                if wait.kind == "time":
                    signature = hashlib.sha256(value.spec.model_dump_json().encode()).hexdigest()
                    entry = conn.execute(
                        "SELECT signature,next_at FROM delegation_schedule WHERE id=?", (value.id,)
                    ).fetchone()
                    if not entry or entry["signature"] != signature:
                        conn.execute(
                            "INSERT INTO delegation_schedule VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET signature=excluded.signature,next_at=excluded.next_at",
                            (value.id, signature, wait.at),
                        )
                        due = wait.at
                    else:
                        due = entry["next_at"]
                    if due is None or due > now:
                        continue
                    if value.spec.repeat.end_at is not None and due > value.spec.repeat.end_at:
                        value.status, value.reason = "completed", "已到周期提醒结束时间"
                        self._save(conn, value)
                        continue
                    trigger = f"due:{value.id}:{signature}:{due}"
                    next_at = next_occurrence(value.spec.repeat, wait.timezone, now)
                    conn.execute(
                        "UPDATE delegation_schedule SET next_at=? WHERE id=?", (next_at, value.id)
                    )
                    result = self._fire(conn, value, trigger, due)
                    if result:
                        ready.append(result)
                elif wait.kind == "event":
                    events = conn.execute(
                        """SELECT * FROM delegation_event e WHERE kind=? AND subject=? AND at>=?
                        AND NOT EXISTS(SELECT 1 FROM delegation_event_consumed c WHERE c.delegation_id=? AND c.event_id=e.id)
                        ORDER BY at DESC LIMIT 1""",
                        (wait.event, wait.subject_id, value.authorized_at or now, value.id),
                    ).fetchall()
                    for event in events:
                        conn.execute(
                            "INSERT INTO delegation_event_consumed VALUES(?,?)",
                            (value.id, event["id"]),
                        )
                        result = self._fire(
                            conn, value, f"event:{value.id}:{event['id']}", event["at"]
                        )
                        if result:
                            ready.append(result)
        self.complete_deliveries()
        with self.db.get_connection() as conn:
            return [
                (row["delegation_id"], row["revision"], row["trigger_id"])
                for row in conn.execute("SELECT * FROM schedule_dispatch WHERE done=0")
            ]

    def dispatched(self, trigger: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE schedule_dispatch SET done=1 WHERE trigger_id=?", (trigger,))

    def complete_deliveries(self) -> None:
        with self.db.transaction() as conn:
            for row in conn.execute("SELECT body FROM notification").fetchall():
                notice = NotificationView.model_validate_json(row[0])
                if notice.reason != "reminder" or notice.status not in ("delivered", "read"):
                    continue
                result = conn.execute(
                    "SELECT body FROM delegation_run WHERE id=?", (notice.source_id,)
                ).fetchone()
                if not result:
                    continue
                run = DelegationRun.model_validate_json(result[0])
                if run.status == "completed":
                    continue
                value = self.delegations._read(conn, run.delegation_id)
                if value.status in ("paused", "cancelled", "draft"):
                    continue
                run.status, run.verdict, run.finished_at = "completed", "verified", self.clock()
                run.reason = "通知已投递；用户是否已读单独记录"
                conn.execute(
                    "UPDATE delegation_run SET body=? WHERE id=?", (run.model_dump_json(), run.id)
                )
                if value.spec.repeat.frequency == "once":
                    value.status, value.active_run_id = "completed", ""
                else:
                    entry = conn.execute(
                        "SELECT next_at FROM delegation_schedule WHERE id=?", (value.id,)
                    ).fetchone()
                    if entry and entry[0] is None:
                        value.status = "completed"
                value.reason = run.reason
                self._save(conn, value)

    def view(self, identity: str) -> ScheduleView:
        value = self.delegations.get(identity)
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT next_at FROM delegation_schedule WHERE id=?", (identity,)
            ).fetchone()
        return ScheduleView(
            delegation_id=identity,
            next_at=row[0] if row else value.spec.wait.at,
            timezone=value.spec.wait.timezone,
            repeat=value.spec.repeat,
            state=value.status,
            reason=value.reason,
        )
