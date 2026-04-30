"""Functional test script for theme system."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.utils.color_utils import (
    contrast_ratio,
    darken,
    get_contrast_level,
    hex_to_rgb,
    is_light_color,
    lighten,
    rgb_to_hex,
)


def test_color_utils():
    """Test color utility functions."""
    print("Testing color utilities...")

    assert hex_to_rgb("#FF8A3D") == (255, 138, 61)
    assert rgb_to_hex(255, 138, 61) == "#ff8a3d"

    ratio = contrast_ratio("#FFFFFF", "#000000")
    assert 20 < ratio < 22

    assert get_contrast_level(8.0) == "AAA"
    assert get_contrast_level(5.0) == "AA"
    assert get_contrast_level(3.5) == "A"
    assert get_contrast_level(2.0) == "FAIL"

    assert is_light_color("#FFFFFF") is True
    assert is_light_color("#000000") is False

    lighter = lighten("#000000", 0.2)
    r, g, b = hex_to_rgb(lighter)
    assert r > 0 or g > 0 or b > 0

    darker = darken("#FFFFFF", 0.2)
    r, g, b = hex_to_rgb(darker)
    assert r < 255 or g < 255 or b < 255

    print("  [OK] Color utilities passed")


def test_theme_generator():
    """Test theme generation from palette."""
    print("Testing theme generator...")

    from core.services.theme_generator import ThemeGenerator

    gen = ThemeGenerator()

    palette = ["#FF8A3D", "#FFFFFF", "#4A2E1F", "#F1D9C0", "#8BCF7A"]
    theme = gen.generate_theme(palette, "Test Theme")

    assert "primary" in theme
    assert "background" in theme
    assert "text" in theme
    assert theme["primary"] in palette

    required_keys = [
        "background", "surface", "primary", "text", "border",
        "success", "warning", "danger", "info",
        "primary_hover", "primary_active", "secondary", "accent",
        "card", "divider", "on_primary", "on_accent",
    ]
    for key in required_keys:
        assert key in theme, f"Missing key: {key}"

    print("  [OK] Theme generator passed")


def test_theme_repo():
    """Test theme repository CRUD."""
    print("Testing theme repository...")

    import tempfile
    from core.config import Settings
    from core.storage.db import init_database, get_database
    from core.storage.theme_repo import ThemeRepository

    with tempfile.TemporaryDirectory() as tmpdir:
        settings = Settings(
            llm_api_key="test-key",
            data_dir=Path(tmpdir),
        )
        init_database(settings)

        repo = ThemeRepository()

        colors = {"primary": "#FF8A3D", "background": "#FFF8EF"}
        repo.save("test_1", "Test Theme", colors, "manual")

        themes = repo.get_all()
        assert len(themes) == 1
        assert themes[0]["name"] == "Test Theme"

        theme = repo.get_by_id("test_1")
        assert theme is not None
        assert json.loads(theme["colors_json"]) == colors

        repo.set_active("test_1")
        active = repo.get_active()
        assert active is not None
        assert active["id"] == "test_1"

        repo.save("test_1", "Updated Theme", colors)
        theme = repo.get_by_id("test_1")
        assert theme["name"] == "Updated Theme"

        assert repo.delete("test_1") is True
        assert repo.get_by_id("test_1") is None

    print("  [OK] Theme repository passed")


def test_theme_manager():
    """Test ThemeManager user theme operations."""
    print("Testing ThemeManager...")

    from ui.theme import ThemeManager, ThemePreset

    mgr = ThemeManager.instance()

    assert mgr.current is not None
    assert mgr.preset == ThemePreset.COZY_ORANGE

    assert hasattr(mgr, "load_user_theme")
    assert hasattr(mgr, "save_current_as_user_theme")
    assert hasattr(mgr, "delete_user_theme")
    assert hasattr(mgr, "get_user_themes")
    assert hasattr(mgr, "user_theme_id")

    print("  [OK] ThemeManager passed")


def test_theme_colors_tokens():
    """Test ThemeColors has all required tokens."""
    print("Testing ThemeColors tokens...")

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

    import dataclasses
    fields = {f.name for f in dataclasses.fields(ThemeColors)}
    for token in required_tokens:
        assert token in fields, f"Missing token: {token}"

    print("  [OK] ThemeColors tokens passed")


def main():
    """Run all tests."""
    print("\n=== Theme System Functional Tests ===\n")

    try:
        test_color_utils()
        test_theme_generator()
        test_theme_repo()
        test_theme_manager()
        test_theme_colors_tokens()

        print("\n[PASS] All tests passed!\n")
        return 0
    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}\n")
        return 1
    except Exception as e:
        print(f"\n[ERROR] {e}\n")
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
