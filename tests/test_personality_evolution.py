"""Regression tests for reversible, content-minimized Personality Evolution."""

from pathlib import Path

import pytest

from core.config import Settings
from core.models.personality import PetPersonality, PersonalityDimension
from core.models.pet import TaskDifficulty, TaskRecord
from core.personality.evolution import PersonalityEvolution
from core.personality.evolution_models import PersonalityEvolutionKind
from core.storage.ability_repo import AbilityRepository
from core.storage.db import Database
from core.storage.personality_evolution_repo import (
    PersonalityEvolutionConflict,
    PersonalityEvolutionRepository,
)
from core.storage.pet_repo import PetRepository


def _build_stack(tmp_path: Path):
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
    )
    database = Database(settings)
    database.init_database()
    pets = PetRepository(database)
    revisions = PersonalityEvolutionRepository(database)
    evolution = PersonalityEvolution(pets=pets, revisions=revisions)
    return database, pets, revisions, evolution


def test_task_evolution_is_versioned_idempotent_and_content_minimized(
    tmp_path: Path,
) -> None:
    _db, pets, revisions, evolution = _build_stack(tmp_path)
    task = TaskRecord(
        id="task-versioned",
        input_text="请优化 Secret-Aurora 项目的 Python 代码并设计新的界面",
        difficulty=TaskDifficulty.COMPLEX,
    )

    first = evolution.evolve_from_task(task)
    after_first = pets.get_or_create_pet().personality
    second = evolution.evolve_from_task(task)
    after_second = pets.get_or_create_pet().personality

    assert first.applied is True
    assert second.applied is False
    assert first.revision.id == second.revision.id
    assert revisions.count() == 2
    assert after_first == after_second
    assert first.revision.kind == PersonalityEvolutionKind.TASK_COMPLETED
    assert first.revision.task_id == task.id
    assert "Secret-Aurora" not in first.revision.reason
    assert task.input_text not in first.revision.reason
    assert first.revision.adjustments["technical_skill"] > 0
    assert first.revision.adjustments["creativity"] > 0
    assert first.revision.adjustments["diligence"] > 0
    assert first.expression is not None
    assert first.expression.dominant_dimension == PersonalityDimension.TECHNICAL_SKILL


def test_restore_appends_a_version_without_downgrading_progress_or_abilities(
    tmp_path: Path,
) -> None:
    database, pets, revisions, evolution = _build_stack(tmp_path)
    pet = pets.get_or_create_pet()
    pet.level = 6
    pet.exp = 37
    pet.skin = "warm-pixel"
    pets.save_pet(pet)
    AbilityRepository(database).save_unlocked_ability("code_assist")

    evolution.evolve_from_task(
        TaskRecord(
            id="task-technical",
            input_text="修复 Python 代码并重构数据库接口",
            difficulty=TaskDifficulty.COMPLEX,
        )
    )
    baseline = evolution.history()[-1]
    before_restore_count = revisions.count()

    restored = evolution.restore(
        baseline.revision_id,
        reason="我希望暂时回到版本历史开始时的伙伴倾向",
    )
    current = pets.get_or_create_pet()

    assert restored.applied is True
    assert restored.revision.kind == PersonalityEvolutionKind.RESTORED
    assert restored.revision.actor == "user"
    assert restored.revision.restored_from_revision_id == baseline.revision_id
    assert current.personality == restored.revision.after
    assert current.level == 6
    assert current.exp == 37
    assert current.skin == "warm-pixel"
    assert AbilityRepository(database).is_unlocked("code_assist") is True
    assert revisions.count() == before_restore_count + 1

    no_op = evolution.restore(
        baseline.revision_id,
        reason="再次选择当前版本",
    )
    assert no_op.applied is False
    assert revisions.count() == before_restore_count + 1


def test_revision_failure_rolls_back_personality_and_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _db, pets, revisions, evolution = _build_stack(tmp_path)
    before = pets.get_or_create_pet().personality.model_copy(deep=True)

    def fail_insert(*_args, **_kwargs):
        raise RuntimeError("revision write failed")

    monkeypatch.setattr(revisions, "_insert_revision", fail_insert)
    with pytest.raises(RuntimeError, match="revision write failed"):
        evolution.evolve_from_task(
            TaskRecord(
                id="task-rollback",
                input_text="优化代码",
                difficulty=TaskDifficulty.MEDIUM,
            )
        )

    assert pets.get_or_create_pet().personality == before
    assert revisions.count() == 0


def test_stale_expected_snapshot_fails_closed(tmp_path: Path) -> None:
    _db, pets, revisions, _evolution = _build_stack(tmp_path)
    pet = pets.get_or_create_pet()
    stale = PetPersonality(technical_skill=20)
    after = pet.personality.model_copy(update={"technical_skill": 60.0})

    with pytest.raises(PersonalityEvolutionConflict):
        revisions.apply_task_evolution(
            pet_id=pet.id,
            task_id="stale-task",
            expected_before=stale,
            after=after,
            adjustments={"technical_skill": 10.0},
            reason="stale test",
        )

    assert revisions.count() == 0
    assert pets.get_or_create_pet().personality == pet.personality


def test_history_projection_marks_only_current_version_restorable(
    tmp_path: Path,
) -> None:
    _db, _pets, _revisions, evolution = _build_stack(tmp_path)
    evolution.evolve_from_task(
        TaskRecord(
            id="history-task",
            input_text="陪我一起设计一个新应用",
            difficulty=TaskDifficulty.MEDIUM,
        )
    )

    history = evolution.history()

    assert len(history) == 2
    assert history[0].is_current is True
    assert history[0].can_restore is False
    assert history[0].kind_label == "任务成长"
    assert "创意协作" in history[0].summary
    assert history[1].kind == PersonalityEvolutionKind.BASELINE
    assert history[1].can_restore is True
