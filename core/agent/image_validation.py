"""Image validation and compression utilities."""

import base64
import io
import logging
from pathlib import Path

_MAX_IMAGE_SIZE = 5 * 1024 * 1024
_ALLOWABLE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

logger = logging.getLogger("lobuddy.image_validation")


def _is_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")


def _is_jpeg(data: bytes) -> bool:
    return data.startswith(b"\xff\xd8\xff")


def _is_gif(data: bytes) -> bool:
    return data.startswith((b"GIF87a", b"GIF89a"))


def _is_webp(data: bytes) -> bool:
    return data.startswith(b"RIFF") and len(data) > 12 and data[8:12] == b"WEBP"


def _is_svg(data: bytes) -> bool:
    if data.startswith(b"\xef\xbb\xbf"):
        text = data[3:].decode("utf-8", errors="ignore")
    else:
        text = data.decode("utf-8", errors="ignore")
    stripped = text.lstrip()
    return stripped.startswith("<svg") or (stripped.startswith("<?xml") and "<svg" in stripped)


def _detect_image_mime(data: bytes) -> str | None:
    if _is_jpeg(data):
        return "image/jpeg"
    if _is_png(data):
        return "image/png"
    if _is_gif(data):
        return "image/gif"
    if _is_webp(data):
        return "image/webp"
    if _is_svg(data):
        return "image/svg+xml"
    return None


def _compress_image_to_target(data: bytes, target_size: int = _MAX_IMAGE_SIZE) -> bytes:
    """Compress image data to fit within target size using Pillow."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))

        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        quality = 85
        while quality >= 30:
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            compressed = buffer.getvalue()

            if len(compressed) <= target_size:
                logger.info(
                    f"Image compressed from {len(data) / 1024 / 1024:.1f}MB to "
                    f"{len(compressed) / 1024 / 1024:.1f}MB at quality={quality}"
                )
                return compressed

            quality -= 10

        scale = 0.8
        while scale >= 0.3:
            new_size = (int(img.width * scale), int(img.height * scale))
            resized = img.resize(new_size, Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            resized.save(buffer, format="JPEG", quality=70, optimize=True)
            compressed = buffer.getvalue()

            if len(compressed) <= target_size:
                logger.info(
                    f"Image resized and compressed from "
                    f"{len(data) / 1024 / 1024:.1f}MB to {len(compressed) / 1024 / 1024:.1f}MB "
                    f"at scale={scale:.1f}"
                )
                return compressed

            scale -= 0.1

        logger.warning(f"Could not compress image below {target_size / 1024 / 1024:.0f}MB")
        return data

    except Exception as exc:
        logger.warning(f"Image compression failed: {exc}")
        return data


def validate_image_file(path: str | Path, compress: bool = True) -> bytes:
    """Validate an image file and return its bytes.

    If compress=True and image exceeds size limit, attempts to compress
    the image before raising an error.

    Raises:
        ValueError: If the file does not exist, has an unsupported extension,
            exceeds the size limit and cannot be compressed, or fails validation.
    """
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"Image file not found: {p.name}")

    file_ext = p.suffix.lower()
    if file_ext not in _ALLOWABLE_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{file_ext}'. Allowed: {', '.join(sorted(_ALLOWABLE_EXTENSIONS))}"
        )

    data = p.read_bytes()
    original_size = len(data)

    if original_size > _MAX_IMAGE_SIZE:
        if compress and file_ext not in (".svg", ".gif"):
            logger.info(
                f"Image {original_size / 1024 / 1024:.1f}MB exceeds limit, attempting compression"
            )
            data = _compress_image_to_target(data, _MAX_IMAGE_SIZE)

        if len(data) > _MAX_IMAGE_SIZE:
            raise ValueError(
                f"Image file is too large ({original_size / 1024 / 1024:.1f} MB). "
                f"Maximum allowed size is {_MAX_IMAGE_SIZE / 1024 / 1024:.0f} MB."
            )

    mime_type = _detect_image_mime(data)
    if mime_type is None:
        raise ValueError("File does not appear to be a valid image.")

    return data


def image_to_base64_data_url(data: bytes, mime_type: str) -> str:
    subtype = mime_type.removeprefix("image/")
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:image/{subtype};base64,{b64}"
