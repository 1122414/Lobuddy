"""Durable delegation identity, optimistic revisions and conservative recovery."""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Callable

from pydantic import BaseModel

from core.service.delegation_protocol import (
    DelegationChange,
    DelegationConfirm,
    DelegationDetail,
    DelegationEdit,
    DelegationRun,
    DelegationSpec,
    DelegationStatus,
    DelegationView,
)
from core.storage.db import Database


class DelegationRepository:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time) -> None:
        self.db = db
        self.clock = clock
        with db.transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS delegation_schema(
                version INTEGER PRIMARY KEY)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS delegation(
                id TEXT PRIMARY KEY, body TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS delegation_revision(
                id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(id,revision), FOREIGN KEY(id) REFERENCES delegation(id))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS delegation_request(
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS delegation_run(
                id TEXT PRIMARY KEY, delegation_id TEXT NOT NULL, trigger_id TEXT NOT NULL UNIQUE,
                turn_id TEXT UNIQUE, body TEXT NOT NULL,
                FOREIGN KEY(delegation_id) REFERENCES delegation(id))""")
            conn.execute("INSERT OR IGNORE INTO delegation_schema VALUES(1)")

    @staticmethod
    def _read(conn: sqlite3.Connection, identity: str) -> DelegationView:
        row = conn.execute("SELECT body FROM delegation WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise ValueError("委托不存在")
        return DelegationView.model_validate_json(row[0])

    @staticmethod
    def _write(conn: sqlite3.Connection, value: DelegationView) -> None:
        body = value.model_dump_json()
        conn.execute(
            "INSERT INTO delegation VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
            (value.id, body),
        )
        conn.execute(
            "INSERT INTO delegation_revision VALUES(?,?,?)",
            (value.id, value.revision, body),
        )

    @staticmethod
    def _replay(conn: sqlite3.Connection, identity: str, fingerprint: str) -> str | None:
        row = conn.execute(
            "SELECT fingerprint,result FROM delegation_request WHERE id=?", (identity,)
        ).fetchone()
        if row and row["fingerprint"] != fingerprint:
            raise ValueError("请求 ID 已用于不同委托操作")
        return str(row["result"]) if row else None

    @staticmethod
    def _remember(
        conn: sqlite3.Connection, identity: str, fingerprint: str, value: BaseModel
    ) -> None:
        conn.execute(
            "INSERT INTO delegation_request VALUES(?,?,?)",
            (identity, fingerprint, value.model_dump_json()),
        )

    def create(self, identity: str, spec: DelegationSpec) -> DelegationView:
        fingerprint = "create:" + spec.model_dump_json()
        with self.db.transaction() as conn:
            previous = self._replay(conn, identity, fingerprint)
            if previous:
                return DelegationView.model_validate_json(previous)
            if (
                spec.session_id
                and not conn.execute(
                    "SELECT 1 FROM chat_session WHERE id=?", (spec.session_id,)
                ).fetchone()
            ):
                raise ValueError("来源会话不存在")
            if (
                spec.source_message_id
                and not conn.execute(
                    "SELECT 1 FROM chat_message WHERE id=? AND session_id=? AND role='user'",
                    (spec.source_message_id, spec.session_id),
                ).fetchone()
            ):
                raise ValueError("来源必须是指定会话中的用户消息")
            now = self.clock()
            value = DelegationView(
                id=str(uuid.uuid4()), revision=1, spec=spec, created_at=now, updated_at=now
            )
            self._write(conn, value)
            self._remember(conn, identity, fingerprint, value)
            return value

    def get(self, identity: str) -> DelegationView:
        with self.db.get_connection() as conn:
            return self._read(conn, identity)

    def list(self) -> list[DelegationView]:
        with self.db.get_connection() as conn:
            rows = conn.execute("SELECT body FROM delegation ORDER BY rowid DESC").fetchall()
        return [DelegationView.model_validate_json(row[0]) for row in rows]

    def detail(self, identity: str) -> DelegationDetail:
        with self.db.get_connection() as conn:
            value = self._read(conn, identity)
            runs = conn.execute(
                "SELECT body FROM delegation_run WHERE delegation_id=? ORDER BY rowid DESC",
                (identity,),
            ).fetchall()
            revisions = conn.execute(
                "SELECT body FROM delegation_revision WHERE id=? ORDER BY revision DESC",
                (identity,),
            ).fetchall()
        return DelegationDetail(
            delegation=value,
            runs=[DelegationRun.model_validate_json(row[0]) for row in runs],
            revisions=[DelegationView.model_validate_json(row[0]) for row in revisions],
        )

    @staticmethod
    def _check(value: DelegationView, revision: int) -> None:
        if value.revision != revision:
            raise ValueError("委托已更新，请重新读取后操作")
        if value.status in ("completed", "cancelled", "failed"):
            raise ValueError("委托已结束，请新建委托")

    @staticmethod
    def _ready(value: DelegationView) -> None:
        states: dict[str, DelegationStatus] = {
            "none": "ready",
            "time": "scheduled",
            "user": "waiting_user",
            "event": "waiting_event",
        }
        value.status = states[value.spec.wait.kind]
        value.reason = "已确认；仅在约定范围与有效期内执行，写入仍须审批"

    def change(self, identity: str, action: str, params: DelegationChange) -> DelegationView:
        fingerprint = action + ":" + params.model_dump_json()
        with self.db.transaction() as conn:
            previous = self._replay(conn, identity, fingerprint)
            if previous:
                return DelegationView.model_validate_json(previous)
            value = self._read(conn, params.delegation_id)
            self._check(value, params.revision)
            now = self.clock()
            if action == "confirm" and isinstance(params, DelegationConfirm):
                if value.status != "draft" or params.expires_at <= now:
                    raise ValueError("只能确认有效期在未来的草稿")
                if value.spec.wait.at and value.spec.wait.at >= params.expires_at:
                    raise ValueError("授权有效期必须晚于提醒时间")
                value.authorized_at, value.expires_at = now, params.expires_at
                self._ready(value)
            elif action == "pause":
                if value.status in ("draft", "paused"):
                    raise ValueError("当前状态不能暂停")
                value.status, value.reason = "paused", "已暂停；已发生的操作不会自动撤销"
            elif action == "cancel":
                value.status, value.reason = "cancelled", "已取消，不再调度；既有产物保留"
            elif action == "resume":
                if value.status != "paused" or not value.expires_at or value.expires_at <= now:
                    raise ValueError("只有仍获授权的暂停委托可以继续")
                if value.active_run_id:
                    raise ValueError("上次执行需要先核对；不能自动重放")
                self._ready(value)
            elif action == "edit" and isinstance(params, DelegationEdit):
                if value.status == "running" or value.active_run_id:
                    raise ValueError("请先暂停并核对已发生的操作")
                if (params.spec.session_id, params.spec.source_message_id) != (
                    value.spec.session_id,
                    value.spec.source_message_id,
                ):
                    raise ValueError("原始委托来源不能被替换")
                value.spec = params.spec
                value.authorized_at = value.expires_at = None
                value.status, value.reason = "draft", "目标或范围已变更，需要重新确认"
            else:
                raise ValueError("不支持的委托状态转换")
            value.revision += 1
            value.updated_at = now
            self._write(conn, value)
            self._remember(conn, identity, fingerprint, value)
            return value

    def claim(
        self, trigger_id: str, params: DelegationChange, workflow_version: str
    ) -> tuple[DelegationRun, bool]:
        fingerprint = "run:" + params.model_dump_json()
        with self.db.transaction() as conn:
            previous = self._replay(conn, trigger_id, fingerprint)
            if previous:
                return DelegationRun.model_validate_json(previous), False
            value = self._read(conn, params.delegation_id)
            self._check(value, params.revision)
            if value.status != "ready" or not value.expires_at or value.expires_at <= self.clock():
                raise ValueError("委托尚未就绪或授权已到期")
            if value.active_run_id or value.spec.kind == "reminder":
                raise ValueError("委托已有运行，或应由提醒调度器处理")
            if not workflow_version:
                raise ValueError("执行必须固定工作流版本")
            value.revision += 1
            value.updated_at = self.clock()
            run = DelegationRun(
                id=str(uuid.uuid4()),
                delegation_id=value.id,
                revision=value.revision,
                trigger_id=trigger_id,
                workflow_version=workflow_version,
                created_at=self.clock(),
            )
            value.active_run_id, value.status, value.reason = run.id, "running", "已领取执行"
            self._write(conn, value)
            conn.execute(
                "INSERT INTO delegation_run VALUES(?,?,?,NULL,?)",
                (run.id, value.id, trigger_id, run.model_dump_json()),
            )
            self._remember(conn, trigger_id, fingerprint, run)
            return run, True

    def replayed_run(self, trigger_id: str, params: DelegationChange) -> DelegationRun | None:
        with self.db.get_connection() as conn:
            previous = self._replay(conn, trigger_id, "run:" + params.model_dump_json())
            if not previous:
                return None
            run = DelegationRun.model_validate_json(previous)
            row = conn.execute("SELECT body FROM delegation_run WHERE id=?", (run.id,)).fetchone()
            return DelegationRun.model_validate_json(row[0])

    def bind(self, run_id: str, turn_id: str) -> None:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT body FROM delegation_run WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise ValueError("执行不存在")
            run = DelegationRun.model_validate_json(row[0])
            if run.turn_id and run.turn_id != turn_id:
                raise ValueError("执行已关联另一轮任务")
            run.turn_id, run.status = turn_id, "running"
            conn.execute(
                "UPDATE delegation_run SET turn_id=?,body=? WHERE id=?",
                (turn_id, run.model_dump_json(), run_id),
            )

    def active(self, run_id: str) -> bool:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT body FROM delegation_run WHERE id=?", (run_id,)).fetchone()
            if not row:
                return False
            run = DelegationRun.model_validate_json(row[0])
            value = self._read(conn, run.delegation_id)
        return bool(
            run.status in ("reserved", "running")
            and value.status == "running"
            and value.revision == run.revision
            and value.active_run_id == run.id
            and value.expires_at
            and self.clock() < value.expires_at
        )

    def settle(self, turn_id: str, status: str, verdict: str, reason: str) -> None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT body FROM delegation_run WHERE turn_id=?", (turn_id,)
            ).fetchone()
            if not row:
                return
            run = DelegationRun.model_validate_json(row[0])
            if run.status not in ("reserved", "running"):
                return
            run = DelegationRun.model_validate(
                {
                    **run.model_dump(),
                    "status": status,
                    "verdict": verdict,
                    "finished_at": self.clock(),
                    "reason": reason,
                }
            )
            conn.execute(
                "UPDATE delegation_run SET body=? WHERE id=?", (run.model_dump_json(), run.id)
            )
            value = self._read(conn, run.delegation_id)
            if value.revision != run.revision or value.status != "running":
                # A late result is retained as evidence, never used to revive an older goal.
                return
            value.status = (
                "completed"
                if status == "completed" and verdict == "verified"
                else "failed" if status == "failed" or verdict == "failed" else "needs_review"
            )
            value.reason = reason
            if value.status in ("completed", "failed"):
                value.active_run_id = ""
            value.revision += 1
            value.updated_at = self.clock()
            self._write(conn, value)

    def recover(self, run_id: str | None = None) -> None:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT body FROM delegation_run WHERE ? IS NULL OR id=?", (run_id, run_id)
            ).fetchall()
            for row in rows:
                run = DelegationRun.model_validate_json(row[0])
                if run.workflow_version == "notification":
                    continue
                if run.status not in ("reserved", "running"):
                    continue
                run.status, run.verdict = "interrupted", "unknown"
                run.reason, run.finished_at = "服务中断，尚未核实结果；不自动重放", self.clock()
                conn.execute(
                    "UPDATE delegation_run SET body=? WHERE id=?", (run.model_dump_json(), run.id)
                )
                value = self._read(conn, run.delegation_id)
                if value.status in ("paused", "cancelled"):
                    continue
                value.status, value.reason = "needs_review", run.reason
                value.revision += 1
                value.updated_at = self.clock()
                self._write(conn, value)

    def review(self, identity: str, reason: str) -> None:
        with self.db.transaction() as conn:
            value = self._read(conn, identity)
            if value.status in ("completed", "cancelled", "failed", "paused", "draft"):
                return
            value.status, value.reason = "needs_review", reason
            value.revision += 1
            value.updated_at = self.clock()
            self._write(conn, value)
