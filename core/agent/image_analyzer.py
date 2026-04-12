"""Lightweight image analysis sub-agent."""

import base64
import logging
from pathlib import Path

import httpx

from app.config import Settings

logger = logging.getLogger("lobuddy.image_analyzer")

_MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".svg"}


def _is_svg(data: bytes) -> bool:
    """Check whether bytes represent an SVG by looking for <svg tag."""
    if data.startswith(b"\xef\xbb\xbf"):
        text = data[3:].decode("utf-8", errors="ignore")
    else:
        text = data.decode("utf-8", errors="ignore")
    stripped = text.lstrip()
    return stripped.startswith("<svg") or (stripped.startswith("<?xml") and "<svg" in stripped)


def _detect_image_mime(data: bytes) -> str | None:
    """Detect MIME type from image magic bytes."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith(b"RIFF") and len(data) > 12 and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if _is_svg(data):
        return "image/svg+xml"
    return None


class ImageAnalyzer:
    """Analyze images using a multimodal model via OpenAI-compatible API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def analyze(self, image_path: str, prompt: str) -> str:
        """Analyze an image and return the model's text response."""
        path = Path(image_path)
        if not path.is_file():
            logger.error("Image file not found: %s", image_path)
            return "Error: Image file not found."

        file_size = path.stat().st_size
        if file_size > _MAX_IMAGE_SIZE:
            logger.error(
                "Image file too large: %.1f MB",
                file_size / 1024 / 1024,
            )
            return (
                f"Error: Image file is too large ({file_size / 1024 / 1024:.1f} MB). "
                f"Maximum allowed size is {_MAX_IMAGE_SIZE / 1024 / 1024:.0f} MB."
            )

        file_ext = path.suffix.lower()
        if file_ext not in _ALLOWED_EXTENSIONS:
            logger.error("Unsupported file type: %s", file_ext)
            return f"Error: Unsupported file type '{file_ext}'. Only image files are allowed."

        data = path.read_bytes()
        mime_type = _detect_image_mime(data)
        if mime_type is None:
            logger.error("File does not appear to be a valid image: %s", image_path)
            return "Error: File does not appear to be a valid image."

        b64 = base64.b64encode(data).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64}"

        model = self.settings.llm_multimodal_model
        if not model:
            logger.error("LLM_MULTIMODAL_MODEL is not configured")
            return "Error: Multimodal model not configured. Please set LLM_MULTIMODAL_MODEL in .env"

        base_url = self.settings.llm_multimodal_base_url or self.settings.llm_base_url
        api_key = self.settings.llm_multimodal_api_key or self.settings.llm_api_key

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful image analysis assistant. "
                    "Describe the image accurately and concisely based on the user's request."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            },
        ]

        try:
            async with httpx.AsyncClient(timeout=self.settings.task_timeout) as client:
                resp = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": self.settings.llm_temperature,
                        "max_tokens": self.settings.llm_max_tokens,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices", [])
                if not choices:
                    logger.error("Empty choices in multimodal response")
                    return "Error: No response from image analysis model."
                content = choices[0].get("message", {}).get("content", "")
                logger.info("Image analysis completed (model=%s)", model)
                return str(content).strip()
        except httpx.TimeoutException:
            logger.error("Image analysis timed out")
            return "Error: Image analysis timed out"
        except httpx.HTTPStatusError as e:
            logger.error(
                "Image analysis HTTP error: status=%s",
                e.response.status_code,
            )
            return "Error: Image analysis service failed. Please try again later."
        except Exception:
            logger.exception("Image analysis failed")
            return "Error: Image analysis failed. Please try again later."
