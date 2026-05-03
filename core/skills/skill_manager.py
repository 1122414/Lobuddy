"""Skill manager with SQLite-backed lifecycle and workspace projection."""

import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from core.config import Settings
from core.skills.skill_schema import SkillCandidate, SkillEvent, SkillRecord, SkillStatus
from core.storage.base_repo import BaseRepository
from core.storage.db import Database

logger = logging.getLogger(__name__)


class SkillManager(BaseRepository):
    """Manages skill lifecycle: create, patch, disable, archive, delete."""

    def __init__(self, settings: Settings, db: Optional[Database] = None) -> None:
        super().__init__(db)
        self._settings = settings
        self._workspace_skills = settings.workspace_path / "skills"
        self._archive_dir = settings.skill_archive_dir
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _init_tables(self):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_record (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    path TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    status TEXT NOT NULL DEFAULT 'draft',
                    version INTEGER NOT NULL DEFAULT 1,
                    source TEXT NOT NULL DEFAULT 'manual',
                    source_session_id TEXT,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    last_used_at TEXT,
                    review_after TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_event (
                    id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    session_id TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (skill_id) REFERENCES skill_record(id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_skill_status ON skill_record(status)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_skill_category ON skill_record(category)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_candidate (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    proposed_name TEXT NOT NULL,
                    proposed_content TEXT NOT NULL,
                    source_session_id TEXT,
                    source_task_id TEXT,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def create_skill(self, record: SkillRecord, content: str) -> SkillRecord:
        skill_dir = self._workspace_skills / record.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        self._write_atomic(skill_file, content)
        record.path = str(skill_file)
        record.updated_at = datetime.now()
        self._save_record(record)
        self._log_event(record.id, "create", f"Created skill {record.name}")
        return record

    def patch_skill(self, skill_id: str, new_content: str, description: Optional[str] = None) -> bool:
        record = self.get_skill(skill_id)
        if not record:
            return False
        skill_file = Path(record.path)
        self._write_atomic(skill_file, new_content)
        record.version += 1
        if description:
            record.description = description
        record.updated_at = datetime.now()
        self._save_record(record)
        self._log_event(skill_id, "patch", f"Updated to v{record.version}")
        return True

    def disable_skill(self, skill_id: str) -> bool:
        record = self.get_skill(skill_id)
        if not record:
            return False
        skill_file = Path(record.path)
        if skill_file.exists():
            skill_file.unlink()
        parent = skill_file.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
        ok = self._update_status(skill_id, SkillStatus.DISABLED)
        if ok:
            self._log_event(skill_id, "disable", "Skill disabled, file removed")
        return ok

    def archive_skill(self, skill_id: str) -> bool:
        record = self.get_skill(skill_id)
        if not record:
            return False
        src = Path(record.path)
        if src.exists():
            dst = self._archive_dir / f"{record.name}_v{record.version}.md"
            shutil.copy2(src, dst)
            src.unlink()
            parent = src.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        self._update_status(skill_id, SkillStatus.ARCHIVED)
        self._log_event(skill_id, "archive", f"Archived to {self._archive_dir}, file removed")
        return True

    def delete_skill(self, skill_id: str) -> bool:
        record = self.get_skill(skill_id)
        if not record:
            return False
        skill_file = Path(record.path)
        if skill_file.exists():
            skill_file.unlink()
        parent = skill_file.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM skill_event WHERE skill_id = ?", (skill_id,))
            conn.execute("DELETE FROM skill_record WHERE id = ?", (skill_id,))
        return True

    def get_skill(self, skill_id: str) -> Optional[SkillRecord]:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM skill_record WHERE id = ?", (skill_id,)).fetchone()
            if not row:
                return None
            return self._row_to_skill_record(row)

    def get_skill_by_name(self, name: str) -> Optional[SkillRecord]:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM skill_record WHERE name = ?", (name,)).fetchone()
            if not row:
                return None
            return self._row_to_skill_record(row)

    def list_skills(
        self,
        status: Optional[SkillStatus] = None,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> list[SkillRecord]:
        query = "SELECT * FROM skill_record WHERE 1=1"
        params: list = []
        if status:
            query += " AND status = ?"
            params.append(status.value)
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_skill_record(r) for r in rows]

    def record_result(self, skill_id: str, success: bool, session_id: Optional[str] = None) -> bool:
        record = self.get_skill(skill_id)
        if not record:
            return False
        if success:
            record.success_count += 1
        else:
            record.failure_count += 1
        record.last_used_at = datetime.now()
        record.updated_at = datetime.now()
        self._save_record(record)
        self._log_event(skill_id, "use", f"{'Success' if success else 'Failure'}", session_id)
        return True

    def review_stale_skills(self) -> list[SkillRecord]:
        review_days = self._settings.skill_stale_review_days
        disable_days = self._settings.skill_stale_disable_days
        now = datetime.now()
        stale: list[SkillRecord] = []
        for skill in self.list_skills(status=SkillStatus.ACTIVE, limit=1000):
            if skill.last_used_at is None:
                continue
            days_since_use = (now - skill.last_used_at).days
            if days_since_use >= disable_days:
                self.disable_skill(skill.id)
                stale.append(skill)
            elif days_since_use >= review_days:
                self._update_status(skill.id, SkillStatus.NEEDS_REVIEW)
                stale.append(skill)
            elif skill.failure_rate() >= self._settings.skill_failure_rate_threshold and (skill.success_count + skill.failure_count) >= self._settings.skill_failure_rate_min_uses:
                self._update_status(skill.id, SkillStatus.NEEDS_REVIEW)
                stale.append(skill)
        return stale

    def cleanup_orphan_workspace_files(self) -> int:
        """Remove workspace SKILL.md files with no active SQLite record.

        Scans workspace/skills/*/SKILL.md and removes any file whose
        corresponding skill is not in ACTIVE status in the database.
        Returns count of files removed.
        """
        import os
        from pathlib import Path

        workspace = Path(self._settings.workspace_path) / "skills"
        if not workspace.exists():
            return 0

        removed = 0
        for skill_dir in workspace.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            skill_name = skill_dir.name
            try:
                existing = self.list_skills(name=skill_name, limit=1)
                if existing and existing[0].status == SkillStatus.ACTIVE:
                    continue
            except Exception:
                pass

            try:
                os.unlink(skill_md)
                logger.info("SkillMaintenance: removed orphan workspace file %s", skill_md)
                removed += 1
                remaining = list(skill_dir.iterdir())
                if not remaining:
                    skill_dir.rmdir()
            except OSError as exc:
                logger.warning("SkillMaintenance: failed to remove orphan %s: %s", skill_md, exc)

        return removed

    def create_candidate(self, candidate: SkillCandidate) -> SkillCandidate:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO skill_candidate (
                    id, title, rationale, proposed_name, proposed_content,
                    source_session_id, source_task_id, confidence, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.id,
                    candidate.title,
                    candidate.rationale,
                    candidate.proposed_name,
                    candidate.proposed_content,
                    candidate.source_session_id,
                    candidate.source_task_id,
                    candidate.confidence,
                    candidate.status,
                    candidate.created_at.isoformat(),
                    candidate.updated_at.isoformat(),
                ),
            )
        return candidate

    def get_candidate(self, candidate_id: str) -> Optional[SkillCandidate]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM skill_candidate WHERE id = ?", (candidate_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_skill_candidate(row)

    def list_candidates(self, status: Optional[str] = None, limit: int = 50) -> list[SkillCandidate]:
        query = "SELECT * FROM skill_candidate WHERE 1=1"
        params: list = []
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_skill_candidate(r) for r in rows]

    def approve_candidate(self, candidate_id: str) -> Optional[SkillRecord]:
        candidate = self.get_candidate(candidate_id)
        if not candidate:
            return None
        record = SkillRecord(
            id=str(uuid.uuid4()),
            name=candidate.proposed_name,
            path="",
            description=candidate.title,
            status=SkillStatus.ACTIVE,
            source="auto",
            source_session_id=candidate.source_session_id,
        )
        created = self.create_skill(record, candidate.proposed_content)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE skill_candidate SET status = ?, updated_at = ? WHERE id = ?",
                ("approved", datetime.now().isoformat(), candidate_id),
            )
        return created

    def _save_record(self, record: SkillRecord) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO skill_record (
                    id, name, path, description, category, status, version, source,
                    source_session_id, success_count, failure_count, last_used_at,
                    review_after, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id, record.name, record.path, record.description,
                    record.category, record.status.value, record.version, record.source,
                    record.source_session_id, record.success_count, record.failure_count,
                    record.last_used_at.isoformat() if record.last_used_at else None,
                    record.review_after.isoformat() if record.review_after else None,
                    record.expires_at.isoformat() if record.expires_at else None,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )

    def _update_status(self, skill_id: str, status: SkillStatus) -> bool:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE skill_record SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, datetime.now().isoformat(), skill_id),
            )
            return cursor.rowcount > 0

    def _log_event(self, skill_id: str, event_type: str, detail: str = "", session_id: Optional[str] = None) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO skill_event (id, skill_id, event_type, detail, session_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), skill_id, event_type, detail, session_id, datetime.now().isoformat()),
            )

    @staticmethod
    def _write_atomic(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".skill_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                _ = f.write(content)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _row_to_skill_record(self, row) -> SkillRecord:
        return SkillRecord(
            id=row["id"],
            name=row["name"],
            path=row["path"],
            description=row["description"],
            category=row["category"],
            status=SkillStatus(row["status"]),
            version=row["version"],
            source=row["source"],
            source_session_id=row["source_session_id"],
            success_count=row["success_count"],
            failure_count=row["failure_count"],
            last_used_at=datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None,
            review_after=datetime.fromisoformat(row["review_after"]) if row["review_after"] else None,
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_skill_candidate(self, row) -> SkillCandidate:
        return SkillCandidate(
            id=row["id"],
            title=row["title"],
            rationale=row["rationale"],
            proposed_name=row["proposed_name"],
            proposed_content=row["proposed_content"],
            source_session_id=row["source_session_id"],
            source_task_id=row["source_task_id"],
            confidence=row["confidence"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
