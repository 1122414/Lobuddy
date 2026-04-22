"""Tests for pet model and persistence."""

import pytest
from datetime import datetime
from uuid import uuid4

from core.models.pet import PetState, TaskRecord, TaskStatus, TaskDifficulty, TaskResult, EvolutionStage


class TestPetState:
    """Test pet state model logic."""

    def test_add_exp_levels_up(self):
        pet = PetState(name="Test")
        assert pet.level == 1
        assert pet.exp == 0
        level_up = pet.add_exp(60)
        assert level_up is True
        assert pet.level == 2
        assert pet.exp == 10

    def test_add_exp_no_level_up(self):
        pet = PetState(name="Test")
        level_up = pet.add_exp(5)
        assert level_up is False
        assert pet.level == 1
        assert pet.exp == 5

    def test_add_exp_negative_rejected(self):
        pet = PetState(name="Test", exp=10)
        with pytest.raises(ValueError, match="non-negative"):
            pet.add_exp(-5)

    def test_evolution_stage_for_level(self):
        pet = PetState(name="Test")
        assert pet.get_evolution_stage_for_level(1) == EvolutionStage.STAGE_1
        assert pet.get_evolution_stage_for_level(3) == EvolutionStage.STAGE_1
        assert pet.get_evolution_stage_for_level(4) == EvolutionStage.STAGE_2
        assert pet.get_evolution_stage_for_level(7) == EvolutionStage.STAGE_2
        assert pet.get_evolution_stage_for_level(8) == EvolutionStage.STAGE_3


class TestTaskRecord:
    """Test task record state machine."""

    def test_task_lifecycle_valid(self):
        task = TaskRecord(id=str(uuid4()), input_text="test")
        assert task.status == TaskStatus.CREATED
        task.start()
        assert task.status == TaskStatus.RUNNING
        assert task.started_at is not None
        task.complete(success=True)
        assert task.status == TaskStatus.SUCCESS
        assert task.finished_at is not None

    def test_task_invalid_transition(self):
        task = TaskRecord(id=str(uuid4()), input_text="test")
        task.start()
        task.complete(success=True)
        with pytest.raises(ValueError, match="Invalid state transition"):
            task.start()

    def test_task_failure_transition(self):
        task = TaskRecord(id=str(uuid4()), input_text="test")
        task.start()
        task.complete(success=False)
        assert task.status == TaskStatus.FAILED


class TestTaskResult:
    """Test task result model."""

    def test_task_result_creation(self):
        result = TaskResult(
            task_id=str(uuid4()),
            success=True,
            raw_result="output",
            summary="done",
        )
        assert result.success is True
        assert result.summary == "done"
