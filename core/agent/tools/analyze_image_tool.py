import logging
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

from app.config import Settings
from core.agent.image_validation import validate_image_file
from core.agent.subagent_factory import SubagentFactory

logger = logging.getLogger("lobuddy.analyze_image_tool")


@tool_parameters(
    tool_parameters_schema(
        path=StringSchema("Absolute path to the image file (optional if image was uploaded)"),
        prompt=StringSchema("What to analyze in the image"),
        required=["prompt"],
    )
)
class AnalyzeImageTool(Tool):
    def __init__(
        self,
        default_image_path: str | None,
        settings: Settings,
        subagent_factory: SubagentFactory,
    ):
        self._default_image_path = default_image_path
        self._settings = settings
        self._subagent_factory = subagent_factory

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

    async def execute(self, path: str = "", prompt: str = "", **kwargs: Any) -> str:
        effective_path = path or self._default_image_path
        if path and path != self._default_image_path:
            logger.warning("analyze_image rejected mismatched path: %s", path)
            return "Error: Invalid image path."
        if not effective_path:
            return "Error: No image path provided."

        try:
            validate_image_file(effective_path)
            return await self._subagent_factory.run_image_analysis(prompt, effective_path)
        except ValueError as exc:
            logger.warning("Image validation failed: %s", exc)
            return f"Error: {exc}"
        except Exception:
            logger.exception("analyze_image tool failed")
            return "Error: Failed to analyze image."
