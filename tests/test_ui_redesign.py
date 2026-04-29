"""Tests for new UI redesign components."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.models.appearance import PetAppearance
from core.models.task_card import TaskCardModel, TaskStep
from core.services.pet_asset_service import PetAssetService


class TestPetAppearance:
    def test_default_values(self):
        app = PetAppearance()
        assert app.scale == 1.0
        assert app.opacity == 1.0
        assert app.always_on_top is True
        assert app.position_x == 100
        assert app.position_y == 100

    def test_scale_bounds(self):
        with pytest.raises(ValidationError):
            PetAppearance(scale=0.1)
        with pytest.raises(ValidationError):
            PetAppearance(scale=3.0)

    def test_opacity_bounds(self):
        with pytest.raises(ValidationError):
            PetAppearance(opacity=0.1)
        with pytest.raises(ValidationError):
            PetAppearance(opacity=1.5)

    def test_load_from_file_missing(self, tmp_path):
        filepath = tmp_path / "missing.json"
        app = PetAppearance.load_from_file(filepath)
        assert app.scale == 1.0

    def test_load_from_file_valid(self, tmp_path):
        filepath = tmp_path / "app.json"
        data = {"scale": 1.5, "opacity": 0.8, "always_on_top": False}
        filepath.write_text(json.dumps(data))
        app = PetAppearance.load_from_file(filepath)
        assert app.scale == 1.5
        assert app.opacity == 0.8
        assert app.always_on_top is False

    def test_load_from_file_corrupted(self, tmp_path):
        filepath = tmp_path / "app.json"
        filepath.write_text("not valid json {{{")
        app = PetAppearance.load_from_file(filepath)
        assert app.scale == 1.0
        assert (tmp_path / "app.json.bak").exists()

    def test_save_and_load_roundtrip(self, tmp_path):
        filepath = tmp_path / "app.json"
        original = PetAppearance(scale=1.2, opacity=0.9)
        original.save_to_file(filepath)
        loaded = PetAppearance.load_from_file(filepath)
        assert loaded.scale == 1.2
        assert loaded.opacity == 0.9


class TestTaskCardModel:
    def test_default_values(self):
        card = TaskCardModel(title="Test", status="running")
        assert card.short_result == ""
        assert card.details == ""
        assert card.exp_reward == 0
        assert card.steps == []
        assert card.available_actions == []

    def test_with_steps(self):
        steps = [TaskStep(text="Step 1", status="success")]
        card = TaskCardModel(title="Test", status="success", steps=steps, exp_reward=15)
        assert len(card.steps) == 1
        assert card.exp_reward == 15


class TestPetAssetService:
    def test_validate_asset_missing(self, tmp_path):
        service = PetAssetService(tmp_path)
        result = service.validate_asset(tmp_path / "nonexistent.png")
        assert not result.valid

    def test_validate_asset_unsupported_type(self, tmp_path):
        service = PetAssetService(tmp_path)
        filepath = tmp_path / "test.txt"
        filepath.write_text("hello")
        result = service.validate_asset(filepath)
        assert not result.valid

    def test_validate_asset_too_large(self, tmp_path):
        service = PetAssetService(tmp_path)
        filepath = tmp_path / "test.png"
        filepath.write_bytes(b"x" * (21 * 1024 * 1024))
        result = service.validate_asset(filepath)
        assert not result.valid

    def test_validate_asset_valid(self, tmp_path):
        service = PetAssetService(tmp_path)
        filepath = tmp_path / "test.png"
        filepath.write_bytes(b"x" * 100)
        result = service.validate_asset(filepath)
        assert result.valid

    def test_detect_asset_type(self, tmp_path):
        service = PetAssetService(tmp_path)
        assert service.detect_asset_type(tmp_path / "test.gif") == "gif"
        assert service.detect_asset_type(tmp_path / "test.png") == "image"
        assert service.detect_asset_type(tmp_path / "test.jpg") == "image"
        assert service.detect_asset_type(tmp_path / "test.txt") == "invalid"

    def test_copy_to_app_data(self, tmp_path):
        service = PetAssetService(tmp_path)
        source = tmp_path / "source.png"
        source.write_bytes(b"x" * 100)
        dest = service.copy_to_app_data(source)
        assert dest.exists()
        assert dest.parent.name == "pets"
        assert dest.name.startswith("pet_")

    def test_remove_asset(self, tmp_path):
        service = PetAssetService(tmp_path)
        filepath = tmp_path / "test.png"
        filepath.write_bytes(b"x")
        assert service.remove_asset(filepath) is True
        assert not filepath.exists()

    def test_remove_asset_missing(self, tmp_path):
        service = PetAssetService(tmp_path)
        assert service.remove_asset(tmp_path / "missing.png") is False
