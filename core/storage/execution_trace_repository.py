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
            session_id,
            tool_name,
            status,
            intent,
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

    def get_completed_tools_for_task(
        self,
        task_id: str,
        limit: int = 200,
    ) -> list[str]:
        """Return content-free tool evidence for one Task Run.

        Runtime traces historically store the Task Run id in ``session_id``.
        This Adapter keeps that storage detail out of provenance consumers.
        """
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT tool_name FROM execution_traces
                WHERE session_id = ? AND status = 'completed'
                ORDER BY created_at ASC, rowid ASC
                LIMIT ?
                """,
                (task_id, max(1, min(1000, limit))),
            ).fetchall()
        return list(
            dict.fromkeys(
                str(row["tool_name"]).strip() for row in rows if str(row["tool_name"]).strip()
            )
        )

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM execution_traces ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_old(self, older_than_seconds: float) -> int:
        import time

        cutoff = time.time() - older_than_seconds
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM execution_traces WHERE created_at < ?",
                (datetime.fromtimestamp(cutoff).isoformat(),),
            )
            conn.commit()
            return cursor.rowcount

    def _sanitize_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        is_typing_action = arguments.get("action") == "type_text"
        for key, value in arguments.items():
            if key in {"text", "password", "token", "api_key", "secret"}:
                safe[key] = f"<redacted:{len(str(value))} chars>"
                continue
            if is_typing_action and key == "description":
                safe[key] = "<redacted for typing action>"
                continue
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
