"""Game growth mechanics for Lobuddy."""

from datetime import datetime

from core.models.pet import EvolutionStage


class GrowthEngine:
    """Handles pet growth logic: EXP, levels, evolution."""

    _EXP_TABLE: tuple[int, ...] = (
        50,    # Lv1->Lv2
        120,   # Lv2->Lv3
        220,   # Lv3->Lv4
        350,   # Lv4->Lv5
        520,   # Lv5->Lv6
        720,   # Lv6->Lv7
        950,   # Lv7->Lv8
        1220,  # Lv8->Lv9
        1550,  # Lv9->Lv10
    )

    @classmethod
    def get_exp_for_next_level(cls, level: int) -> int:
        if level <= 9:
            return cls._EXP_TABLE[level - 1]
        return 9999

    @classmethod
    def get_evolution_stage_for_level(cls, level: int) -> EvolutionStage:
        return EvolutionStage(min(level // 4 + 1, 3))

    @classmethod
    def add_exp(cls, pet_state, amount: int) -> bool:
        if amount < 0:
            raise ValueError(f"EXP amount must be non-negative, got {amount}")
        pet_state.exp += amount
        pet_state.updated_at = datetime.now()

        level_up = False
        while pet_state.level < 10 and pet_state.exp >= cls.get_exp_for_next_level(pet_state.level):
            pet_state.exp -= cls.get_exp_for_next_level(pet_state.level)
            pet_state.level += 1
            level_up = True

            new_stage = cls.get_evolution_stage_for_level(pet_state.level)
            if new_stage != pet_state.evolution_stage:
                pet_state.evolution_stage = new_stage

        return level_up
