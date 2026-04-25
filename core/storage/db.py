"""Database module for Lobuddy."""

import logging
import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional

from core.config import Settings

logger = logging.getLogger(__name__)


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
        """Initialize database with tables."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Pet state table
            cursor.execute("""
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
            """)

            # Migration: Add personality_json column if not exists
            try:
                cursor.execute("ALTER TABLE pet_state ADD COLUMN personality_json TEXT")
            except sqlite3.OperationalError:
                logger.debug("personality_json column already exists, skipping migration")

            # Task records table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_record (
                    id TEXT PRIMARY KEY,
                    input_text TEXT NOT NULL,
                    task_type TEXT NOT NULL DEFAULT 'general',
                    status TEXT NOT NULL DEFAULT 'created',
                    difficulty TEXT NOT NULL DEFAULT 'simple',
                    reward_exp INTEGER NOT NULL DEFAULT 5,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
            """)

            # Task results table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_result (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE,
                    success INTEGER NOT NULL DEFAULT 0,
                    raw_result TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES task_record(id) ON DELETE CASCADE
                )
            """)

            # App settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Unlocked abilities table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS unlocked_abilities (
                    ability_id TEXT PRIMARY KEY,
                    unlocked_at TEXT NOT NULL
                )
            """)

            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_status ON task_record(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_created ON task_record(created_at)
            """)

            conn.commit()

    def is_initialized(self) -> bool:
        """Check if database is initialized."""
        if not self.db_path.exists():
            return False

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name IN ('pet_state', 'task_record', 'task_result')
                """)
                tables = cursor.fetchall()
                return len(tables) == 3
        except sqlite3.Error:
            return False


# Global database instance
_db: Optional[Database] = None


def get_database(settings: Optional[Settings] = None) -> Database:
    """Get or create database instance."""
    global _db
    if _db is None:
        if settings is None:
            raise RuntimeError(
                "Database settings required. "
                "Pass settings explicitly."
            )
        _db = Database(settings)
    return _db


def init_database(settings: Optional[Settings] = None):
    """Initialize database."""
    db = get_database(settings)
    db.init_database()
