"""Database module for Lobuddy."""

import logging
import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional

from core.config import Settings
from core.storage.migrations import MigrationRunner
from core.storage.migrations.v001_initial import V001Initial

logger = logging.getLogger(__name__)


def _ensure_column(cursor, table: str, column_def: str) -> None:
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
    except sqlite3.OperationalError:
        logger.debug("Column already exists in %s, skipping migration", table)


class Database:
    """SQLite database manager."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.db_path = settings.data_dir / "lobuddy.db"
        self._ensure_directory()

    def _ensure_directory(self):
        """Ensure data directory exists."""
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.execute("PRAGMA foreign_keys")
        if cursor.fetchone()[0] != 1:
            logger.warning("SQLite foreign keys not enforced")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        with self.get_connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def init_database(self):
        """Initialize database with tables and run migrations."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Pet state table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS pet_state (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT 'Lobuddy',
                    level INTEGER NOT NULL DEFAULT 1,
                    exp INTEGER NOT NULL DEFAULT 0,
                    evolution_stage INTEGER NOT NULL DEFAULT 1,
                    mood TEXT NOT NULL DEFAULT 'happy',
                    skin TEXT NOT NULL DEFAULT 'default',
                    personality_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """
            )

            # Migration: Add personality_json column if not exists
            _ensure_column(cursor, "pet_state", "personality_json TEXT")

            # Task records table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS task_record (
                    id TEXT PRIMARY KEY,
                    input_text TEXT NOT NULL,
                    task_type TEXT NOT NULL DEFAULT 'general',
                    status TEXT NOT NULL DEFAULT 'created',
                    difficulty TEXT NOT NULL DEFAULT 'simple',
                    reward_exp INTEGER NOT NULL DEFAULT 5,
                    session_id TEXT NOT NULL DEFAULT '',
                    estimated_duration_seconds INTEGER NOT NULL DEFAULT 0,
                    estimated_token_usage INTEGER NOT NULL DEFAULT 0,
                    attempt_no INTEGER NOT NULL DEFAULT 1,
                    parent_task_id TEXT,
                    has_image INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
            """
            )
            _ensure_column(
                cursor,
                "task_record",
                "session_id TEXT NOT NULL DEFAULT ''",
            )
            _ensure_column(
                cursor,
                "task_record",
                "estimated_duration_seconds INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                cursor,
                "task_record",
                "estimated_token_usage INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                cursor,
                "task_record",
                "attempt_no INTEGER NOT NULL DEFAULT 1",
            )
            _ensure_column(cursor, "task_record", "parent_task_id TEXT")
            _ensure_column(
                cursor,
                "task_record",
                "has_image INTEGER NOT NULL DEFAULT 0",
            )

            # Task results table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS task_result (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE,
                    success INTEGER NOT NULL DEFAULT 0,
                    raw_result TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    error_message TEXT,
                    model_name TEXT NOT NULL DEFAULT '',
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0,
                    usage_source TEXT NOT NULL DEFAULT 'unavailable',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES task_record(id) ON DELETE CASCADE
                )
            """
            )
            _ensure_column(cursor, "task_result", "model_name TEXT NOT NULL DEFAULT ''")
            _ensure_column(
                cursor,
                "task_result",
                "prompt_tokens INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                cursor,
                "task_result",
                "completion_tokens INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                cursor,
                "task_result",
                "cached_tokens INTEGER NOT NULL DEFAULT 0",
            )
            _ensure_column(
                cursor,
                "task_result",
                "usage_source TEXT NOT NULL DEFAULT 'unavailable'",
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS task_run_update (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    update_key TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    stage_family TEXT NOT NULL DEFAULT '',
                    depends_on_json TEXT NOT NULL DEFAULT '[]',
                    estimated_duration_seconds INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES task_record(id) ON DELETE CASCADE
                )
            """
            )

            # App settings table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """
            )

            # User themes table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_themes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    colors_json TEXT NOT NULL,
                    source_image_path TEXT,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """
            )

            # Unlocked abilities table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS unlocked_abilities (
                    ability_id TEXT PRIMARY KEY,
                    unlocked_at TEXT NOT NULL
                )
            """
            )

            # Create indexes for performance
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_task_status ON task_record(status)
            """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_task_created ON task_record(created_at)
            """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_task_parent ON task_record(parent_task_id)
            """
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_task_single_retry
                ON task_record(parent_task_id)
                WHERE parent_task_id IS NOT NULL
            """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_task_run_update_task
                ON task_run_update(task_id, created_at)
            """
            )

            # HITL approval audit log (5.5)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS hitl_approval_log (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    command_hash TEXT NOT NULL,
                    command_preview TEXT NOT NULL,
                    working_dir TEXT,
                    affected_paths_json TEXT NOT NULL,
                    risk_tags_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    decision_reason TEXT,
                    created_at TEXT NOT NULL,
                    decided_at TEXT NOT NULL
                )
            """
            )

            conn.commit()

        self.migrate()

    def migrate(self) -> int:
        """Run pending schema migrations."""
        runner = MigrationRunner(str(self.db_path))
        runner.register(V001Initial())
        return runner.migrate()

    def get_schema_version(self) -> int:
        """Return current schema version from PRAGMA user_version."""
        with self.get_connection() as conn:
            row = conn.execute("PRAGMA user_version").fetchone()
            return row[0] if row else 0

    @staticmethod
    def set_schema_version(version: int) -> None:
        raise NotImplementedError("Use Database.migrate() to change schema version")

    def is_initialized(self) -> bool:
        if not self.db_path.exists():
            return False
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name IN ('pet_state', 'task_record', 'task_result')
                """
                )
                tables = cursor.fetchall()
                return len(tables) == 3
        except sqlite3.Error:
            return False

    def has_fts5(self) -> bool:
        try:
            with self.get_connection() as conn:
                conn.execute("CREATE VIRTUAL TABLE _fts5_test USING fts5(x)")
                conn.execute("DROP TABLE _fts5_test")
                return True
        except sqlite3.OperationalError:
            return False


# Global database instance
_db: Optional[Database] = None


def get_database(settings: Optional[Settings] = None) -> Database:
    """Get or create database instance."""
    global _db
    if _db is None:
        if settings is None:
            raise RuntimeError("Database settings required. " "Pass settings explicitly.")
        _db = Database(settings)
    return _db


def init_database(settings: Optional[Settings] = None):
    """Initialize database."""
    db = get_database(settings)
    db.init_database()
