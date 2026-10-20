"""Idempotent turn settlement and observed model usage, independent of UI lifetime."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from core.abilities.ability_system import AbilityRegistry
from core.models.pet import PetProgressEvent, PetState, TaskRecord
from core.personality.personality_engine import PersonalityEngine
from core.service.outcomes import OutcomeRepository
from core.service.protocol import TurnState
from core.storage.db import Database
from core.storage.desktop_migrations import migrate_desktop
from core.storage.pet_repo import PetRepository
from core.tasks.classification import determine_task_difficulty


class ObservedUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    inputTokens: int = Field(ge=0)
    outputTokens: int = Field(ge=0)
    cacheReadTokens: int = Field(default=0, ge=0)
    cacheWriteTokens: int = Field(default=0, ge=0)


class UsageTotals(BaseModel):
    input: int
    output: int
    cached: int
    calls: int


class AbilityView(BaseModel):
    id: str
    name: str
    description: str
    type: str
    unlocked_at: str | None
    min_level: int | None
    min_stage: int | None
    trait: str | None
    trait_value: float | None
    tasks_completed: int | None


class ProgressOverview(BaseModel):
    completed_tasks: int
    usage: UsageTotals
    abilities: list[AbilityView]
    pet: PetState


class RuntimeLedger:
    def __init__(self, db: Database) -> None:
        self.db = db
        migrate_desktop(db)
        self.pet = PetRepository(db)
        self.outcomes = OutcomeRepository(db)

    def record_skill_use(self, state: TurnState, skill_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO skill_use VALUES (?, ?)", (state.task_id, skill_id))

    def usage(self, state: TurnState, sequence: int, data: dict[str, JsonValue]) -> None:
        value = ObservedUsage.model_validate(data)
        cached = value.cacheReadTokens + value.cacheWriteTokens
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO model_usage VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    state.turn_id,
                    sequence,
                    state.session_id,
                    value.inputTokens + cached,
                    value.outputTokens,
                    cached,
                    datetime.now().isoformat(),
                ),
            )

    def settle(self, state: TurnState) -> PetProgressEvent:
        if state.status in ("queued", "running"):
            raise ValueError("任务尚未结束，不能结算")
        with self.db.transaction() as conn:
            previous = conn.execute(
                "SELECT progress_json FROM turn_settlement WHERE task_id=?", (state.task_id,)
            ).fetchone()
            if previous:
                return PetProgressEvent.model_validate_json(previous["progress_json"])
            pet = self.pet.get_pet(connection=conn) or PetState()
            progress = PetProgressEvent(
                current_exp=pet.exp, required_exp=pet.get_exp_for_next_level()
            )
            difficulty, reward = determine_task_difficulty(state.input_text)
            task = TaskRecord(
                id=state.task_id,
                input_text=state.input_text,
                difficulty=difficulty,
                reward_exp=reward,
            )
            now = datetime.now().isoformat()
            status = {
                "completed": "success",
                "failed": "failed",
                "cancelled": "cancelled",
                "interrupted": "cancelled",
            }[state.status]
            legacy_task = conn.execute(
                "SELECT id FROM task_record WHERE id=?", (state.task_id,)
            ).fetchone()
            conn.execute(
                """INSERT OR IGNORE INTO task_record
                (id,input_text,task_type,status,difficulty,reward_exp,created_at,finished_at)
                VALUES (?,?,'general',?,?,?,?,?)""",
                (state.task_id, state.input_text, status, difficulty.value, reward, now, now),
            )
            conn.execute(
                """INSERT OR IGNORE INTO task_result
                (task_id,success,raw_result,summary,error_message,created_at) VALUES (?,?,?,?,?,?)""",
                (
                    state.task_id,
                    int(state.status == "completed"),
                    state.output_text,
                    state.output_text,
                    state.error,
                    now,
                ),
            )
            if state.status == "completed" and legacy_task is None:
                progress.level_up = pet.add_exp(reward)
                progress.exp_gained = reward
                if progress.level_up:
                    progress.new_level = pet.level
                    progress.new_stage = pet.evolution_stage.value
                adjustments = PersonalityEngine.analyze_task(task, pet.personality)
                PersonalityEngine.apply_adjustments(pet.personality, adjustments)
                progress.personality_adjustments = adjustments
                count = conn.execute(
                    "SELECT COUNT(*) FROM task_record WHERE status='success'"
                ).fetchone()[0]
                for ability in AbilityRegistry.get_available_abilities(pet, pet.personality, count):
                    inserted = conn.execute(
                        "INSERT OR IGNORE INTO unlocked_abilities VALUES (?, ?)", (ability.id, now)
                    )
                    if inserted.rowcount:
                        progress.unlocked_abilities.append((ability.id, ability.name))
            progress.current_exp = pet.exp
            progress.required_exp = pet.get_exp_for_next_level()
            self.pet.save_pet(pet, connection=conn)
            # Reading a skill is usage, not evidence that it caused a successful result.
            conn.execute(
                "INSERT INTO turn_settlement VALUES (?, ?, ?, ?, ?)",
                (state.task_id, state.turn_id, state.status, progress.model_dump_json(), now),
            )
            return progress

    def recover(self) -> None:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """SELECT t.state_json FROM service_turn t
                LEFT JOIN turn_settlement s ON s.turn_id=t.turn_id WHERE s.turn_id IS NULL"""
            ).fetchall()
        for row in rows:
            state = TurnState.model_validate_json(row["state_json"])
            if state.status not in ("queued", "running"):
                self.outcomes.finish_turn(state.turn_id, state.status)
                self.settle(state)

    def summary(self) -> dict[str, JsonValue]:
        with self.db.get_connection() as conn:
            usage = conn.execute("""SELECT COALESCE(SUM(input_tokens),0) AS input,
                COALESCE(SUM(output_tokens),0) AS output,COALESCE(SUM(cached_tokens),0) AS cached,
                COUNT(*) AS calls FROM model_usage""").fetchone()
            completed = conn.execute(
                "SELECT COUNT(*) FROM task_record WHERE status='success'"
            ).fetchone()[0]
            unlocked = {
                row["ability_id"]: row["unlocked_at"]
                for row in conn.execute("SELECT * FROM unlocked_abilities")
            }
        abilities: list[AbilityView] = []
        for ability in AbilityRegistry.ABILITIES:
            requirement = ability.requirements
            trait = requirement.min_personality
            abilities.append(
                AbilityView(
                    id=ability.id,
                    name=ability.name,
                    description=ability.description,
                    type=ability.type.value,
                    unlocked_at=unlocked.get(ability.id),
                    min_level=requirement.min_level,
                    min_stage=requirement.min_stage.value if requirement.min_stage else None,
                    trait=trait[0].value if trait else None,
                    trait_value=trait[1] if trait else None,
                    tasks_completed=requirement.tasks_completed,
                )
            )
        return ProgressOverview(
            completed_tasks=completed,
            usage=UsageTotals(**dict(usage)),
            abilities=abilities,
            pet=self.pet.get_or_create_pet(),
        ).model_dump(mode="json")
