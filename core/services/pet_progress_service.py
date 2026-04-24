"""Pet progress service for EXP, personality, and ability management."""

import threading
from PySide6.QtCore import QObject, Signal

from core.models.pet import PetState, TaskRecord, TaskResult, TaskStatus
from core.models.personality import PetPersonality
from core.abilities.ability_system import AbilityManager
from core.personality.personality_engine import PersonalityEngine
from core.storage.pet_repo import PetRepository


class PetProgressService(QObject):
    """Handles pet EXP gain, level up, personality evolution, and ability unlocks."""

    pet_exp_gained = Signal(int, int, int, bool)
    pet_level_up = Signal(int, int)
    pet_personality_changed = Signal(dict)
    ability_unlocked = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.pet_repo = PetRepository()
        self.ability_manager = AbilityManager()
        self._tasks_completed_count = 0
        self._lock = threading.Lock()

    def process_task_completion(self, task: TaskRecord, result: TaskResult) -> None:
        """Process EXP and evolution for a completed task."""
        pet = self.pet_repo.get_or_create_pet()
        required_exp = pet.get_exp_for_next_level()

        if result.success:
            level_up = pet.add_exp(task.reward_exp)
            self.pet_repo.save_pet(pet)
            self.pet_exp_gained.emit(task.reward_exp, pet.exp, required_exp, level_up)
            if level_up:
                self.pet_level_up.emit(pet.level, pet.evolution_stage.value)
        else:
            self.pet_exp_gained.emit(0, pet.exp, required_exp, False)

        if result.success:
            self._evolve_personality(task, pet)
            self._check_ability_unlocks(pet)

    def _evolve_personality(self, task: TaskRecord, pet: PetState) -> None:
        """Analyze task and apply personality adjustments."""
        personality = pet.personality if hasattr(pet, "personality") else PetPersonality()
        adjustments = PersonalityEngine.analyze_task(task, personality)
        if adjustments:
            PersonalityEngine.apply_adjustments(personality, adjustments)
            pet.personality = personality
            self.pet_repo.save_pet(pet)
            self.pet_personality_changed.emit(adjustments)

    def _check_ability_unlocks(self, pet: PetState) -> None:
        """Check and emit ability unlocks."""
        with self._lock:
            self._tasks_completed_count += 1
            tasks_count = self._tasks_completed_count
        personality = pet.personality if hasattr(pet, "personality") else PetPersonality()
        unlocked = self.ability_manager.check_and_unlock(pet, personality, tasks_count)
        for ability in unlocked:
            self.ability_unlocked.emit(ability.id, ability.name)
