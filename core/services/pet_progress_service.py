import threading

from core.abilities.ability_system import AbilityManager
from core.models.pet import PetProgressEvent, PetState, TaskRecord, TaskResult
from core.models.personality import PetPersonality
from core.personality.evolution import PersonalityEvolution
from core.storage.pet_repo import PetRepository


class PetProgressService:
    def __init__(
        self,
        *,
        pet_repo: PetRepository | None = None,
        ability_manager: AbilityManager | None = None,
        personality_evolution: PersonalityEvolution | None = None,
    ):
        self.pet_repo = pet_repo or PetRepository()
        self.ability_manager = ability_manager or AbilityManager()
        self.personality_evolution = personality_evolution or PersonalityEvolution(
            pets=self.pet_repo
        )
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
            event.current_exp = pet.exp
            event.required_exp = pet.get_exp_for_next_level()
            event.level_up = level_up
            if level_up:
                event.new_level = pet.level
                event.new_stage = pet.evolution_stage.value

        if result.success:
            evolution = self.personality_evolution.evolve_from_task(task, pet_id=pet.id)
            if evolution.applied:
                event.personality_adjustments = evolution.revision.adjustments
                event.personality_revision_id = evolution.revision.id
            pet = self.pet_repo.get_or_create_pet(pet.id)
            unlocked = self._check_ability_unlocks(pet)
            event.unlocked_abilities = [(a.id, a.name) for a in unlocked]

        return event

    def _check_ability_unlocks(self, pet: PetState) -> list:
        with self._lock:
            self._tasks_completed_count += 1
            tasks_count = self._tasks_completed_count
        personality = pet.personality if hasattr(pet, "personality") else PetPersonality()
        return self.ability_manager.check_and_unlock(pet, personality, tasks_count)
