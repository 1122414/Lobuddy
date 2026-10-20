"""Appearance persistence and bounded animated asset admission."""

from pathlib import Path

import pytest
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from core.config import Settings
from core.service.companion import CompanionPreferences, CompanionService
from core.service.images import ImageReference, ImageStore
from core.service.themes import ThemeReference, ThemeSave, ThemeService
from core.storage.db import Database
from core.storage.theme_repo import ThemeRepository


class TestCompanionService:
    def test_preferences_survive_restart_and_validate(self, tmp_path: Path) -> None:
        db = Database(Settings(llm_api_key="test", data_dir=tmp_path))
        db.init_database(allow_desktop=True)
        service = CompanionService(db, tmp_path)
        service.save(CompanionPreferences(sprite="skadi", scale=1.5, accent="#223344"))
        restored = CompanionService(db, tmp_path)
        assert restored.preferences.sprite == "skadi"
        assert restored.preferences.scale == 1.5
        with pytest.raises(ValidationError):
            CompanionPreferences(accent="url(https://example.com)")
        with pytest.raises(ValidationError):
            CompanionPreferences(scale=5)
        with pytest.raises(ValueError, match="先选择"):
            service.save(CompanionPreferences(sprite="custom"))

    def test_gif_preserved_and_bad_asset_cannot_replace_selection(self, tmp_path: Path) -> None:
        db = Database(Settings(llm_api_key="test", data_dir=tmp_path))
        db.init_database(allow_desktop=True)
        service = CompanionService(db, tmp_path)
        source = tmp_path / "pet.gif"
        Image.new("RGB", (20, 20), "red").save(
            source, save_all=True, append_images=[Image.new("RGB", (20, 20), "blue")], loop=0
        )
        selected = service.import_image(str(source))
        assert selected.image_id is not None
        target = service.images.root / selected.image_id
        assert target.read_bytes() == source.read_bytes()
        with Image.open(target) as image:
            assert image.n_frames == 2
        source.write_bytes(b"broken")
        with pytest.raises(UnidentifiedImageError):
            service.import_image(str(source))
        assert service.preferences == selected

    def test_legacy_appearance_does_not_copy_geometry_into_business_state(
        self, tmp_path: Path
    ) -> None:
        db = Database(Settings(llm_api_key="test", data_dir=tmp_path))
        db.init_database(allow_desktop=True)
        (tmp_path / "pet_appearance.json").write_text(
            '{"scale":1.5,"opacity":0.5,"always_on_top":false,"position_x":-9999}'
        )
        value = CompanionService(db, tmp_path).preferences
        assert value.scale == 1.5 and value.opacity == 0.5 and not value.always_on_top
        assert "position_x" not in value.model_dump()

    def test_legacy_theme_ids_palette_and_image_validation_remain_intact(
        self, tmp_path: Path
    ) -> None:
        from PIL import ImageFile

        db = Database(Settings(llm_api_key="test", data_dir=tmp_path))
        db.init_database(allow_desktop=True)
        old = ThemeRepository(db)
        old.save("legacy-id", "旧主题", {"primary": "#334455", "primary_soft": "#ccddee"})
        images = ImageStore(tmp_path / "images")
        companion = CompanionService(db, tmp_path)
        themes = ThemeService(db, companion, images)
        assert themes.list()[0].theme_id == "legacy-id"
        themes.apply(ThemeReference(theme_id="legacy-id"))
        assert companion.preferences.accent == "#334455"
        assert companion.preferences.side == "#ccddee"
        source = tmp_path / "sample.png"
        Image.new("RGB", (20, 20), "orange").save(source)
        image = images.import_file(str(source))
        previous = ImageFile.LOAD_TRUNCATED_IMAGES
        palette = themes.from_image(ImageReference(image_id=image.image_id))
        assert ImageFile.LOAD_TRUNCATED_IMAGES == previous
        saved = themes.save(ThemeSave(name="橙色", accent=palette.accent, side=palette.side))
        assert len(themes.list()) == 2
        assert themes.remove(ThemeReference(theme_id=saved.theme_id))
        assert themes.list()[0].theme_id == "legacy-id"

    def test_focus_completion_survives_session_release_exactly_once(self) -> None:
        from datetime import datetime, timedelta

        from core.focus.focus_companion import FocusCompanion

        focus = FocusCompanion(Settings(llm_api_key="test", focus_auto_loop=False))
        session = focus.start_focus(1)
        session._ends_at = datetime.now() - timedelta(seconds=1)
        focus.poll()
        focus.poll()
        assert focus.completed_count == 1
        assert focus.current_session is None
