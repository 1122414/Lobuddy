"""Pet appearance configuration."""

import json
import shutil
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class PetAppearance(BaseModel):
    """Pet appearance configuration."""

    idle_image: str = "pet_idle.gif"
    running_image: str = "pet_running.gif"
    success_image: str = "pet_success.png"
    error_image: str = "pet_error.png"

    width: int = 128
    height: int = 128

    custom_asset_path: str | None = None
    custom_asset_type: str = "default"
    scale: float = Field(default=1.0, ge=0.5, le=2.0)
    opacity: float = Field(default=1.0, ge=0.3, le=1.0)
    position_x: int = 100
    position_y: int = 100
    always_on_top: bool = True
    task_panel_width: int = 560
    task_panel_height: int = 640

    @classmethod
    def load_from_file(cls, filepath: Path) -> "PetAppearance":
        if not filepath.exists():
            return cls()

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**data)
        except (json.JSONDecodeError, ValueError):
            backup = filepath.with_suffix(".json.bak")
            shutil.copy2(str(filepath), str(backup))
            return cls()

    def save_to_file(self, filepath: Path):
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2)


_appearance: Optional[PetAppearance] = None


def get_appearance(config_path: Optional[Path] = None) -> PetAppearance:
    global _appearance

    if _appearance is None:
        if config_path is None:
            config_path = Path("data/pet_appearance.json")
        _appearance = PetAppearance.load_from_file(config_path)

    return _appearance


def save_appearance(appearance: PetAppearance, config_path: Optional[Path] = None):
    if config_path is None:
        config_path = Path("data/pet_appearance.json")
    appearance.save_to_file(config_path)

    global _appearance
    _appearance = appearance
