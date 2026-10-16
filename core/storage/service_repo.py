"""Durable request identity, engine mapping, turn states and event sequence."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import JsonValue

from core.service.protocol import ServiceEvent, TurnSend, TurnState
from core.storage.db import Database


class ServiceRepository:
    def __init__(self, db: Database) -> None:
        self.db = db
        with db.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS service_schema_version (version INTEGER PRIMARY KEY)"
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS engine_session (
                session_id TEXT NOT NULL REFERENCES chat_session(id), lane TEXT NOT NULL,
                engine_id TEXT NOT NULL UNIQUE, ready INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (session_id, lane))"""
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS service_turn (
                turn_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                request_json TEXT NOT NULL, state_json TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS service_event (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_json TEXT NOT NULL)""")
            conn.execute("INSERT OR IGNORE INTO service_schema_version(version) VALUES (1)")

    def submit(self, request_id: str, params: TurnSend) -> tuple[TurnState, bool, bool]:
        """Commit input and task before dispatch; replay returns the original identity."""
        request_json = params.model_dump_json()
        with self.db.transaction() as conn:
            found = conn.execute(
                "SELECT request_json, state_json FROM service_turn WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if found:
                if TurnSend.model_validate_json(found["request_json"]) != params:
                    raise ValueError("请求 ID 已用于不同内容")
                return TurnState.model_validate_json(found["state_json"]), False, False
            if (
                conn.execute(
                    "SELECT id FROM chat_session WHERE id=?", (params.session_id,)
                ).fetchone()
                is None
            ):
                raise ValueError("会话不存在")
            row = conn.execute(
                "SELECT engine_id FROM engine_session WHERE session_id=? AND lane=?",
                (params.session_id, params.lane),
            ).fetchone()
            existed = row is not None
            engine_id = row["engine_id"] if row else f"lobuddy-{uuid.uuid4().hex}"
            if row is None:
                conn.execute(
                    "INSERT INTO engine_session(session_id, lane, engine_id) VALUES (?, ?, ?)",
                    (params.session_id, params.lane, engine_id),
                )
            state = TurnState(
                turn_id=str(uuid.uuid4()),
                task_id=str(uuid.uuid4()),
                session_id=params.session_id,
                engine_id=engine_id,
                lane=params.lane,
                status="queued",
                input_text=params.text,
                image_id=params.image_id,
            )
            conn.execute(
                "INSERT INTO service_turn VALUES (?, ?, ?, ?)",
                (state.turn_id, request_id, request_json, state.model_dump_json()),
            )
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO chat_message(id, session_id, role, content, created_at, image_path) VALUES (?, ?, 'user', ?, ?, ?)",
                (state.turn_id, state.session_id, params.text, now, params.image_id),
            )
            conn.execute(
                "UPDATE chat_session SET updated_at=?, title=CASE WHEN title='新对话' THEN ? ELSE title END WHERE id=?",
                (now, params.text.strip()[:30], state.session_id),
            )
            return state, True, existed

    def engine_ready(self, engine_id: str) -> bool:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT ready FROM engine_session WHERE engine_id=?", (engine_id,)
            ).fetchone()
        return bool(row and row["ready"])

    def mark_engine_ready(self, engine_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE engine_session SET ready=1 WHERE engine_id=?", (engine_id,))

    def save(self, state: TurnState) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE service_turn SET state_json=? WHERE turn_id=?",
                (state.model_dump_json(), state.turn_id),
            )
            if state.status == "completed":
                conn.execute(
                    "INSERT OR IGNORE INTO chat_message(id, session_id, role, content, created_at) VALUES (?, ?, 'assistant', ?, ?)",
                    (
                        state.turn_id + "-reply",
                        state.session_id,
                        state.output_text,
                        datetime.now().isoformat(),
                    ),
                )

    def get(self, turn_id: str) -> TurnState:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT state_json FROM service_turn WHERE turn_id=?", (turn_id,)
            ).fetchone()
        if row is None:
            raise ValueError("任务不存在")
        return TurnState.model_validate_json(row["state_json"])

    def list_turns(self) -> list[TurnState]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT state_json FROM service_turn ORDER BY rowid DESC LIMIT 100"
            ).fetchall()
        return [TurnState.model_validate_json(row["state_json"]) for row in rows]

    def interrupt_unfinished(self) -> None:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT state_json FROM service_turn").fetchall()
            for row in rows:
                state = TurnState.model_validate_json(row["state_json"])
                if state.status in ("queued", "running"):
                    state.status = "interrupted"
                    state.error = "上次服务中断，未自动重放，请确认已有结果后再继续。"
                    conn.execute(
                        "UPDATE service_turn SET state_json=? WHERE turn_id=?",
                        (state.model_dump_json(), state.turn_id),
                    )

    def event(self, state: TurnState, kind: str, data: dict[str, JsonValue]) -> ServiceEvent:
        with self.db.transaction() as conn:
            cursor = conn.execute("INSERT INTO service_event(event_json) VALUES ('{}')")
            assert cursor.lastrowid is not None
            event = ServiceEvent(
                session_id=state.session_id,
                task_id=state.task_id,
                turn_id=state.turn_id,
                sequence=cursor.lastrowid,
                kind=kind,
                data=data,
            )
            conn.execute(
                "UPDATE service_event SET event_json=? WHERE sequence=?",
                (event.model_dump_json(), event.sequence),
            )
        return event
