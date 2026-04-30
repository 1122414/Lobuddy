"""User theme repository for Lobuddy."""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from core.storage.base_repo import BaseRepository

logger = logging.getLogger(__name__)


class ThemeRepository(BaseRepository):
    """Repository for user theme CRUD operations."""

    def get_all(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get all user themes, ordered by updated_at desc."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM user_themes ORDER BY updated_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_by_id(self, theme_id: str) -> Optional[dict[str, Any]]:
        """Get a theme by ID."""
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM user_themes WHERE id = ?",
                (theme_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_active(self) -> Optional[dict[str, Any]]:
        """Get the currently active theme."""
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM user_themes WHERE is_active = 1 LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def save(self, theme_id: str, name: str, colors: dict[str, Any],
             source: str = "manual", source_image_path: str | None = None) -> None:
        """Save or update a user theme."""
        now = datetime.now().isoformat()
        colors_json = json.dumps(colors, ensure_ascii=False)

        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO user_themes (id, name, source, colors_json, source_image_path, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    colors_json = excluded.colors_json,
                    source = excluded.source,
                    source_image_path = excluded.source_image_path,
                    updated_at = excluded.updated_at
                """,
                (theme_id, name, source, colors_json, source_image_path, now, now)
            )
            conn.commit()

    def delete(self, theme_id: str) -> bool:
        """Delete a user theme."""
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM user_themes WHERE id = ?",
                (theme_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def set_active(self, theme_id: str) -> None:
        """Set a theme as active, deactivating all others."""
        with self.db.get_connection() as conn:
            conn.execute("UPDATE user_themes SET is_active = 0")
            conn.execute(
                "UPDATE user_themes SET is_active = 1 WHERE id = ?",
                (theme_id,)
            )
            conn.commit()

    def deactivate_all(self) -> None:
        """Deactivate all themes."""
        with self.db.get_connection() as conn:
            conn.execute("UPDATE user_themes SET is_active = 0")
            conn.commit()

    def count(self) -> int:
        """Count total user themes."""
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM user_themes").fetchone()
            return row["cnt"] if row else 0
