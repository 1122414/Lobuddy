"""Pet appearance configuration."""

import json
from pathlib import Path
from typing import Dict, Optional

from pydantic import BaseModel, Field


class PetAppearance(BaseModel):
    """Pet appearance configuration."""

    # State images (path relative to assets directory)
    idle_image: str = "pet_idle.gif"
    running_image: str = "pet_running.png"
    success_image: str = "pet_success.png"
    error_image: str = "pet_error.png"

    # Pet window size
    width: int = 128
    height: int = 128

    @classmethod
    def load_from_file(cls, filepath: Path) -> "PetAppearance":
        """Load appearance from JSON file."""
        if not filepath.exists():
            return cls()

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        return cls(**data)

    def save_to_file(self, filepath: Path):
        """Save appearance to JSON file."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2)

    def get_image_for_state(self, state: str) -> str:
        """Get image filename for given state."""
        state_map = {
            "idle": self.idle_image,
            "running": self.running_image,
            "success": self.success_image,
            "error": self.error_image,
        }
        return state_map.get(state, self.idle_image)


# Global instance
_appearance: Optional[PetAppearance] = None


def get_appearance(config_path: Optional[Path] = None) -> PetAppearance:
    """Get or load pet appearance configuration."""
    global _appearance

    if _appearance is None:
        if config_path is None:
            config_path = Path("data/pet_appearance.json")
        _appearance = PetAppearance.load_from_file(config_path)

    return _appearance


def save_appearance(appearance: PetAppearance, config_path: Optional[Path] = None):
    """Save pet appearance configuration."""
    if config_path is None:
        config_path = Path("data/pet_appearance.json")
    appearance.save_to_file(config_path)

    global _appearance
    _appearance = appearance
