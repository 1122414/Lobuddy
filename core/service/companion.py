"""Persistent companion appearance; geometry remains owned by Electron."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from core.service.images import MAX_BYTES, ImageStore
from core.storage.db import Database
from core.storage.settings_repo import SettingsRepository

logger = logging.getLogger(__name__)


class CompanionPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sprite: Literal["skadi-v2", "skadi", "custom"] = "skadi-v2"
    image_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    scale: float = Field(default=1.0, ge=0.5, le=2.0)
    opacity: float = Field(default=1.0, ge=0.3, le=1.0)
    always_on_top: bool = True
    accent: str = Field(default="#367572", pattern=r"^#[0-9a-fA-F]{6}$")
    side: str = Field(default="#deebec", pattern=r"^#[0-9a-fA-F]{6}$")


class CompanionService:
    def __init__(self, db: Database, data: Path) -> None:
        self.repo = SettingsRepository(db)
        self.images = ImageStore(data / "pet-images")
        raw = self.repo.get_setting("desktop_companion")
        self.preferences = (
            CompanionPreferences.model_validate_json(raw) if raw else CompanionPreferences()
        )
        # Read only the old appearance fields whose meaning is unchanged.
        legacy = data / "pet_appearance.json"
        if raw is None and legacy.is_file():
            try:
                values = json.loads(legacy.read_text(encoding="utf-8"))
                self.preferences = CompanionPreferences.model_validate(
                    {
                        key: values[key]
                        for key in ("scale", "opacity", "always_on_top")
                        if key in values
                    }
                )
                custom = values.get("custom_asset_path")
                if custom:
                    source = Path(custom)
                    if not source.is_absolute():
                        source = data / source
                    if source.resolve().is_relative_to(data.resolve()):
                        self.import_image(str(source.resolve()))
                    else:
                        logger.warning("Legacy appearance needs a fresh native image selection")
                self.save(self.preferences)
            except (ValueError, OSError, TypeError, AttributeError):
                logger.warning("Legacy appearance unavailable; keeping source and default sprite")

    def save(self, value: CompanionPreferences) -> CompanionPreferences:
        if value.sprite == "custom":
            if not value.image_id:
                raise ValueError("请先选择宠物图片")
            self.images.get(value.image_id)
        self.repo.set_setting("desktop_companion", value.model_dump_json())
        self.preferences = value
        return value

    def import_image(self, path: str) -> CompanionPreferences:
        # Reject oversized animations rather than silently flattening them.
        source = Path(path)
        if not source.is_absolute():
            raise ValueError("请选择本地图片")
        data = ImageStore._read(source, MAX_BYTES)
        ImageStore._decode(data)
        with Image.open(io.BytesIO(data)) as image:
            frames = getattr(image, "n_frames", 1)
            if frames > 300 or image.width * image.height * frames > 80_000_000:
                raise ValueError("宠物动画帧数或总尺寸超过限制")
            for frame in range(frames):
                image.seek(frame)
                image.load()
        imported = self.images.import_bytes(data, source.suffix.lower())
        return self.save(
            self.preferences.model_copy(update={"sprite": "custom", "image_id": imported.image_id})
        )
