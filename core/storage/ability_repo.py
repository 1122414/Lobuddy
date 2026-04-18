"""Ability repository for database operations."""

from datetime import datetime
from typing import List, Optional

from core.storage.db import Database, get_database


class AbilityRepository:
    """Repository for unlocked abilities."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()

    def save_unlocked_ability(self, ability_id: str) -> None:
        """Record an unlocked ability."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO unlocked_abilities (ability_id, unlocked_at)
                VALUES (?, ?)
                ON CONFLICT(ability_id) DO UPDATE SET
                    unlocked_at = excluded.unlocked_at
                """,
                (ability_id, datetime.now().isoformat()),
            )
            conn.commit()

    def get_unlocked_abilities(self) -> List[str]:
        """Get list of unlocked ability IDs."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ability_id FROM unlocked_abilities ORDER BY unlocked_at")
            return [row["ability_id"] for row in cursor.fetchall()]

    def is_unlocked(self, ability_id: str) -> bool:
        """Check if ability is unlocked."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM unlocked_abilities WHERE ability_id = ?",
                (ability_id,),
            )
            return cursor.fetchone() is not None

    def clear_all(self) -> None:
        """Clear all unlocked abilities (for testing)."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM unlocked_abilities")
            conn.commit()
