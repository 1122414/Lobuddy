"""Adapt existing named theme records to the desktop color tokens."""

import io
import json
import uuid
from typing import Annotated, cast

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from core.service.companion import CompanionService
from core.service.images import MAX_BYTES, ImageReference, ImageStore
from core.storage.db import Database
from core.storage.theme_repo import ThemeRepository
from core.utils.color_utils import contrast_ratio, darken, lighten

Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class ThemeReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    theme_id: str = Field(min_length=1, max_length=128)


class ThemeSave(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=80)
    accent: Color
    side: Color


class ThemeView(ThemeSave):
    theme_id: str


class ThemeService:
    def __init__(self, db: Database, companion: CompanionService, images: ImageStore) -> None:
        self.repo = ThemeRepository(db)
        self.companion = companion
        self.images = images

    def list(self) -> list[ThemeView]:
        result = []
        for record in self.repo.get_all():
            colors = json.loads(record["colors_json"])
            result.append(
                ThemeView(
                    theme_id=record["id"],
                    name=record["name"],
                    accent=colors.get("primary", "#367572"),
                    side=colors.get("side", colors.get("primary_soft", "#deebec")),
                )
            )
        return result

    def save(self, value: ThemeSave) -> ThemeView:
        identity = str(uuid.uuid4())
        self.repo.save(identity, value.name, {"primary": value.accent, "side": value.side})
        return ThemeView(theme_id=identity, **value.model_dump())

    def apply(self, value: ThemeReference) -> None:
        selected = next((theme for theme in self.list() if theme.theme_id == value.theme_id), None)
        if selected is None:
            raise ValueError("主题不存在")
        self.companion.save(
            self.companion.preferences.model_copy(
                update={"accent": selected.accent, "side": selected.side}
            )
        )
        self.repo.set_active(value.theme_id)

    def remove(self, value: ThemeReference) -> bool:
        return self.repo.delete(value.theme_id)

    def from_image(self, value: ImageReference) -> ThemeSave:
        self.images.get(value.image_id)
        data = ImageStore._read(self.images.root / value.image_id, MAX_BYTES)
        with Image.open(io.BytesIO(data)) as image:
            image.thumbnail((100, 100))
            reduced = image.convert("RGB").quantize(colors=8).convert("RGB")
            colors = sorted(
                cast(list[tuple[int, tuple[int, int, int]]], reduced.getcolors(10000) or []),
                reverse=True,
            )
        # Keep the resulting button text readable; no global Pillow leniency changes.
        rgb = next((color for _, color in colors if max(color) - min(color) > 30), (54, 117, 114))
        accent = "#{:02x}{:02x}{:02x}".format(*rgb)
        side = lighten(accent, 0.85)
        for _ in range(20):
            if contrast_ratio(accent, "#ffffff") >= 4.5:
                break
            accent = darken(accent, 0.1)
        return ThemeSave(name="图片配色", accent=accent, side=side)
