"""Pet repository for database operations."""

import json
from typing import Optional

from core.models.pet import PetState
from core.models.personality import PetPersonality
from core.storage.db import Database, get_database


class PetRepository:
    """Repository for pet state operations."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()

    def get_pet(self, pet_id: str = "default") -> Optional[PetState]:
        """Get pet state by ID."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM pet_state WHERE id = ?", (pet_id,))
            row = cursor.fetchone()

            if row:
                personality = PetPersonality()
                if row["personality_json"]:
                    try:
                        personality = PetPersonality.model_validate_json(row["personality_json"])
                    except Exception:
                        pass
                return PetState(
                    id=row["id"],
                    name=row["name"],
                    level=row["level"],
                    exp=row["exp"],
                    evolution_stage=row["evolution_stage"],
                    mood=row["mood"],
                    skin=row["skin"],
                    personality=personality,
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            return None

    def create_default_pet(self, pet_id: str = "default") -> PetState:
        """Create default pet if not exists."""
        pet = PetState(id=pet_id)
        self.save_pet(pet)
        return pet

    def save_pet(self, pet: PetState) -> None:
        """Save or update pet state."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO pet_state (id, name, level, exp, evolution_stage, mood, skin, personality_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    level = excluded.level,
                    exp = excluded.exp,
                    evolution_stage = excluded.evolution_stage,
                    mood = excluded.mood,
                    skin = excluded.skin,
                    personality_json = excluded.personality_json,
                    updated_at = excluded.updated_at
            """,
                (
                    pet.id,
                    pet.name,
                    pet.level,
                    pet.exp,
                    pet.evolution_stage,
                    pet.mood,
                    pet.skin,
                    pet.personality.model_dump_json(),
                    pet.created_at.isoformat(),
                    pet.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def get_or_create_pet(self, pet_id: str = "default") -> PetState:
        """Get existing pet or create default."""
        pet = self.get_pet(pet_id)
        if pet is None:
            pet = self.create_default_pet(pet_id)
        return pet
