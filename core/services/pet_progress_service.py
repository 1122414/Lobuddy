import threading

from core.models.pet import PetProgressEvent, PetState, TaskRecord, TaskResult, TaskStatus
from core.models.personality import PetPersonality
from core.abilities.ability_system import AbilityManager
from core.personality.personality_engine import PersonalityEngine
from core.storage.pet_repo import PetRepository


class PetProgressService:
    def __init__(self):
        self.pet_repo = PetRepository()
        self.ability_manager = AbilityManager()
        self._tasks_completed_count = 0
        self._lock = threading.Lock()

    def process_task_completion(self, task: TaskRecord, result: TaskResult) -> PetProgressEvent:
        pet = self.pet_repo.get_or_create_pet()
        required_exp = pet.get_exp_for_next_level()
        event = PetProgressEvent(current_exp=pet.exp, required_exp=required_exp)

        if result.success:
            level_up = pet.add_exp(task.reward_exp)
            self.pet_repo.save_pet(pet)
            event.exp_gained = task.reward_exp
            event.level_up = level_up
            if level_up:
                event.new_level = pet.level
                event.new_stage = pet.evolution_stage.value

        if result.success:
            adjustments = self._evolve_personality(task, pet)
            if adjustments:
                event.personality_adjustments = adjustments
            unlocked = self._check_ability_unlocks(pet)
            event.unlocked_abilities = [(a.id, a.name) for a in unlocked]

        return event

    def _evolve_personality(self, task: TaskRecord, pet: PetState) -> dict | None:
        personality = pet.personality if hasattr(pet, "personality") else PetPersonality()
        adjustments = PersonalityEngine.analyze_task(task, personality)
        if adjustments:
            PersonalityEngine.apply_adjustments(personality, adjustments)
            pet.personality = personality
            self.pet_repo.save_pet(pet)
            return adjustments
        return None

    def _check_ability_unlocks(self, pet: PetState) -> list:
        with self._lock:
            self._tasks_completed_count += 1
            tasks_count = self._tasks_completed_count
        personality = pet.personality if hasattr(pet, "personality") else PetPersonality()
        return self.ability_manager.check_and_unlock(pet, personality, tasks_count)
