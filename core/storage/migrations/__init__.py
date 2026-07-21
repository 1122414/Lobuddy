"""SQLite schema migration system.

Uses PRAGMA user_version for tracking. Each migration is a subclass of
Migration with up() and optional down() methods.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1


class Migration:
    """A single schema migration step."""

    version: int = 0
    name: str = ""

    def up(self, conn: sqlite3.Connection) -> None:
        raise NotImplementedError

    def down(self, conn: sqlite3.Connection) -> None:
        raise NotImplementedError


class MigrationRunner:
    """Runs unapplied migrations sequentially within a transaction."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._migrations: list[Migration] = []

    def register(self, migration: Migration) -> None:
        self._migrations.append(migration)
        self._migrations.sort(key=lambda m: m.version)

    def get_current_version(self) -> int:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute("PRAGMA user_version").fetchone()
            return row[0] if row else 0

    def migrate(self) -> int:
        current = self.get_current_version()
        if current >= CURRENT_SCHEMA_VERSION:
            logger.debug("Schema up to date (v%d)", current)
            return current

        for migration in self._migrations:
            if migration.version <= current:
                continue
            logger.info("Applying migration v%d: %s", migration.version, migration.name)
            with sqlite3.connect(self._db_path) as conn:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    migration.up(conn)
                    conn.execute(f"PRAGMA user_version = {migration.version}")
                    conn.commit()
                    current = migration.version
                except Exception:
                    conn.rollback()
                    logger.error(
                        "Migration v%d (%s) failed, rolled back",
                        migration.version,
                        migration.name,
                    )
                    raise

        logger.info("Schema migrated to v%d", current)
        return current
