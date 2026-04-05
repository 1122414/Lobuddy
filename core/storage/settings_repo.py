"""Settings repository for database operations."""

import json
from datetime import datetime
from typing import Optional

from core.storage.db import Database, get_database


class SettingsRepository:
    """Repository for app settings operations."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()

    def get_setting(self, key: str) -> Optional[str]:
        """Get setting value by key."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Save or update setting."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """,
                (key, value, datetime.now().isoformat()),
            )
            conn.commit()

    def get_json_setting(self, key: str, default=None):
        """Get setting as JSON."""
        value = self.get_setting(key)
        if value is None:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    def set_json_setting(self, key: str, value) -> None:
        """Save setting as JSON."""
        self.set_setting(key, json.dumps(value))
