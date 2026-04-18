"""Tests for ability persistence."""

import pytest

from core.abilities.ability_system import AbilityManager
from core.storage.ability_repo import AbilityRepository


class TestAbilityPersistence:
    """Test ability unlock persistence."""

    def test_unlock_persistence(self, tmp_path, monkeypatch):
        """Test that unlocked abilities are persisted to database."""
        from app.config import Settings
        from core.storage.db import Database

        # Create a temporary database
        settings = Settings(
            llm_api_key="test",
            data_dir=tmp_path,
        )
        db = Database(settings)
        db.init_database()

        repo = AbilityRepository(db)

        # Save an unlocked ability
        repo.save_unlocked_ability("test_ability")

        # Verify it was saved
        assert repo.is_unlocked("test_ability") is True
        abilities = repo.get_unlocked_abilities()
        assert "test_ability" in abilities

    def test_ability_manager_loads_persisted(self, tmp_path, monkeypatch):
        """Test that AbilityManager loads persisted abilities."""
        from app.config import Settings
        from core.storage.db import Database, get_database

        # Create a temporary database
        settings = Settings(
            llm_api_key="test",
            data_dir=tmp_path,
        )
        db = Database(settings)
        db.init_database()

        # Monkeypatch the global database
        monkeypatch.setattr("core.storage.db._db", db)

        # Pre-populate with an unlocked ability
        repo = AbilityRepository(db)
        repo.save_unlocked_ability("advanced_chat")

        # Create manager - should load persisted abilities
        manager = AbilityManager()
        assert manager.is_unlocked("advanced_chat") is True

    def test_unlock_is_idempotent(self, tmp_path, monkeypatch):
        """Test that unlocking the same ability multiple times is safe."""
        from app.config import Settings
        from core.storage.db import Database

        settings = Settings(
            llm_api_key="test",
            data_dir=tmp_path,
        )
        db = Database(settings)
        db.init_database()

        repo = AbilityRepository(db)

        # Save twice
        repo.save_unlocked_ability("test_ability")
        repo.save_unlocked_ability("test_ability")

        abilities = repo.get_unlocked_abilities()
        assert abilities.count("test_ability") == 1
