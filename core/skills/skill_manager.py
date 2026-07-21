"""Skill manager with SQLite-backed lifecycle and workspace projection."""

import difflib
import hashlib
import logging
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.config import Settings
from core.skills.skill_schema import (
    BehaviorSimulationStatus,
    CandidateSource,
    CandidateStatus,
    EvaluationCheck,
    EvaluationCheckStatus,
    EvaluationStatus,
    ProvenanceStatus,
    SkillBehaviorSimulation,
    SkillCandidate,
    SkillCandidateDiff,
    SkillCandidateProvenance,
    SkillCandidateRevision,
    SkillEvaluationReport,
    SkillEvent,
    SkillPermissionProfile,
    SkillRecord,
    SkillStatus,
)
from core.storage.base_repo import BaseRepository
from core.storage.db import Database

logger = logging.getLogger(__name__)

_VALID_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillManager(BaseRepository):
    """Manages skill lifecycle: create, patch, disable, archive, delete."""

    def __init__(self, settings: Settings, db: Optional[Database] = None) -> None:
        super().__init__(db)
        self._settings = settings
        self._workspace_skills = settings.workspace_path / "skills"
        self._archive_dir = settings.skill_archive_dir
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        self._init_tables()
        from core.skills.skill_candidate_provenance import (
            SkillCandidateProvenanceVerifier,
        )

        self._provenance_verifier = SkillCandidateProvenanceVerifier()

    def update_settings(self, settings: Settings) -> None:
        self._settings = settings

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
                    content TEXT NOT NULL DEFAULT '',
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
            self._ensure_column(
                cursor,
                "skill_record",
                "content",
                "TEXT NOT NULL DEFAULT ''",
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
                    source_kind TEXT NOT NULL DEFAULT 'manual',
                    revision INTEGER NOT NULL DEFAULT 1,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    validation_errors_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending',
                    reject_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(
                cursor,
                "skill_candidate",
                "revision",
                "INTEGER NOT NULL DEFAULT 1",
            )
            self._ensure_column(
                cursor,
                "skill_candidate",
                "source_kind",
                "TEXT NOT NULL DEFAULT 'manual'",
            )
            cursor.execute(
                """
                UPDATE skill_candidate
                SET source_kind = ?
                WHERE source_task_id IS NOT NULL
                  AND source_kind = ?
                """,
                (
                    CandidateSource.SUCCESSFUL_TASK.value,
                    CandidateSource.MANUAL.value,
                ),
            )
            self._ensure_column(
                cursor,
                "skill_candidate",
                "evidence_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                cursor,
                "skill_candidate",
                "validation_errors_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_candidate_evaluation (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    candidate_revision INTEGER NOT NULL DEFAULT 1,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    minimum_score INTEGER NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    checks_json TEXT NOT NULL DEFAULT '[]',
                    permissions_json TEXT NOT NULL DEFAULT '{}',
                    provenance_json TEXT NOT NULL DEFAULT '{}',
                    behavior_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (candidate_id)
                        REFERENCES skill_candidate(id) ON DELETE CASCADE
                )
                """
            )
            self._ensure_column(
                cursor,
                "skill_candidate_evaluation",
                "candidate_revision",
                "INTEGER NOT NULL DEFAULT 1",
            )
            self._ensure_column(
                cursor,
                "skill_candidate_evaluation",
                "provenance_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                cursor,
                "skill_candidate_evaluation",
                "behavior_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_candidate_revision (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (candidate_id)
                        REFERENCES skill_candidate(id) ON DELETE CASCADE,
                    UNIQUE(candidate_id, revision)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_skill_candidate_revision
                ON skill_candidate_revision(candidate_id, revision)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_skill_candidate_evaluation
                ON skill_candidate_evaluation(candidate_id, created_at)
                """
            )
            self._backfill_skill_content(cursor)
            self._backfill_candidate_revisions(cursor)
            conn.commit()

    @staticmethod
    def _ensure_column(cursor, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _backfill_skill_content(self, cursor) -> None:
        rows = cursor.execute(
            "SELECT id, name, path FROM skill_record WHERE content = ''"
        ).fetchall()
        for row in rows:
            try:
                path = self._managed_skill_file(
                    row["name"],
                    stored_path=row["path"],
                )
            except ValueError:
                logger.warning(
                    "Skipped unsafe skill content backfill: id=%s",
                    row["id"],
                )
                continue
            if not path.is_file() or path.is_symlink():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            cursor.execute(
                "UPDATE skill_record SET content = ? WHERE id = ?",
                (content, row["id"]),
            )

    @staticmethod
    def _backfill_candidate_revisions(cursor) -> None:
        rows = cursor.execute(
            """
            SELECT candidate.id, candidate.revision,
                   candidate.proposed_content, candidate.created_at
            FROM skill_candidate AS candidate
            LEFT JOIN skill_candidate_revision AS revision
              ON revision.candidate_id = candidate.id
             AND revision.revision = candidate.revision
            WHERE revision.id IS NULL
            """
        ).fetchall()
        for row in rows:
            content = row["proposed_content"]
            cursor.execute(
                """
                INSERT INTO skill_candidate_revision (
                    id, candidate_id, revision, content_hash,
                    content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    row["id"],
                    row["revision"],
                    hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    content,
                    row["created_at"],
                ),
            )

    def create_skill(self, record: SkillRecord, content: str) -> SkillRecord:
        skill_file = self._managed_skill_file(record.name)
        if skill_file.exists():
            raise FileExistsError(f"Skill projection already exists: {record.name}")
        skill_file.parent.mkdir(parents=True, exist_ok=False)
        self._write_atomic(skill_file, content)
        record.path = str(skill_file)
        record.content = content
        record.updated_at = datetime.now()
        self._save_record(record)
        self._log_event(record.id, "create", f"Created skill {record.name}")
        return record

    def patch_skill(
        self, skill_id: str, new_content: str, description: Optional[str] = None
    ) -> bool:
        record = self.get_skill(skill_id)
        if not record:
            return False
        try:
            skill_file = self._managed_skill_file(
                record.name,
                stored_path=record.path,
            )
        except ValueError:
            logger.warning("Refused unsafe skill patch: id=%s", skill_id)
            return False
        self._write_atomic(skill_file, new_content)
        record.content = new_content
        record.version += 1
        if description:
            record.description = description
        record.updated_at = datetime.now()
        self._save_record(record)
        self._log_event(skill_id, "patch", f"Updated to v{record.version}")
        return True

    def enable_skill(self, skill_id: str) -> bool:
        record = self.get_skill(skill_id)
        if not record or record.status not in (SkillStatus.DISABLED, SkillStatus.NEEDS_REVIEW):
            return False
        try:
            skill_file = self._managed_skill_file(
                record.name,
                stored_path=record.path,
            )
        except ValueError:
            logger.warning("Refused unsafe skill enable: id=%s", skill_id)
            return False
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        if not skill_file.exists():
            content = record.content or "# " + record.name + "\n\n" + record.description
            self._write_atomic(skill_file, content)
        record.path = str(skill_file)
        record.status = SkillStatus.ACTIVE
        record.updated_at = datetime.now()
        self._save_record(record)
        self._log_event(skill_id, "enable", "Skill enabled")
        return True

    def disable_skill(self, skill_id: str) -> bool:
        record = self.get_skill(skill_id)
        if not record:
            return False
        try:
            skill_file = self._managed_skill_file(
                record.name,
                stored_path=record.path,
            )
        except ValueError:
            logger.warning("Refused unsafe skill disable: id=%s", skill_id)
            return False
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
        try:
            src = self._managed_skill_file(
                record.name,
                stored_path=record.path,
            )
        except ValueError:
            logger.warning("Refused unsafe skill archive: id=%s", skill_id)
            return False
        if src.exists():
            archive_root = self._archive_dir.resolve()
            archive_root.mkdir(parents=True, exist_ok=True)
            dst = archive_root / f"{record.name}_v{record.version}.md"
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
        try:
            skill_file = self._managed_skill_file(
                record.name,
                stored_path=record.path,
            )
        except ValueError:
            logger.warning("Refused unsafe skill delete: id=%s", skill_id)
            return False
        if skill_file.exists():
            skill_file.unlink()
        parent = skill_file.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM skill_event WHERE skill_id = ?", (skill_id,))
            conn.execute("DELETE FROM skill_record WHERE id = ?", (skill_id,))
        return True

    def get_content(self, skill_id: str) -> str:
        record = self.get_skill(skill_id)
        if not record or not record.path:
            return ""
        try:
            path = self._managed_skill_file(
                record.name,
                stored_path=record.path,
            )
        except ValueError:
            logger.warning("Refused unsafe skill read: id=%s", skill_id)
            return ""
        if not path.exists():
            return record.content
        content = path.read_text(encoding="utf-8")
        if content != record.content:
            record.content = content
            record.updated_at = datetime.now()
            self._save_record(record)
        return content

    def get_events(self, skill_id: str, limit: int = 50) -> list[SkillEvent]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_event WHERE skill_id = ? ORDER BY created_at DESC LIMIT ?",
                (skill_id, limit),
            ).fetchall()
            return [self._row_to_skill_event(r) for r in rows]

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
            elif (
                skill.failure_rate() >= self._settings.skill_failure_rate_threshold
                and (skill.success_count + skill.failure_count)
                >= self._settings.skill_failure_rate_min_uses
            ):
                self._update_status(skill.id, SkillStatus.NEEDS_REVIEW)
                stale.append(skill)
        return stale

    def cleanup_orphan_workspace_files(self) -> int:
        """Remove stale projections only for explicitly inactive managed skills.

        Workspace skills can also be installed directly by users or external
        tooling, so an unknown directory is never proof that a file is an
        orphan. This method only removes projections belonging to a database
        record already marked disabled or archived.
        """
        workspace = self._workspace_skills
        if not workspace.exists():
            return 0
        workspace = workspace.resolve()

        removed = 0
        for skill_dir in workspace.iterdir():
            if not skill_dir.is_dir():
                continue
            try:
                resolved_dir = skill_dir.resolve(strict=True)
            except OSError:
                continue
            if resolved_dir.parent != workspace:
                logger.warning("SkillMaintenance: skipped escaped skill directory %s", skill_dir)
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists() or skill_md.is_symlink():
                continue

            skill_name = skill_dir.name
            existing = self.get_skill_by_name(skill_name)
            if existing is None:
                logger.debug(
                    "SkillMaintenance: preserving unmanaged workspace skill %s", skill_name
                )
                continue
            if existing.status not in (SkillStatus.DISABLED, SkillStatus.ARCHIVED):
                continue

            try:
                resolved_skill = skill_md.resolve(strict=True)
                if resolved_skill.parent != resolved_dir:
                    logger.warning("SkillMaintenance: skipped escaped skill file %s", skill_md)
                    continue
                resolved_skill.unlink()
                logger.info("SkillMaintenance: removed orphan workspace file %s", skill_md)
                removed += 1
                remaining = list(skill_dir.iterdir())
                if not remaining:
                    skill_dir.rmdir()
            except OSError as exc:
                logger.warning("SkillMaintenance: failed to remove orphan %s: %s", skill_md, exc)

        return removed

    def create_candidate(
        self,
        candidate: SkillCandidate,
        *,
        defer_evaluation: bool = False,
    ) -> SkillCandidate:
        if candidate.source_task_id and candidate.source_kind == CandidateSource.MANUAL:
            candidate.source_kind = CandidateSource.SUCCESSFUL_TASK
        candidate.revision = 1
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO skill_candidate (
                    id, title, rationale, proposed_name, proposed_content,
                    source_session_id, source_task_id, source_kind, revision,
                    confidence, evidence_json,
                    validation_errors_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.id,
                    candidate.title,
                    candidate.rationale,
                    candidate.proposed_name,
                    candidate.proposed_content,
                    candidate.source_session_id,
                    candidate.source_task_id,
                    candidate.source_kind.value,
                    candidate.revision,
                    candidate.confidence,
                    json.dumps(candidate.evidence, ensure_ascii=False),
                    json.dumps(candidate.validation_errors, ensure_ascii=False),
                    candidate.status.value,
                    candidate.created_at.isoformat(),
                    candidate.updated_at.isoformat(),
                ),
            )
            self._insert_candidate_revision(
                conn,
                SkillCandidateRevision(
                    id=str(uuid.uuid4()),
                    candidate_id=candidate.id,
                    revision=candidate.revision,
                    content_hash=hashlib.sha256(
                        candidate.proposed_content.encode("utf-8")
                    ).hexdigest(),
                    content=candidate.proposed_content,
                    created_at=candidate.created_at,
                ),
            )
        if self._settings.skill_evaluation_enabled and not defer_evaluation:
            try:
                self.evaluate_candidate(candidate.id)
            except Exception as exc:
                logger.warning(
                    "Skill candidate evaluation failed: id=%s error=%s",
                    candidate.id,
                    exc,
                )
        return candidate

    def find_candidate_by_name(
        self,
        proposed_name: str,
        statuses: tuple[CandidateStatus, ...] = (
            CandidateStatus.PENDING,
            CandidateStatus.APPROVED,
        ),
    ) -> Optional[SkillCandidate]:
        placeholders = ", ".join("?" for _ in statuses)
        params = [proposed_name, *(status.value for status in statuses)]
        with self.db.get_connection() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM skill_candidate
                WHERE proposed_name = ? AND status IN ({placeholders})
                ORDER BY created_at DESC LIMIT 1
                """,
                params,
            ).fetchone()
        return self._row_to_skill_candidate(row) if row else None

    def get_candidate(self, candidate_id: str) -> Optional[SkillCandidate]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM skill_candidate WHERE id = ?", (candidate_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_skill_candidate(row)

    def list_candidates(
        self, status: Optional[str] = None, limit: int = 50
    ) -> list[SkillCandidate]:
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

    def update_candidate_content(
        self,
        candidate_id: str,
        content: str,
    ) -> Optional[SkillCandidate]:
        """Create an immutable candidate revision and refresh its evaluation."""
        candidate = self.get_candidate(candidate_id)
        if candidate is None or candidate.status != CandidateStatus.PENDING:
            return None
        proposed_content = str(content)
        if proposed_content == candidate.proposed_content:
            return candidate

        from core.skills.skill_validator import SkillValidator

        validator = SkillValidator()
        valid_candidate, candidate_errors = validator.validate(
            candidate.model_copy(update={"proposed_content": proposed_content})
        )
        valid_static, static_errors = validator.validate_static(proposed_content)
        validation_errors = list(dict.fromkeys([*candidate_errors, *static_errors]))
        if valid_candidate and valid_static:
            validation_errors = []

        now = datetime.now()
        next_revision = candidate.revision + 1
        revision = SkillCandidateRevision(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            revision=next_revision,
            content_hash=hashlib.sha256(proposed_content.encode("utf-8")).hexdigest(),
            content=proposed_content,
            created_at=now,
        )
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE skill_candidate
                SET proposed_content = ?, revision = ?,
                    validation_errors_json = ?, updated_at = ?
                WHERE id = ? AND status = ? AND revision = ?
                """,
                (
                    proposed_content,
                    next_revision,
                    json.dumps(validation_errors, ensure_ascii=False),
                    now.isoformat(),
                    candidate.id,
                    CandidateStatus.PENDING.value,
                    candidate.revision,
                ),
            )
            if cursor.rowcount != 1:
                return None
            self._insert_candidate_revision(conn, revision)

        updated = self.get_candidate(candidate.id)
        if updated is not None and self._settings.skill_evaluation_enabled:
            try:
                self.evaluate_candidate(updated.id)
            except Exception as exc:
                logger.warning(
                    "Updated skill candidate evaluation failed: id=%s error=%s",
                    updated.id,
                    exc,
                )
        return updated

    def list_candidate_revisions(
        self,
        candidate_id: str,
        limit: int = 50,
    ) -> list[SkillCandidateRevision]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM skill_candidate_revision
                WHERE candidate_id = ?
                ORDER BY revision DESC
                LIMIT ?
                """,
                (candidate_id, max(1, min(200, limit))),
            ).fetchall()
        return [self._row_to_candidate_revision(row) for row in rows]

    def get_candidate_diff(
        self,
        candidate_id: str,
    ) -> Optional[SkillCandidateDiff]:
        revisions = self.list_candidate_revisions(candidate_id, limit=2)
        if not revisions:
            return None
        current = revisions[0]
        if len(revisions) == 1:
            return SkillCandidateDiff(
                from_revision=current.revision,
                to_revision=current.revision,
            )
        previous = revisions[1]
        lines = list(
            difflib.unified_diff(
                previous.content.splitlines(),
                current.content.splitlines(),
                fromfile=f"revision-{previous.revision}",
                tofile=f"revision-{current.revision}",
                lineterm="",
                n=3,
            )
        )
        added = sum(line.startswith("+") and not line.startswith("+++") for line in lines)
        removed = sum(line.startswith("-") and not line.startswith("---") for line in lines)
        return SkillCandidateDiff(
            from_revision=previous.revision,
            to_revision=current.revision,
            added_lines=added,
            removed_lines=removed,
            changed=bool(added or removed),
            unified_diff="\n".join(lines)[:20_000],
        )

    def approve_candidate(self, candidate_id: str) -> Optional[SkillRecord]:
        candidate = self.get_candidate(candidate_id)
        if not candidate or candidate.status != CandidateStatus.PENDING:
            return None
        if candidate.confidence < self._settings.skill_candidate_min_confidence:
            return None
        report = self.get_latest_candidate_evaluation(
            candidate.id,
            current_content_only=True,
        )
        if candidate.source_kind == CandidateSource.SUCCESSFUL_TASK:
            report = self.evaluate_candidate(candidate.id)
        if (
            report is None
            or report.candidate_revision != candidate.revision
            or report.behavior.status != BehaviorSimulationStatus.PASSED
        ):
            report = self.evaluate_candidate(candidate.id)
        if (
            report is None
            or report.status != EvaluationStatus.PASSED
            or report.score < self._settings.skill_evaluation_min_score
            or report.candidate_revision != candidate.revision
            or report.behavior.status != BehaviorSimulationStatus.PASSED
            or (
                candidate.source_kind == CandidateSource.SUCCESSFUL_TASK
                and report.provenance.status != ProvenanceStatus.VERIFIED
            )
        ):
            return None
        from core.skills.skill_validator import SkillValidator

        validator = SkillValidator()
        valid, errors = validator.validate(candidate)
        if not valid:
            return None
        valid_static, static_errors = validator.validate_static(candidate.proposed_content)
        if not valid_static or errors or static_errors:
            return None
        if not _VALID_SKILL_NAME.fullmatch(candidate.proposed_name):
            return None
        if self.get_skill_by_name(candidate.proposed_name) is not None:
            return None

        workspace = self._workspace_skills.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        skill_dir = workspace / candidate.proposed_name
        if skill_dir.parent != workspace:
            return None
        try:
            skill_dir.mkdir()
        except FileExistsError:
            return None
        skill_file = skill_dir / "SKILL.md"

        record = SkillRecord(
            id=str(uuid.uuid4()),
            name=candidate.proposed_name,
            path=str(skill_file),
            description=candidate.title,
            content=candidate.proposed_content,
            status=SkillStatus.ACTIVE,
            source="auto",
            source_session_id=candidate.source_session_id,
        )
        now = datetime.now()
        record.updated_at = now
        staged_path: Optional[Path] = None
        database_committed = False
        try:
            staged_path = self._write_staged(
                skill_dir,
                candidate.proposed_content,
            )
            with self.db.transaction() as conn:
                self._insert_record(conn, record)
                self._insert_event(
                    conn,
                    record.id,
                    "create",
                    (
                        f"Approved evaluated candidate {candidate.id} "
                        f"revision {candidate.revision}"
                    ),
                    candidate.source_session_id,
                )
                cursor = conn.execute(
                    """
                    UPDATE skill_candidate
                    SET status = ?, updated_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        CandidateStatus.APPROVED.value,
                        now.isoformat(),
                        candidate_id,
                        CandidateStatus.PENDING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Candidate approval state changed")
            database_committed = True
            os.replace(staged_path, skill_file)
        except Exception as exc:
            logger.warning(
                "Candidate approval rolled back: id=%s error=%s",
                candidate.id,
                exc,
            )
            if database_committed:
                try:
                    with self.db.transaction() as conn:
                        conn.execute(
                            "DELETE FROM skill_event WHERE skill_id = ?",
                            (record.id,),
                        )
                        conn.execute(
                            "DELETE FROM skill_record WHERE id = ?",
                            (record.id,),
                        )
                        conn.execute(
                            """
                            UPDATE skill_candidate
                            SET status = ?, updated_at = ?
                            WHERE id = ? AND status = ?
                            """,
                            (
                                CandidateStatus.PENDING.value,
                                datetime.now().isoformat(),
                                candidate.id,
                                CandidateStatus.APPROVED.value,
                            ),
                        )
                except Exception:
                    logger.exception(
                        "Failed to compensate candidate approval: %s",
                        candidate.id,
                    )
            try:
                if staged_path is not None and staged_path.exists():
                    staged_path.unlink()
                if skill_file.exists():
                    skill_file.unlink()
                if skill_dir.exists() and not any(skill_dir.iterdir()):
                    skill_dir.rmdir()
            except OSError:
                logger.warning(
                    "Failed to clean candidate projection after rollback: %s",
                    skill_dir,
                )
            return None
        return record

    def evaluate_candidate(
        self,
        candidate_id: str,
    ) -> Optional[SkillEvaluationReport]:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            return None
        from core.skills.skill_evaluation_service import (
            SkillEvaluationService,
        )

        provenance = self._verify_candidate_provenance(candidate)
        report = SkillEvaluationService(self._settings).evaluate(
            candidate,
            provenance=provenance,
        )
        self.save_candidate_evaluation(report)
        return report

    def _verify_candidate_provenance(
        self,
        candidate: SkillCandidate,
    ) -> SkillCandidateProvenance:
        if candidate.source_kind != CandidateSource.SUCCESSFUL_TASK:
            return self._provenance_verifier.verify(candidate)
        from core.skills.skill_candidate_provenance import (
            SkillCandidateProvenanceVerifier,
        )
        from core.storage.execution_trace_repository import (
            ExecutionTraceRepository,
        )
        from core.storage.task_repo import TaskRepository

        try:
            verifier = SkillCandidateProvenanceVerifier(
                TaskRepository(self.db),
                ExecutionTraceRepository(self.db),
            )
            return verifier.verify(candidate)
        except Exception as exc:
            logger.warning(
                "Skill candidate provenance reader unavailable: id=%s error=%s",
                candidate.id,
                exc,
            )
            return self._provenance_verifier.verify(candidate)

    def save_candidate_evaluation(
        self,
        report: SkillEvaluationReport,
    ) -> SkillEvaluationReport:
        if self.get_candidate(report.candidate_id) is None:
            raise ValueError("Skill candidate does not exist")
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO skill_candidate_evaluation (
                    id, candidate_id, candidate_revision,
                    content_hash, status, score,
                    minimum_score, summary, checks_json,
                    permissions_json, provenance_json,
                    behavior_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.id,
                    report.candidate_id,
                    report.candidate_revision,
                    report.content_hash,
                    report.status.value,
                    report.score,
                    report.minimum_score,
                    report.summary,
                    json.dumps(
                        [check.model_dump(mode="json") for check in report.checks],
                        ensure_ascii=False,
                    ),
                    report.permissions.model_dump_json(),
                    report.provenance.model_dump_json(),
                    report.behavior.model_dump_json(),
                    report.created_at.isoformat(),
                ),
            )
        return report

    def get_latest_candidate_evaluation(
        self,
        candidate_id: str,
        *,
        current_content_only: bool = False,
    ) -> Optional[SkillEvaluationReport]:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            return None
        params: list[object] = [candidate_id]
        content_filter = ""
        if current_content_only:
            from core.skills.skill_evaluation_service import (
                SkillEvaluationService,
            )

            content_filter = " AND content_hash = ? AND candidate_revision = ?"
            params.append(SkillEvaluationService.content_hash(candidate.proposed_content))
            params.append(candidate.revision)
        with self.db.get_connection() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM skill_candidate_evaluation
                WHERE candidate_id = ?{content_filter}
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return self._row_to_evaluation(row) if row else None

    def reject_candidate(self, candidate_id: str, reason: str = "") -> bool:
        candidate = self.get_candidate(candidate_id)
        if not candidate or candidate.status != CandidateStatus.PENDING:
            return False
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE skill_candidate
                SET status = ?, reject_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (CandidateStatus.REJECTED.value, reason, datetime.now().isoformat(), candidate_id),
            )
        return True

    def validate_skill(self, skill_id: str) -> tuple[bool, list[str]]:
        from core.skills.skill_validator import SkillValidator

        content = self.get_content(skill_id)
        if not content:
            return False, ["Skill content not found"]
        validator = SkillValidator()
        return validator.validate_static(content)

    def get_pending_candidates(self, limit: int = 50) -> list[SkillCandidate]:
        return self.list_candidates(status=CandidateStatus.PENDING.value, limit=limit)

    def get_candidate_stats(self) -> dict[str, int]:
        with self.db.get_connection() as conn:
            cursor = conn.execute("SELECT status, COUNT(*) FROM skill_candidate GROUP BY status")
            stats = {row[0]: row[1] for row in cursor.fetchall()}
        return {
            "pending": stats.get(CandidateStatus.PENDING.value, 0),
            "approved": stats.get(CandidateStatus.APPROVED.value, 0),
            "rejected": stats.get(CandidateStatus.REJECTED.value, 0),
            "converted": stats.get(CandidateStatus.CONVERTED.value, 0),
        }

    def _save_record(self, record: SkillRecord) -> None:
        with self.db.transaction() as conn:
            self._insert_record(conn, record, replace=True)

    @staticmethod
    def _insert_record(conn, record: SkillRecord, *, replace: bool = False) -> None:
        operation = "INSERT OR REPLACE" if replace else "INSERT"
        conn.execute(
            f"""
            {operation} INTO skill_record (
                id, name, path, description, content, category, status, version, source,
                source_session_id, success_count, failure_count, last_used_at,
                review_after, expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.name,
                record.path,
                record.description,
                record.content,
                record.category,
                record.status.value,
                record.version,
                record.source,
                record.source_session_id,
                record.success_count,
                record.failure_count,
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

    def _log_event(
        self, skill_id: str, event_type: str, detail: str = "", session_id: Optional[str] = None
    ) -> None:
        with self.db.transaction() as conn:
            self._insert_event(
                conn,
                skill_id,
                event_type,
                detail,
                session_id,
            )

    @staticmethod
    def _insert_event(
        conn,
        skill_id: str,
        event_type: str,
        detail: str = "",
        session_id: Optional[str] = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO skill_event (
                id, skill_id, event_type, detail, session_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                skill_id,
                event_type,
                detail,
                session_id,
                datetime.now().isoformat(),
            ),
        )

    @staticmethod
    def _insert_candidate_revision(
        conn,
        revision: SkillCandidateRevision,
    ) -> None:
        conn.execute(
            """
            INSERT INTO skill_candidate_revision (
                id, candidate_id, revision, content_hash,
                content, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                revision.id,
                revision.candidate_id,
                revision.revision,
                revision.content_hash,
                revision.content,
                revision.created_at.isoformat(),
            ),
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

    @staticmethod
    def _write_staged(directory: Path, content: str) -> Path:
        """Write a non-loadable temporary projection for later publication."""
        fd, temp_path = tempfile.mkstemp(
            dir=directory,
            prefix=".candidate_",
            suffix=".tmp",
        )
        path = Path(temp_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                _ = file.write(content)
            return path
        except BaseException:
            try:
                path.unlink()
            except OSError:
                pass
            raise

    def _managed_skill_file(
        self,
        name: str,
        *,
        stored_path: str = "",
    ) -> Path:
        """Return the only managed projection path or reject an escape."""
        if not _VALID_SKILL_NAME.fullmatch(name):
            raise ValueError("Invalid managed skill name")
        workspace = self._workspace_skills.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        skill_dir = workspace / name
        if skill_dir.exists():
            if skill_dir.is_symlink() or skill_dir.resolve() != skill_dir:
                raise ValueError("Managed skill directory escaped workspace")
            if skill_dir.resolve().parent != workspace:
                raise ValueError("Managed skill directory escaped workspace")
        skill_file = skill_dir / "SKILL.md"
        if skill_file.is_symlink():
            raise ValueError("Managed skill file cannot be a symlink")
        if stored_path:
            stored = Path(stored_path).resolve(strict=False)
            if stored != skill_file.resolve(strict=False):
                raise ValueError("Stored skill path is outside managed workspace")
        return skill_file

    def _row_to_skill_record(self, row) -> SkillRecord:
        return SkillRecord(
            id=row["id"],
            name=row["name"],
            path=row["path"],
            description=row["description"],
            content=row["content"] if "content" in row.keys() else "",
            category=row["category"],
            status=SkillStatus(row["status"]),
            version=row["version"],
            source=row["source"],
            source_session_id=row["source_session_id"],
            success_count=row["success_count"],
            failure_count=row["failure_count"],
            last_used_at=(
                datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None
            ),
            review_after=(
                datetime.fromisoformat(row["review_after"]) if row["review_after"] else None
            ),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_skill_candidate(self, row) -> SkillCandidate:
        reject_reason = None
        if "reject_reason" in row.keys():
            reject_reason = row["reject_reason"] if row["reject_reason"] else None
        return SkillCandidate(
            id=row["id"],
            title=row["title"],
            rationale=row["rationale"],
            proposed_name=row["proposed_name"],
            proposed_content=row["proposed_content"],
            source_session_id=row["source_session_id"],
            source_task_id=row["source_task_id"],
            source_kind=CandidateSource(
                row["source_kind"]
                if "source_kind" in row.keys() and row["source_kind"]
                else CandidateSource.MANUAL.value
            ),
            revision=(row["revision"] if "revision" in row.keys() and row["revision"] else 1),
            confidence=row["confidence"],
            evidence=(
                json.loads(row["evidence_json"])
                if "evidence_json" in row.keys() and row["evidence_json"]
                else {}
            ),
            validation_errors=(
                json.loads(row["validation_errors_json"])
                if "validation_errors_json" in row.keys() and row["validation_errors_json"]
                else []
            ),
            status=CandidateStatus(row["status"]),
            reject_reason=reject_reason,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_evaluation(row) -> SkillEvaluationReport:
        checks_data = json.loads(row["checks_json"] or "[]")
        permissions_data = json.loads(row["permissions_json"] or "{}")
        provenance_data = (
            json.loads(row["provenance_json"] or "{}") if "provenance_json" in row.keys() else {}
        )
        behavior_data = (
            json.loads(row["behavior_json"] or "{}") if "behavior_json" in row.keys() else {}
        )
        return SkillEvaluationReport(
            id=row["id"],
            candidate_id=row["candidate_id"],
            candidate_revision=(
                row["candidate_revision"]
                if "candidate_revision" in row.keys() and row["candidate_revision"]
                else 1
            ),
            content_hash=row["content_hash"],
            status=EvaluationStatus(row["status"]),
            score=row["score"],
            minimum_score=row["minimum_score"],
            summary=row["summary"],
            checks=[
                EvaluationCheck(
                    **{
                        **item,
                        "status": EvaluationCheckStatus(item["status"]),
                    }
                )
                for item in checks_data
            ],
            permissions=SkillPermissionProfile(**permissions_data),
            provenance=SkillCandidateProvenance(**provenance_data),
            behavior=SkillBehaviorSimulation(**behavior_data),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_candidate_revision(row) -> SkillCandidateRevision:
        return SkillCandidateRevision(
            id=row["id"],
            candidate_id=row["candidate_id"],
            revision=row["revision"],
            content_hash=row["content_hash"],
            content=row["content"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_skill_event(self, row) -> SkillEvent:
        return SkillEvent(
            id=row["id"],
            skill_id=row["skill_id"],
            event_type=row["event_type"],
            detail=row["detail"],
            session_id=row["session_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
