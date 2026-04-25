"""Pet asset service for Lobuddy."""

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ValidationResult:
    valid: bool
    error: str = ""


class PetAssetService:
    """Handles pet asset upload, validation, and storage."""

    SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    MAX_SIZE_MB = 20

    def __init__(self, data_dir: Path = None):
        if data_dir is None:
            data_dir = Path("data")
        self.pets_dir = data_dir / "user_assets" / "pets"
        self.pets_dir.mkdir(parents=True, exist_ok=True)

    def validate_asset(self, path: Path) -> ValidationResult:
        if not path.exists():
            return ValidationResult(False, "File does not exist.")

        if not path.is_file():
            return ValidationResult(False, "Path is not a file.")

        ext = path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            return ValidationResult(
                False, f"Unsupported file type: {ext}. Supported: {', '.join(self.SUPPORTED_EXTENSIONS)}"
            )

        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > self.MAX_SIZE_MB:
            return ValidationResult(
                False, f"File too large: {size_mb:.1f}MB. Max: {self.MAX_SIZE_MB}MB."
            )

        return ValidationResult(True)

    def detect_asset_type(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext == ".gif":
            return "gif"
        if ext in {".png", ".jpg", ".jpeg", ".webp"}:
            return "image"
        return "invalid"

    def copy_to_app_data(self, source_path: Path) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = source_path.suffix.lower()
        filename = f"pet_{timestamp}{ext}"
        dest_path = self.pets_dir / filename
        shutil.copy2(str(source_path), str(dest_path))
        return dest_path

    def remove_asset(self, path: Path) -> bool:
        try:
            if path.exists() and path.is_file():
                path.unlink()
                return True
        except OSError:
            pass
        return False
