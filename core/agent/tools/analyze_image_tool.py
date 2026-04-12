"""Nanobot tool for image analysis via sub-agent."""

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

from app.config import Settings
from core.agent.image_analyzer import ImageAnalyzer


@tool_parameters(
    tool_parameters_schema(
        path=StringSchema("Absolute path to the image file"),
        prompt=StringSchema("What to analyze in the image"),
        required=["path", "prompt"],
    )
)
class AnalyzeImageTool(Tool):
    """Tool that delegates image analysis to a multimodal sub-agent."""

    def __init__(self, default_image_path: str | None, settings: Settings):
        self._default_image_path = default_image_path
        self._analyzer = ImageAnalyzer(settings)

    @property
    def name(self) -> str:
        return "analyze_image"

    @property
    def description(self) -> str:
        return (
            "Analyze an image using a multimodal vision model. "
            "Use this when the user uploaded an image and you need visual understanding "
            "to answer their question. Provide a specific prompt about what to look for."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, path: str, prompt: str, **kwargs: Any) -> str:
        effective_path = path or self._default_image_path
        if not effective_path:
            return "Error: No image path provided."
        return await self._analyzer.analyze(effective_path, prompt)
