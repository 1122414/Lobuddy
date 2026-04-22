"""Tool registry for managing nanobot tool lifecycle."""

import logging
from typing import Any

from core.agent.nanobot_gateway import NanobotGateway

logger = logging.getLogger("lobuddy.tool_registry")


class ToolRegistry:
    """Manages temporary tool registration and cleanup for nanobot sessions."""

    @staticmethod
    def register_analyze_image(
        gateway: NanobotGateway,
        image_path: str,
        settings: Any,
        subagent_factory: Any,
    ) -> tuple[Any, Any]:
        """Register analyze_image tool and return (custom_tool, previous_tool)."""
        from core.agent.tools.analyze_image_tool import AnalyzeImageTool

        custom_tool = AnalyzeImageTool(image_path, settings, subagent_factory)
        previous_tool = gateway.get_tool(custom_tool.name)
        gateway.register_tool(custom_tool)
        return custom_tool, previous_tool

    @staticmethod
    def cleanup(gateway: NanobotGateway, custom_tool: Any, previous_tool: Any) -> None:
        """Restore original tool or unregister temporary tool."""
        if custom_tool is None:
            return
        try:
            if previous_tool is not None:
                gateway.register_tool(previous_tool)
            else:
                gateway.unregister_tool(custom_tool.name)
        except Exception as tool_cleanup_err:
            logger.warning(f"Failed to restore tool state: {tool_cleanup_err}")
