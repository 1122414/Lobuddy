"""Lightweight image analysis sub-agent."""

import base64
import logging
import mimetypes
from pathlib import Path

import httpx

from app.config import Settings

logger = logging.getLogger("lobuddy.image_analyzer")


class ImageAnalyzer:
    """Analyze images using a multimodal model via OpenAI-compatible API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def analyze(self, image_path: str, prompt: str) -> str:
        """Analyze an image and return the model's text response."""
        path = Path(image_path)
        if not path.is_file():
            error_msg = f"Error: Image file not found at {image_path}"
            logger.error(error_msg)
            return error_msg

        mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64}"

        model = self.settings.llm_multimodal_model or self.settings.llm_model
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
                    f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.llm_api_key}",
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
                content = data["choices"][0]["message"]["content"]
                logger.info("Image analysis completed (model=%s)", model)
                return str(content).strip()
        except httpx.TimeoutException:
            logger.error("Image analysis timed out")
            return "Error: Image analysis timed out"
        except Exception as e:
            logger.error("Image analysis failed: %s", e)
            return f"Error analyzing image: {e}"
