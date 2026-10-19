"""Project/source identity is explicit; tombstones cannot be revived by stale responses."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable

from core.service.project_protocol import ProjectCreate, ProjectView, SourceView
from core.storage.db import Database, _ensure_column


class ProjectRepository:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time) -> None:
        self.db, self.clock = db, clock
        with db.transaction() as conn:
            for table in ("personal_project", "project_source"):
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY,body TEXT NOT NULL)"
                )
            conn.execute("CREATE TABLE IF NOT EXISTS project_schema(version INTEGER PRIMARY KEY)")
            conn.execute("INSERT OR IGNORE INTO project_schema VALUES(1)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS project_session(session_id TEXT PRIMARY KEY,project_id TEXT NOT NULL)"
            )
            _ensure_column(conn.cursor(), "project_session", "revision INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS project_context_use(turn_id TEXT,source_id TEXT,PRIMARY KEY(turn_id,source_id))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS project_request(id TEXT PRIMARY KEY,fingerprint TEXT,entity_id TEXT)"
            )

    def projects(self) -> list[ProjectView]:
        with self.db.get_connection() as conn:
            return [
                ProjectView.model_validate_json(row[0])
                for row in conn.execute("SELECT body FROM personal_project ORDER BY rowid DESC")
            ]

    def project(self, identity: str) -> ProjectView:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT body FROM personal_project WHERE id=?", (identity,)
            ).fetchone()
        if not row:
            raise ValueError("项目不存在，请明确选择项目")
        return ProjectView.model_validate_json(row[0])

    def create(self, request_id: str, spec: ProjectCreate) -> ProjectView:
        identity = str(uuid.uuid4())
        fingerprint = hashlib.sha256(spec.model_dump_json().encode()).hexdigest()
        with self.db.transaction() as conn:
            old = conn.execute(
                "SELECT fingerprint,entity_id FROM project_request WHERE id=?", (request_id,)
            ).fetchone()
            if old:
                if old[0] != fingerprint:
                    raise ValueError("重复请求内容不一致")
                row = conn.execute(
                    "SELECT body FROM personal_project WHERE id=?", (old[1],)
                ).fetchone()
                return ProjectView.model_validate_json(row[0])
            value = ProjectView(
                **spec.model_dump(), id=identity, created_at=self.clock(), updated_at=self.clock()
            )
            conn.execute(
                "INSERT INTO personal_project VALUES(?,?)", (value.id, value.model_dump_json())
            )
            conn.execute(
                "INSERT INTO project_request VALUES(?,?,?)", (request_id, fingerprint, identity)
            )
            return value

    def save_project(self, value: ProjectView, revision: int) -> ProjectView:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT body FROM personal_project WHERE id=?", (value.id,)
            ).fetchone()
            if not row or ProjectView.model_validate_json(row[0]).revision != revision:
                raise ValueError("项目已更新，请刷新")
            value.revision, value.updated_at = revision + 1, self.clock()
            conn.execute(
                "UPDATE personal_project SET body=? WHERE id=?", (value.model_dump_json(), value.id)
            )
        return value

    def sources(self) -> list[SourceView]:
        with self.db.get_connection() as conn:
            return [
                SourceView.model_validate_json(row[0])
                for row in conn.execute("SELECT body FROM project_source ORDER BY rowid DESC")
            ]

    def source(self, identity: str) -> SourceView:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT body FROM project_source WHERE id=?", (identity,)).fetchone()
        if not row:
            raise ValueError("来源不存在")
        return SourceView.model_validate_json(row[0])

    def replay_source(self, request_id: str, fingerprint: str) -> SourceView | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT fingerprint,entity_id FROM project_request WHERE id=?", (request_id,)
            ).fetchone()
        if not row:
            return None
        if row[0] != fingerprint:
            raise ValueError("重复请求内容不一致")
        return self.source(str(row[1]))

    def add(self, value: SourceView, request_id: str, fingerprint: str) -> SourceView:
        with self.db.transaction() as conn:
            old = conn.execute(
                "SELECT fingerprint,entity_id FROM project_request WHERE id=?", (request_id,)
            ).fetchone()
            if old:
                if old[0] != fingerprint:
                    raise ValueError("重复请求内容不一致")
                row = conn.execute(
                    "SELECT body FROM project_source WHERE id=?", (old[1],)
                ).fetchone()
                return SourceView.model_validate_json(row[0])
            conn.execute(
                "INSERT INTO project_source VALUES(?,?)", (value.id, value.model_dump_json())
            )
            conn.execute(
                "INSERT INTO project_request VALUES(?,?,?)", (request_id, fingerprint, value.id)
            )
        return value

    def save_source(self, value: SourceView, revision: int) -> SourceView:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT body FROM project_source WHERE id=?", (value.id,)).fetchone()
            old = SourceView.model_validate_json(row[0]) if row else None
            if not old or old.revision != revision or old.status == "forgotten":
                raise ValueError("来源已更新或遗忘，请刷新")
            value.revision = revision + 1
            conn.execute(
                "UPDATE project_source SET body=? WHERE id=?", (value.model_dump_json(), value.id)
            )
        return value

    def bind(self, session_id: str, project_id: str, revision: int) -> None:
        with self.db.transaction() as conn:
            if not conn.execute("SELECT 1 FROM chat_session WHERE id=?", (session_id,)).fetchone():
                raise ValueError("会话不存在")
            row = conn.execute(
                "SELECT revision FROM project_session WHERE session_id=?", (session_id,)
            ).fetchone()
            if (int(row[0]) if row else 0) != revision:
                raise ValueError("会话项目关联已变化，请刷新")
            conn.execute(
                "INSERT INTO project_session(session_id,project_id,revision) VALUES(?,?,?) ON CONFLICT(session_id) DO UPDATE SET project_id=excluded.project_id,revision=excluded.revision",
                (session_id, project_id, revision + 1),
            )

    def binding_revision(self, session_id: str) -> int:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT revision FROM project_session WHERE session_id=?", (session_id,)
            ).fetchone()
        return int(row[0]) if row else 0

    def bound(self, session_id: str) -> str:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT project_id FROM project_session WHERE session_id=?", (session_id,)
            ).fetchone()
        return str(row[0]) if row else ""

    def reset_engines(self, sessions: list[str]) -> None:
        with self.db.transaction() as conn:
            for session_id in sessions:
                conn.execute("DELETE FROM engine_session WHERE session_id=?", (session_id,))

    def source_sessions(self, source_id: str) -> list[str]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT state_json FROM service_turn JOIN project_context_use USING(turn_id) WHERE source_id=?",
                (source_id,),
            )
            return list({str(json.loads(row[0])["session_id"]) for row in rows})

    def project_sessions(self, project_id: str) -> list[str]:
        with self.db.get_connection() as conn:
            sessions = {
                str(row[0])
                for row in conn.execute(
                    "SELECT session_id FROM project_session WHERE project_id=?", (project_id,)
                )
            }
            for row in conn.execute("SELECT state_json FROM service_turn"):
                state = json.loads(row[0])
                if state.get("project_id") == project_id:
                    sessions.add(str(state["session_id"]))
            return list(sessions)

    def clear_derived(self, source_id: str) -> None:
        with self.db.transaction() as conn:
            # Summaries can contain quotations from previously supplied project context.
            conn.execute("DELETE FROM conversation_summary")
            conn.execute("DELETE FROM learning_job WHERE source_id=?", (source_id,))
