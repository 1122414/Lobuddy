"""5.4 LocalOpenTool — controlled opening of locally-resolved candidates."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, ClassVar

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

logger = logging.getLogger("lobuddy.local_open")

_UNSAFE_EXTENSIONS: tuple[str, ...] = (".bat", ".cmd", ".ps1", ".vbs", ".wsf", ".msi", ".reg")


@tool_parameters(
    tool_parameters_schema(
        path=StringSchema("Absolute path to open (must come from local_app_resolve candidates)"),
        source=StringSchema("Tool that found this candidate (must be local_app_resolve)"),
        required=["path", "source"],
    )
)
class LocalOpenTool(Tool):
    """Open a local file or shortcut that was previously identified by local_app_resolve.

    Only paths returned by local_app_resolve in the current task can be opened.
    Scripts (.bat, .cmd, .ps1) are rejected for safety.
    """

    BLOCKED_EXTS: ClassVar[tuple[str, ...]] = _UNSAFE_EXTENSIONS

    def __init__(self, resolver_candidates: list[dict[str, Any]] | None = None) -> None:
        self._resolver_candidates = resolver_candidates or []

    @property
    def name(self) -> str:
        return "local_open"

    @property
    def description(self) -> str:
        return (
            "Open a file or shortcut using the OS default handler. "
            "The path MUST come from a local_app_resolve result in the current task. "
            "Do NOT use for .bat/.cmd/.ps1 files or paths not returned by local_app_resolve."
        )

    @property
    def read_only(self) -> bool:
        return False

    async def execute(
        self,
        path: str = "",
        source: str = "local_app_resolve",
        **kwargs: Any,
    ) -> str:
        if not path:
            return json.dumps({"opened": False, "reason": "empty_path"})

        if source != "local_app_resolve":
            return json.dumps({
                "opened": False,
                "path": path,
                "reason": "source_must_be_local_app_resolve",
            })

        if self._resolver_candidates:
            allowed_paths = {c["path"] for c in self._resolver_candidates if c.get("path")}
            if path not in allowed_paths:
                return json.dumps({
                    "opened": False,
                    "path": path,
                    "reason": "path_not_from_resolver_candidates",
                })

        ext = Path(path).suffix.lower()
        if ext in self.BLOCKED_EXTS:
            return json.dumps({
                "opened": False,
                "path": path,
                "reason": f"blocked_extension_{ext}",
            })

        resolved = Path(path).resolve()
        if not resolved.exists():
            return json.dumps({
                "opened": False,
                "path": path,
                "reason": "path_not_found_on_disk",
            })

        if not hasattr(os, "startfile"):
            return json.dumps({
                "opened": False,
                "path": path,
                "reason": "os_startfile_not_available",
            })

        try:
            os.startfile(str(resolved))
            return json.dumps({
                "opened": True,
                "path": str(resolved),
                "message": "opened",
            }, ensure_ascii=False)
        except OSError as e:
            logger.warning("local_open failed for %s: %s", path, e)
            return json.dumps({
                "opened": False,
                "path": str(resolved),
                "reason": f"os_error_{e}",
            })
