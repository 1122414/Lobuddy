"""Theme system tests - color utils, theme generator, repository, manager."""

import dataclasses
import json
import tempfile
from pathlib import Path

import pytest

from core.config import Settings
from core.storage.db import init_database
from core.utils.color_utils import (
    contrast_ratio,
    darken,
    get_contrast_level,
    hex_to_rgb,
    is_light_color,
    lighten,
    rgb_to_hex,
)


class TestColorUtils:
    """Tests for WCAG color utility functions."""

    def test_hex_to_rgb_converts_correctly(self):
        assert hex_to_rgb("#FF8A3D") == (255, 138, 61)

    def test_rgb_to_hex_converts_correctly(self):
        assert rgb_to_hex(255, 138, 61) == "#ff8a3d"

    def test_contrast_ratio_black_white_is_max(self):
        ratio = contrast_ratio("#FFFFFF", "#000000")
        assert 20 < ratio < 22

    def test_get_contrast_level_returns_aaa_for_high_ratio(self):
        assert get_contrast_level(8.0) == "AAA"

    def test_get_contrast_level_returns_aa_for_medium_ratio(self):
        assert get_contrast_level(5.0) == "AA"

    def test_get_contrast_level_returns_a_for_low_ratio(self):
        assert get_contrast_level(3.5) == "A"

    def test_get_contrast_level_returns_fail_for_very_low_ratio(self):
        assert get_contrast_level(2.0) == "FAIL"

    def test_is_light_color_white(self):
        assert is_light_color("#FFFFFF") is True

    def test_is_light_color_black(self):
        assert is_light_color("#000000") is False

    def test_lighten_increases_brightness(self):
        lighter = lighten("#000000", 0.2)
        r, g, b = hex_to_rgb(lighter)
        assert r > 0 or g > 0 or b > 0

    def test_darken_decreases_brightness(self):
        darker = darken("#FFFFFF", 0.2)
        r, g, b = hex_to_rgb(darker)
        assert r < 255 or g < 255 or b < 255


class TestThemeGenerator:
    """Tests for theme color extraction and generation."""

    def test_generate_theme_returns_required_keys(self):
        from core.services.theme_generator import ThemeGenerator

        gen = ThemeGenerator()
        palette = ["#FF8A3D", "#FFFFFF", "#4A2E1F", "#F1D9C0", "#8BCF7A"]
        theme = gen.generate_theme(palette, "Test Theme")

        required_keys = [
            "background", "surface", "primary", "text", "border",
            "success", "warning", "danger", "info",
            "primary_hover", "primary_active", "secondary", "accent",
            "card", "divider", "on_primary", "on_accent",
        ]
        for key in required_keys:
            assert key in theme, f"Missing key: {key}"

    def test_generate_theme_uses_palette_primary(self):
        from core.services.theme_generator import ThemeGenerator

        gen = ThemeGenerator()
        palette = ["#FF8A3D", "#FFFFFF", "#4A2E1F", "#F1D9C0", "#8BCF7A"]
        theme = gen.generate_theme(palette, "Test Theme")

        assert theme["primary"] in palette

    def test_extract_palette_returns_list(self):
        from core.services.theme_generator import ThemeGenerator

        gen = ThemeGenerator()
        palette = gen._fallback_palette()

        assert isinstance(palette, list)
        assert len(palette) >= 3


class TestThemeRepository:
    """Tests for user theme CRUD operations."""

    @pytest.fixture
    def theme_repo(self, tmp_path):
        settings = Settings(llm_api_key="test-key", data_dir=tmp_path)
        init_database(settings)
        from core.storage.theme_repo import ThemeRepository
        return ThemeRepository()

    def test_save_and_get_all(self, theme_repo):
        colors = {"primary": "#FF8A3D", "background": "#FFF8EF"}
        theme_repo.save("test_1", "Test Theme", colors, "manual")

        themes = theme_repo.get_all()
        assert len(themes) == 1
        assert themes[0]["name"] == "Test Theme"

    def test_get_by_id_returns_correct_theme(self, theme_repo):
        colors = {"primary": "#FF8A3D"}
        theme_repo.save("test_1", "Test Theme", colors, "manual")

        theme = theme_repo.get_by_id("test_1")
        assert theme is not None
        assert json.loads(theme["colors_json"]) == colors

    def test_set_active_and_get_active(self, theme_repo):
        colors = {"primary": "#FF8A3D"}
        theme_repo.save("test_1", "Test Theme", colors, "manual")

        theme_repo.set_active("test_1")
        active = theme_repo.get_active()
        assert active is not None
        assert active["id"] == "test_1"

    def test_save_updates_existing_theme(self, theme_repo):
        colors = {"primary": "#FF8A3D"}
        theme_repo.save("test_1", "Original", colors, "manual")
        theme_repo.save("test_1", "Updated", colors)

        theme = theme_repo.get_by_id("test_1")
        assert theme["name"] == "Updated"

    def test_delete_removes_theme(self, theme_repo):
        colors = {"primary": "#FF8A3D"}
        theme_repo.save("test_1", "Test Theme", colors, "manual")

        assert theme_repo.delete("test_1") is True
        assert theme_repo.get_by_id("test_1") is None


class TestThemeManager:
    """Tests for ThemeManager user theme operations."""

    def test_manager_has_current_theme(self):
        from ui.theme import ThemeManager, ThemePreset

        mgr = ThemeManager.instance()
        assert mgr.current is not None
        assert mgr.preset == ThemePreset.COZY_ORANGE

    def test_manager_has_user_theme_methods(self):
        from ui.theme import ThemeManager

        mgr = ThemeManager.instance()
        assert hasattr(mgr, "load_user_theme")
        assert hasattr(mgr, "save_current_as_user_theme")
        assert hasattr(mgr, "delete_user_theme")
        assert hasattr(mgr, "get_user_themes")
        assert hasattr(mgr, "user_theme_id")


class TestThemeColorsTokens:
    """Tests for ThemeColors dataclass completeness."""

    def test_has_all_required_tokens(self):
        from ui.theme import ThemeColors

        required_tokens = [
            "background", "surface", "surface_soft",
            "primary", "primary_soft", "primary_text",
            "primary_hover", "primary_active",
            "secondary", "accent",
            "card", "divider", "info",
            "on_primary", "on_accent",
            "text", "text_secondary", "text_muted",
            "border", "border_focus",
            "success", "warning", "danger",
        ]

        fields = {f.name for f in dataclasses.fields(ThemeColors)}
        for token in required_tokens:
            assert token in fields, f"Missing token: {token}"
