"""Ability unlock system based on progression."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

from core.models.pet import EvolutionStage, PetState
from core.models.personality import PetPersonality, PersonalityDimension
from core.storage.ability_repo import AbilityRepository


class AbilityType(str, Enum):
    """Types of abilities."""

    COSMETIC = "cosmetic"
    FUNCTIONAL = "functional"
    SOCIAL = "social"
    TOOL = "tool"


@dataclass
class AbilityRequirement:
    """Requirements to unlock an ability."""

    min_level: Optional[int] = None
    min_stage: Optional[EvolutionStage] = None
    min_personality: Optional[Tuple[PersonalityDimension, float]] = None
    tasks_completed: Optional[int] = None


@dataclass
class Ability:
    """A pet ability that can be unlocked."""

    id: str
    name: str
    description: str
    type: AbilityType
    requirements: AbilityRequirement
    icon: str = "default"
    unlocked_at: Optional[str] = None

    def check_unlocked(
        self, pet: PetState, personality: PetPersonality, tasks_completed: int
    ) -> bool:
        """Check if ability should be unlocked.

        Args:
            pet: Current pet state
            personality: Current pet personality
            tasks_completed: Number of tasks completed

        Returns:
            True if all requirements are met
        """
        req = self.requirements

        if req.min_level and pet.level < req.min_level:
            return False
        if req.min_stage and pet.evolution_stage.value < req.min_stage.value:
            return False
        if req.min_personality:
            trait, min_val = req.min_personality
            if getattr(personality, trait.value) < min_val:
                return False
        if req.tasks_completed and tasks_completed < req.tasks_completed:
            return False

        return True


class AbilityRegistry:
    """Registry of all abilities."""

    ABILITIES: List[Ability] = [
        Ability(
            id="advanced_chat",
            name="Advanced Chat",
            description="Can maintain longer and more complex conversations",
            type=AbilityType.FUNCTIONAL,
            requirements=AbilityRequirement(min_level=3),
            icon="chat_advanced",
        ),
        Ability(
            id="multi_task",
            name="Multi-Tasking",
            description="Can handle multiple tasks simultaneously",
            type=AbilityType.FUNCTIONAL,
            requirements=AbilityRequirement(min_level=5),
            icon="tasks",
        ),
        Ability(
            id="code_assist",
            name="Code Assistant",
            description="Enhanced code generation and debugging capabilities",
            type=AbilityType.TOOL,
            requirements=AbilityRequirement(
                min_level=4, min_personality=(PersonalityDimension.TECHNICAL_SKILL, 60.0)
            ),
            icon="code",
        ),
        Ability(
            id="creative_mode",
            name="Creative Mode",
            description="Can help with creative writing and design tasks",
            type=AbilityType.TOOL,
            requirements=AbilityRequirement(
                min_level=4, min_personality=(PersonalityDimension.CREATIVITY, 65.0)
            ),
            icon="creative",
        ),
        Ability(
            id="social_butterfly",
            name="Social Butterfly",
            description="Pet becomes more expressive and socially engaging",
            type=AbilityType.SOCIAL,
            requirements=AbilityRequirement(
                min_level=6, min_personality=(PersonalityDimension.FRIENDLINESS, 70.0)
            ),
            icon="social",
        ),
        Ability(
            id="evolution_stage2",
            name="Growth Evolution",
            description="Pet evolves to growth stage with new appearance",
            type=AbilityType.COSMETIC,
            requirements=AbilityRequirement(min_stage=EvolutionStage.STAGE_2),
            icon="evolution",
        ),
        Ability(
            id="evolution_stage3",
            name="Final Evolution",
            description="Pet reaches final form",
            type=AbilityType.COSMETIC,
            requirements=AbilityRequirement(min_stage=EvolutionStage.STAGE_3),
            icon="evolution_final",
        ),
    ]

    @classmethod
    def get_available_abilities(
        cls, pet: PetState, personality: PetPersonality, tasks_completed: int
    ) -> List[Ability]:
        """Get all abilities available to unlock.

        Args:
            pet: Current pet state
            personality: Current personality
            tasks_completed: Number of tasks completed

        Returns:
            List of abilities that meet requirements but not yet unlocked
        """
        return [
            ability
            for ability in cls.ABILITIES
            if ability.check_unlocked(pet, personality, tasks_completed) and not ability.unlocked_at
        ]

    @classmethod
    def get_ability(cls, ability_id: str) -> Optional[Ability]:
        """Get ability by ID.

        Args:
            ability_id: Ability identifier

        Returns:
            Ability if found, None otherwise
        """
        for ability in cls.ABILITIES:
            if ability.id == ability_id:
                return ability
        return None


class AbilityManager:
    """Manages ability unlocking and effects."""

    def __init__(self):
        self.unlocked_abilities: Dict[str, Ability] = {}
        self._unlock_handlers: Dict[str, Callable] = {}
        self._ability_repo = AbilityRepository()
        self._load_persisted_abilities()

    def _load_persisted_abilities(self):
        """Load previously unlocked abilities from database."""
        unlocked_ids = self._ability_repo.get_unlocked_abilities()
        for ability_id in unlocked_ids:
            ability = AbilityRegistry.get_ability(ability_id)
            if ability:
                # Create a copy to avoid mutating the registry singleton
                from dataclasses import replace

                copied = replace(ability, unlocked_at=datetime.now().isoformat())
                self.unlocked_abilities[ability_id] = copied

    def register_unlock_handler(self, ability_id: str, handler: Callable):
        """Register a callback for when ability is unlocked.

        Args:
            ability_id: Ability to watch
            handler: Function to call when unlocked
        """
        self._unlock_handlers[ability_id] = handler

    def check_and_unlock(
        self, pet: PetState, personality: PetPersonality, tasks_completed: int
    ) -> List[Ability]:
        """Check for new unlocks and trigger handlers.

        Args:
            pet: Current pet state
            personality: Current personality
            tasks_completed: Number of tasks completed

        Returns:
            List of newly unlocked abilities
        """
        newly_unlocked = []

        for ability in AbilityRegistry.get_available_abilities(pet, personality, tasks_completed):
            # Skip already unlocked abilities
            if ability.id in self.unlocked_abilities:
                continue

            # Create a copy to avoid mutating the registry singleton
            from dataclasses import replace

            copied = replace(ability, unlocked_at=datetime.now().isoformat())
            self.unlocked_abilities[ability.id] = copied
            self._ability_repo.save_unlocked_ability(ability.id)
            newly_unlocked.append(copied)

            if ability.id in self._unlock_handlers:
                self._unlock_handlers[ability.id](copied)

        return newly_unlocked

    def get_unlocked_abilities(self) -> List[Ability]:
        """Get all unlocked abilities.

        Returns:
            List of unlocked abilities
        """
        return list(self.unlocked_abilities.values())

    def is_unlocked(self, ability_id: str) -> bool:
        """Check if ability is unlocked.

        Args:
            ability_id: Ability to check

        Returns:
            True if unlocked
        """
        return ability_id in self.unlocked_abilities
