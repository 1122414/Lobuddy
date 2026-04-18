"""Safety guardrails for Lobuddy tool execution."""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("lobuddy.guardrails")


class SafetyGuardrails:
    """Enforces safety rules on tool execution."""

    def __init__(self, workspace_path: Path):
        self.workspace_path = workspace_path.resolve()

    def validate_path(self, path: str) -> Optional[str]:
        """Validate that a path is within workspace."""
        try:
            # Reject ambiguous Windows drive-relative paths (e.g., C:secret.txt)
            import re

            if re.match(r"^[A-Za-z]:[^\\/]", path):
                return f"Ambiguous drive-relative path blocked: {path}"

            # Resolve relative paths against workspace, not CWD
            if not Path(path).is_absolute():
                target = (self.workspace_path / path).resolve()
            else:
                target = Path(path).resolve()

            # Check if target is within workspace
            try:
                target.relative_to(self.workspace_path)
                return None
            except ValueError:
                return f"Path {path} is outside workspace"
        except Exception as e:
            return f"Invalid path: {e}"

    def validate_shell_command(self, command: str) -> Optional[str]:
        """Validate shell command safety."""
        from core.tools.tool_policy import ToolPolicy

        policy = ToolPolicy()
        if policy.is_command_dangerous(command):
            return f"Dangerous command blocked: {command}"
        return None

    def validate_working_dir(self, working_dir: str) -> Optional[str]:
        """Validate that shell working directory is within workspace."""
        return self.validate_path(working_dir)

    def validate_web_url(self, url: str) -> Optional[str]:
        """Validate web URL safety."""
        blocked_schemes = {"file", "ftp", "data"}
        scheme = url.split("://")[0].lower() if "://" in url else ""
        if scheme in blocked_schemes:
            return f"Blocked URL scheme: {scheme}"
        return None
