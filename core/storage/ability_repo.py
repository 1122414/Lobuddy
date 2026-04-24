from datetime import datetime
from typing import List, Optional

from core.storage.base_repo import BaseRepository
from core.storage.db import Database, get_database


class AbilityRepository(BaseRepository):
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()

    def save_unlocked_ability(self, ability_id: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
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
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT ability_id FROM unlocked_abilities ORDER BY unlocked_at"
            ).fetchall()
            return [row["ability_id"] for row in rows]

    def is_unlocked(self, ability_id: str) -> bool:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM unlocked_abilities WHERE ability_id = ?",
                (ability_id,),
            ).fetchone()
            return row is not None

    def clear_all(self) -> None:
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM unlocked_abilities")
            conn.commit()
