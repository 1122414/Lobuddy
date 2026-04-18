"""Tool policy definitions for Lobuddy."""

import re
from enum import Enum


class ToolCategory(str, Enum):
    """Tool categories."""

    FILESYSTEM = "filesystem"
    WEB = "web"
    SHELL = "shell"
    CUSTOM = "custom"


class ToolPolicy:
    """Defines which tools are enabled and under what conditions."""

    # Substring patterns (specific enough to avoid false positives)
    DANGEROUS_PATTERNS = {
        "rm -rf",
        "rm -fr",
        "del /f",
        "del /s /q",
        "del /q /s",
        ":(){ :|:& };:",
        "powershell -command",
        "invoke-expression",
    }

    # Regex patterns with word boundaries to avoid false positives
    DANGEROUS_REGEX = [
        re.compile(r"\biex\s*\("),
        re.compile(r"\bformat\b"),
        re.compile(r"\bshutdown\b"),
        re.compile(r"\breboot\b"),
        re.compile(r"\bmkfs"),
        re.compile(r"\bdd\s+if="),
        re.compile(r"\brd\s+/s(?:\s+/q)?\b"),
        re.compile(r"\brmdir\s+/s(?:\s+/q)?\b"),
    ]

    def __init__(self, shell_enabled: bool = False):
        self.shell_enabled = shell_enabled

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed."""
        if tool_name in {"exec", "shell"}:
            return self.shell_enabled
        return True

    def is_command_dangerous(self, command: str) -> bool:
        """Check if a shell command contains dangerous patterns."""
        # Normalize: lowercase, collapse extra whitespace
        cmd_lower = " ".join(command.lower().split())
        if any(pattern in cmd_lower for pattern in self.DANGEROUS_PATTERNS):
            return True
        # Check regex patterns (e.g., iex with optional whitespace)
        if any(rx.search(command.lower()) for rx in self.DANGEROUS_REGEX):
            return True
        return False
