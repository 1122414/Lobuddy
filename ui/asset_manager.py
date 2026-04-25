"""Asset manager for UI resources."""

from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QMovie, QPainter, QPixmap

from core.models.appearance import get_appearance
from core.models.pet import TaskStatus


class AssetManager:
    """Manages UI assets with lazy loading and caching."""

    _instance: Optional["AssetManager"] = None
    _pixmap_cache: Dict[str, QPixmap] = {}
    _MAX_CACHE_SIZE = 50

    def __new__(cls) -> "AssetManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        self.assets_dir = Path(__file__).parent / "assets"
        self.appearance = get_appearance()
        if not getattr(self, "_initialized", False):
            self._ensure_assets_exist()
            self._initialized = True

    def _ensure_assets_exist(self):
        """Create placeholder assets if they don't exist."""
        self.assets_dir.mkdir(exist_ok=True)

        # Create default placeholder images if user images don't exist
        placeholders = {
            "pet_idle": ("#4CAF50", "IDLE"),
            "pet_running": ("#2196F3", "RUN"),
            "pet_success": ("#8BC34A", "OK"),
            "pet_error": ("#F44336", "ERR"),
            "icon_tray": ("#9C27B0", "L"),
            "icon_app": ("#9C27B0", "LB"),
        }

        for basename, (color, text) in placeholders.items():
            if not list(self.assets_dir.glob(f"{basename}.*")):
                self._create_placeholder(self.assets_dir / f"{basename}.png", color, text)

    def _create_placeholder(self, filepath: Path, color: str, text: str):
        size = 128 if "pet_" in filepath.name else 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        radius = 12 if "pet_" in filepath.name else 8
        painter.drawRoundedRect(pixmap.rect().adjusted(2, 2, -2, -2), radius, radius)

        font = QFont("Arial", 16 if "pet_" in filepath.name else 20)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("white"))

        painter.drawText(
            pixmap.rect(),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )

        painter.end()
        pixmap.save(str(filepath))

    def _is_valid_gif(self, path: Path) -> bool:
        if not path.exists() or path.suffix.lower() != ".gif":
            return False
        movie = QMovie(str(path))
        valid = movie.isValid()
        movie.deleteLater()
        return valid

    def _resolve_pet_image_path(self, state: TaskStatus) -> Path:
        if getattr(self.appearance, "custom_asset_path", None):
            custom = Path(self.appearance.custom_asset_path)
            if custom.exists():
                return custom

        state_map = {
            TaskStatus.IDLE: self.appearance.idle_image,
            TaskStatus.CREATED: self.appearance.idle_image,
            TaskStatus.QUEUED: self.appearance.idle_image,
            TaskStatus.RUNNING: self.appearance.running_image,
            TaskStatus.SUCCESS: self.appearance.success_image,
            TaskStatus.FAILED: self.appearance.error_image,
            TaskStatus.CANCELLED: self.appearance.idle_image,
        }
        filename = state_map.get(state, self.appearance.idle_image)
        filepath = self.assets_dir / filename
        if filepath.exists():
            if filepath.suffix.lower() == ".gif" and not self._is_valid_gif(filepath):
                fallback = self.assets_dir / f"{filepath.stem}.png"
                if fallback.exists():
                    return fallback
            return filepath

        stem = Path(filename).stem
        candidates = sorted(self.assets_dir.glob(f"{stem}.*"))
        for candidate in candidates:
            if candidate.suffix.lower() == ".gif":
                if self._is_valid_gif(candidate):
                    return candidate
                continue
            return candidate
        return filepath

    def _resolve_tray_image_path(self) -> Path:
        gif_path = self.assets_dir / "icon_tray.gif"
        if self._is_valid_gif(gif_path):
            return gif_path

        stem = "icon_tray"
        candidates = sorted(self.assets_dir.glob(f"{stem}.*"))
        for candidate in candidates:
            if candidate == gif_path:
                continue
            if candidate.suffix.lower() == ".gif":
                if self._is_valid_gif(candidate):
                    return candidate
                continue
            return candidate
        return self.assets_dir / "icon_tray.png"

    def get_pet_pixmap(self, state: TaskStatus, size: int = None) -> QPixmap:
        if size is None:
            size = self.appearance.width

        cache_key = f"{state.value}_{size}"
        if cache_key in self._pixmap_cache:
            return self._pixmap_cache[cache_key]

        filepath = self._resolve_pet_image_path(state)
        if filepath.exists():
            pixmap = QPixmap(str(filepath))
        else:
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.gray)

        if not pixmap.isNull() and (pixmap.width() != size or pixmap.height() != size):
            pixmap = pixmap.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        self._enforce_cache_limit()
        self._pixmap_cache[cache_key] = pixmap
        return pixmap

    def _enforce_cache_limit(self):
        while len(self._pixmap_cache) >= self._MAX_CACHE_SIZE:
            oldest_key = next(iter(self._pixmap_cache))
            del self._pixmap_cache[oldest_key]

    def get_pet_movie(self, state: TaskStatus, size: int = None) -> QMovie | None:
        filepath = self._resolve_pet_image_path(state)
        if not filepath.exists() or filepath.suffix.lower() != ".gif":
            return None
        if size is None:
            size = self.appearance.width
        movie = QMovie(str(filepath))
        movie.setScaledSize(QSize(size, size))
        if not movie.isValid():
            movie.deleteLater()
            return None
        return movie

    def get_tray_movie(self) -> QMovie | None:
        filepath = self._resolve_tray_image_path()
        if filepath.suffix.lower() != ".gif" or not filepath.exists():
            return None
        movie = QMovie(str(filepath))
        if not movie.isValid():
            movie.deleteLater()
            return None
        return movie

    def get_tray_icon(self) -> QIcon:
        """Get system tray icon."""
        filepath = self._resolve_tray_image_path()
        if filepath.exists():
            return QIcon(str(filepath))
        return QIcon()


