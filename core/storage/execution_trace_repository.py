"""5.4 ExecutionTraceRepository — lightweight execution trace persistence."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from core.storage.base_repo import BaseRepository
from core.storage.db import Database

logger = logging.getLogger("lobuddy.execution_trace")

_MAX_COMMAND_CHARS = 500
_MAX_PATH_CHARS = 1000


class ExecutionTraceRepository(BaseRepository):
    """Lightweight execution trace persistence for debugging and test assertions."""

    def __init__(self, db: Database | None = None) -> None:
        super().__init__(db)
        self._init_tables()

    def _init_tables(self) -> None:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_traces (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    target TEXT,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_summary TEXT,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_execution_traces_session
                ON execution_traces(session_id, created_at)
                """
            )
            conn.commit()

    def record(
        self,
        session_id: str,
        intent: str,
        tool_name: str,
        arguments: dict[str, Any],
        status: str,
        target: str = "",
        result_summary: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> str:
        trace_id = str(uuid.uuid4())

        safe_args = self._sanitize_arguments(arguments)
        safe_summary = result_summary[:_MAX_COMMAND_CHARS] if result_summary else ""

        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO execution_traces (
                    id, session_id, created_at, intent, target,
                    tool_name, arguments_json, status, result_summary,
                    prompt_tokens, completion_tokens
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    session_id,
                    datetime.now().isoformat(),
                    intent,
                    target,
                    tool_name,
                    json.dumps(safe_args, ensure_ascii=False),
                    status,
                    safe_summary,
                    prompt_tokens,
                    completion_tokens,
                ),
            )
            conn.commit()

        logger.debug(
            "execution trace recorded: session=%s tool=%s status=%s intent=%s",
            session_id, tool_name, status, intent,
        )
        return trace_id

    def get_traces_for_session(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM execution_traces
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _sanitize_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in arguments.items():
            if isinstance(value, str):
                if key in {"command", "cmd"}:
                    safe[key] = value[:_MAX_COMMAND_CHARS]
                elif key in {"path", "file_path", "working_dir"}:
                    safe[key] = value[:_MAX_PATH_CHARS]
                else:
                    safe[key] = value[:500] if len(value) > 500 else value
            else:
                safe[key] = value
        return safe
