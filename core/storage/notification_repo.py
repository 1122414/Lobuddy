"""Transactional inbox and display acknowledgements, separate from user read state."""

from __future__ import annotations

import builtins
import time
import uuid
from collections.abc import Callable

from core.service.schedule_protocol import NotificationBatch, NotificationView
from core.storage.db import Database


class NotificationRepository:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time) -> None:
        self.db, self.clock = db, clock
        self.valid: Callable[[NotificationView], bool] = lambda value: True
        self.eligible: Callable[[NotificationView], bool] = lambda value: True
        with db.transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS notification(
                id TEXT PRIMARY KEY, body TEXT NOT NULL)""")

    def put(self, value: NotificationView) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO notification VALUES(?,?)",
                (value.id, value.model_dump_json()),
            )

    def list(self) -> list[NotificationView]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT body FROM notification ORDER BY rowid DESC LIMIT 500"
            ).fetchall()
        return [NotificationView.model_validate_json(row[0]) for row in rows]

    def get(self, identity: str) -> NotificationView | None:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT body FROM notification WHERE id=?", (identity,)).fetchone()
        return NotificationView.model_validate_json(row[0]) if row else None

    def pending(self) -> builtins.list[NotificationView]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """SELECT body FROM notification WHERE
                json_extract(body,'$.status')='pending' OR
                (json_extract(body,'$.status')='leased' AND
                json_extract(body,'$.lease_until')<=?) ORDER BY rowid""",
                (self.clock(),),
            ).fetchall()
        return [NotificationView.model_validate_json(row[0]) for row in rows]

    def next(self, *, quiet: bool) -> NotificationBatch | None:
        now = self.clock()
        if quiet:
            return None
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT body FROM notification ORDER BY rowid").fetchall()
            pending = []
            for row in rows:
                value = NotificationView.model_validate_json(row[0])
                if not self.valid(value):
                    continue
                if value.status == "leased" and value.lease_until > now:
                    return None
                if (
                    value.status == "pending"
                    or value.status == "leased"
                    and value.lease_until <= now
                ) and self.eligible(value):
                    pending.append(value)
            if not pending:
                return None
            batch = str(uuid.uuid4())
            for value in pending:
                value.status, value.batch_id, value.lease_until = "leased", batch, now + 15
                conn.execute(
                    "UPDATE notification SET body=? WHERE id=?", (value.model_dump_json(), value.id)
                )
        return NotificationBatch(
            batch_id=batch,
            count=len(pending),
            expires_at=now + 15,
            text=(
                pending[0].text
                if len(pending) == 1
                else f"有 {len(pending)} 条提醒或任务结果，想看时打开通知收件箱就好。"
            ),
        )

    def displayed(self, batch_id: str, *, quiet: bool) -> bool:
        if quiet:
            return False
        changed = False
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT body FROM notification").fetchall()
            for row in rows:
                value = NotificationView.model_validate_json(row[0])
                if value.batch_id != batch_id:
                    continue
                if not self.valid(value):
                    continue
                if not self.eligible(value):
                    continue
                if value.status in ("delivered", "read"):
                    changed = True
                if value.status == "leased" and value.lease_until > self.clock():
                    value.status, value.delivered_at = "delivered", self.clock()
                    conn.execute(
                        "UPDATE notification SET body=? WHERE id=?",
                        (value.model_dump_json(), value.id),
                    )
                    changed = True
        return changed

    def read(self, identity: str) -> NotificationView:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT body FROM notification WHERE id=?", (identity,)).fetchone()
            if not row:
                raise ValueError("通知不存在")
            value = NotificationView.model_validate_json(row[0])
            if value.status in ("missed", "cancelled"):
                return value
            value.status = "read"
            value.delivered_at = value.delivered_at or self.clock()
            value.read_at = value.read_at or self.clock()
            conn.execute(
                "UPDATE notification SET body=? WHERE id=?", (value.model_dump_json(), value.id)
            )
            return value

    def cancel_for(self, identity: str) -> None:
        with self.db.transaction() as conn:
            for row in conn.execute("SELECT body FROM notification").fetchall():
                value = NotificationView.model_validate_json(row[0])
                if value.delegation_id == identity and value.status in ("pending", "leased"):
                    value.status = "cancelled"
                    conn.execute(
                        "UPDATE notification SET body=? WHERE id=?",
                        (value.model_dump_json(), value.id),
                    )
