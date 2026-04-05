"""Tests for database and repository layer."""

import pytest
from datetime import datetime

from core.models.pet import (
    EvolutionStage,
    PetState,
    TaskDifficulty,
    TaskRecord,
    TaskResult,
    TaskStatus,
)
from core.storage.db import Database, init_database
from core.storage.pet_repo import PetRepository
from core.storage.task_repo import TaskRepository
from core.storage.settings_repo import SettingsRepository


@pytest.fixture
def test_db(tmp_path):
    """Create test database."""
    from app.config import Settings

    settings = Settings(
        llm_api_key="test-key",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
    )

    db = Database(settings)
    db.init_database()
    return db


class TestDatabase:
    """Test database operations."""

    def test_database_initialization(self, test_db):
        """Test database and tables are created."""
        assert test_db.is_initialized()

    def test_tables_exist(self, test_db):
        """Test all required tables exist."""
        with test_db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table'
            """)
            tables = {row["name"] for row in cursor.fetchall()}

            assert "pet_state" in tables
            assert "task_record" in tables
            assert "task_result" in tables
            assert "app_settings" in tables


class TestPetRepository:
    """Test pet repository operations."""

    def test_create_and_get_pet(self, test_db):
        """Test creating and retrieving pet."""
        repo = PetRepository(test_db)

        # Create default pet
        pet = repo.create_default_pet()
        assert pet.name == "Lobuddy"
        assert pet.level == 1

        # Get pet
        retrieved = repo.get_pet("default")
        assert retrieved is not None
        assert retrieved.name == pet.name
        assert retrieved.level == pet.level

    def test_update_pet(self, test_db):
        """Test updating pet state."""
        repo = PetRepository(test_db)

        pet = repo.create_default_pet()
        pet.level = 5
        pet.exp = 100

        repo.save_pet(pet)

        retrieved = repo.get_pet("default")
        assert retrieved.level == 5
        assert retrieved.exp == 100

    def test_get_or_create_pet(self, test_db):
        """Test get_or_create creates pet if not exists."""
        repo = PetRepository(test_db)

        pet = repo.get_or_create_pet("new_pet")
        assert pet.name == "Lobuddy"

        # Second call should return same pet
        pet2 = repo.get_or_create_pet("new_pet")
        assert pet2.id == pet.id


class TestTaskRepository:
    """Test task repository operations."""

    def test_create_and_get_task(self, test_db):
        """Test creating and retrieving task."""
        repo = TaskRepository(test_db)

        task = TaskRecord(
            id="task-001",
            input_text="Test task",
            difficulty=TaskDifficulty.SIMPLE,
            reward_exp=5,
        )

        repo.create_task(task)

        retrieved = repo.get_task("task-001")
        assert retrieved is not None
        assert retrieved.input_text == "Test task"
        assert retrieved.status == TaskStatus.CREATED

    def test_update_task_status(self, test_db):
        """Test updating task status."""
        repo = TaskRepository(test_db)

        task = TaskRecord(id="task-002", input_text="Test")
        repo.create_task(task)

        repo.update_task_status("task-002", TaskStatus.RUNNING, started_at=datetime.now())

        retrieved = repo.get_task("task-002")
        assert retrieved.status == TaskStatus.RUNNING
        assert retrieved.started_at is not None

    def test_get_recent_tasks(self, test_db):
        """Test retrieving recent tasks."""
        repo = TaskRepository(test_db)

        for i in range(5):
            task = TaskRecord(id=f"task-{i}", input_text=f"Task {i}")
            repo.create_task(task)

        recent = repo.get_recent_tasks(limit=3)
        assert len(recent) == 3

    def test_save_and_get_task_result(self, test_db):
        """Test saving and retrieving task result."""
        repo = TaskRepository(test_db)

        task = TaskRecord(id="task-003", input_text="Test")
        repo.create_task(task)

        result = TaskResult(
            task_id="task-003",
            success=True,
            raw_result="Full output",
            summary="Summary",
        )
        repo.save_task_result(result)

        retrieved = repo.get_task_result("task-003")
        assert retrieved is not None
        assert retrieved.success is True
        assert retrieved.summary == "Summary"


class TestSettingsRepository:
    """Test settings repository operations."""

    def test_set_and_get_setting(self, test_db):
        """Test saving and retrieving setting."""
        repo = SettingsRepository(test_db)

        repo.set_setting("test_key", "test_value")
        value = repo.get_setting("test_key")

        assert value == "test_value"

    def test_get_nonexistent_setting(self, test_db):
        """Test getting non-existent setting returns None."""
        repo = SettingsRepository(test_db)

        value = repo.get_setting("nonexistent")
        assert value is None

    def test_json_settings(self, test_db):
        """Test JSON serialization for settings."""
        repo = SettingsRepository(test_db)

        data = {"key": "value", "number": 42}
        repo.set_json_setting("json_key", data)

        retrieved = repo.get_json_setting("json_key")
        assert retrieved == data


class TestPetStateLogic:
    """Test PetState business logic."""

    def test_exp_for_next_level(self):
        """Test EXP calculation."""
        pet = PetState(level=1)
        assert pet.get_exp_for_next_level() == 50

        pet.level = 5
        assert pet.get_exp_for_next_level() == 520

    def test_evolution_stage_for_level(self):
        """Test evolution stage determination."""
        pet = PetState()

        assert pet.get_evolution_stage_for_level(1) == EvolutionStage.STAGE_1
        assert pet.get_evolution_stage_for_level(3) == EvolutionStage.STAGE_1
        assert pet.get_evolution_stage_for_level(4) == EvolutionStage.STAGE_2
        assert pet.get_evolution_stage_for_level(7) == EvolutionStage.STAGE_2
        assert pet.get_evolution_stage_for_level(8) == EvolutionStage.STAGE_3

    def test_add_exp_and_level_up(self):
        """Test EXP addition and level up."""
        pet = PetState(level=1, exp=0)

        # Add enough EXP for level up
        level_up = pet.add_exp(60)

        assert level_up is True
        assert pet.level == 2
        assert pet.exp == 10  # 60 - 50 = 10

    def test_add_exp_multiple_level_ups(self):
        """Test multiple level ups at once."""
        pet = PetState(level=1, exp=0)

        # Add enough for multiple levels
        level_up = pet.add_exp(200)

        assert level_up is True
        assert pet.level == 3
        # Lv1->Lv2: 50, Lv2->Lv3: 120, total 170
        # 200 - 170 = 30 remaining
        assert pet.exp == 30

    def test_evolution_on_level_up(self):
        """Test evolution stage updates on level up."""
        pet = PetState(level=3, exp=0)
        pet.evolution_stage = EvolutionStage.STAGE_1

        # Level up to 4
        pet.add_exp(220)

        assert pet.level == 4
        assert pet.evolution_stage == EvolutionStage.STAGE_2
