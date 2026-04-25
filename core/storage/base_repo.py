import logging
import sqlite3
from datetime import datetime
from typing import Any, Optional

from core.storage.db import Database, get_database

logger = logging.getLogger(__name__)


def _parse_iso(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return datetime.now()


class BaseRepository:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()

    @staticmethod
    def _ensure_column(cursor, table: str, column_def: str) -> None:
        """Add column if not exists, silently skip if already present."""
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        except sqlite3.OperationalError:
            logger.debug("Column already exists in %s, skipping migration", table)
