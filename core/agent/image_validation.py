"""Image validation utilities."""

import base64
from pathlib import Path

_MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


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


def validate_image_file(path: str | Path) -> bytes:
    """Validate an image file and return its bytes.

    Raises:
        ValueError: If the file does not exist, has an unsupported extension,
            exceeds the size limit, or fails magic-byte validation.
    """
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"Image file not found: {p.name}")

    file_ext = p.suffix.lower()
    if file_ext not in _ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{file_ext}'. Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
        )

    data = p.read_bytes()
    if len(data) > _MAX_IMAGE_SIZE:
        raise ValueError(
            f"Image file is too large ({len(data) / 1024 / 1024:.1f} MB). "
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
