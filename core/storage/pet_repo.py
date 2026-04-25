import logging
from typing import Optional

from core.models.pet import PetState
from core.models.personality import PetPersonality
from core.storage.base_repo import BaseRepository, _parse_iso

logger = logging.getLogger(__name__)


class PetRepository(BaseRepository):
    def get_pet(self, pet_id: str = "default") -> Optional[PetState]:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM pet_state WHERE id = ?", (pet_id,)).fetchone()
            if not row:
                return None

            personality = PetPersonality()
            if row["personality_json"]:
                try:
                    personality = PetPersonality.model_validate_json(row["personality_json"])
                except Exception as e:
                    logger.warning(f"Failed to parse personality: {e}")

            return PetState(
                id=row["id"],
                name=row["name"],
                level=row["level"],
                exp=row["exp"],
                evolution_stage=row["evolution_stage"],
                mood=row["mood"],
                skin=row["skin"],
                personality=personality,
                created_at=_parse_iso(row["created_at"]),
                updated_at=_parse_iso(row["updated_at"]),
            )

    def create_default_pet(self, pet_id: str = "default") -> PetState:
        pet = PetState(id=pet_id)
        self.save_pet(pet)
        return pet

    def save_pet(self, pet: PetState) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
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
                    pet.id, pet.name, pet.level, pet.exp,
                    pet.evolution_stage, pet.mood, pet.skin,
                    pet.personality.model_dump_json(),
                    pet.created_at.isoformat(),
                    pet.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def get_or_create_pet(self, pet_id: str = "default") -> PetState:
        pet = self.get_pet(pet_id)
        if pet is None:
            pet = self.create_default_pet(pet_id)
        return pet
