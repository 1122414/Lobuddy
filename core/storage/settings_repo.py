"""Settings repository for database operations."""

import json
import logging
from datetime import datetime
from typing import Optional

from core.storage.crypto import decrypt_sensitive, encrypt_sensitive, is_encrypted
from core.storage.db import Database, get_database

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = {"llm_api_key", "llm_multimodal_api_key"}


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
            if row is None:
                return None
            value = row["value"]
            if key in _SENSITIVE_KEYS and is_encrypted(value):
                return decrypt_sensitive(value)
            return value

    def set_setting(self, key: str, value: str) -> None:
        """Save or update setting."""
        if key in _SENSITIVE_KEYS and value:
            value = encrypt_sensitive(value)
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
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON setting {key}: {e}")
            return default

    def set_json_setting(self, key: str, value) -> None:
        """Save setting as JSON."""
        self.set_setting(key, json.dumps(value))
