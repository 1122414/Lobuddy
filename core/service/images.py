"""Validated native image imports; renderer references opaque content IDs only."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import stat
import tempfile
import warnings
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from core.agent.image_validation import _compress_image_to_target

FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
EXTENSIONS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".gif": "GIF", ".webp": "WEBP"}
MAX_BYTES = 5 * 1024 * 1024


class ImageImport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, max_length=4096)


class ImageReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    image_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class ImageInfo(ImageReference):
    media_type: str
    width: int
    height: int
    preview: str


class ImageStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    @staticmethod
    def _read(path: Path, limit: int) -> bytes:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError("图片必须是大小合适的普通文件")
            data = source.read(limit + 1)
        if not data or len(data) > limit:
            raise ValueError("图片为空或超过大小限制")
        return data

    @staticmethod
    def _decode(data: bytes) -> tuple[str, int, int, str]:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in FORMATS:
                    raise ValueError("仅支持 PNG、JPEG、GIF 和 WebP 图片")
                fmt = image.format
                width, height = image.size
                if max(width, height) > 16384 or width * height > 40_000_000:
                    raise ValueError("图片尺寸超过限制")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                image.thumbnail((320, 320))
                preview = io.BytesIO()
                image.convert("RGB").save(preview, "JPEG", quality=75)
        return (
            fmt,
            width,
            height,
            "data:image/jpeg;base64," + base64.b64encode(preview.getvalue()).decode(),
        )

    def import_file(self, path: str) -> ImageInfo:
        source = Path(path)
        if not source.is_absolute() or source.suffix.lower() not in EXTENSIONS:
            raise ValueError("请选择支持的本地图片")
        data = self._read(source, 100 * 1024 * 1024)
        fmt, _, _, _ = self._decode(data)
        if EXTENSIONS[source.suffix.lower()] != fmt:
            raise ValueError("图片扩展名与实际格式不一致")
        if len(data) > MAX_BYTES:
            data = _compress_image_to_target(data)
        if len(data) > MAX_BYTES:
            raise ValueError("压缩后图片仍超过 5 MB")
        self._decode(data)
        identity = hashlib.sha256(data).hexdigest()
        target = self.root / identity
        if not target.exists():
            descriptor, temp = tempfile.mkstemp(dir=self.root)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temp, target)
            finally:
                Path(temp).unlink(missing_ok=True)
        return self.get(identity)

    def get(self, identity: str) -> ImageInfo:
        ImageReference(image_id=identity)
        data = self._read(self.root / identity, MAX_BYTES)
        if hashlib.sha256(data).hexdigest() != identity:
            raise ValueError("图片校验失败，请重新选择")
        fmt, width, height, preview = self._decode(data)
        return ImageInfo(
            image_id=identity, media_type=FORMATS[fmt], width=width, height=height, preview=preview
        )
