"""Tests for tool policy and guardrails."""

import pytest
from pathlib import Path

from core.tools.tool_policy import ToolPolicy
from core.safety.guardrails import SafetyGuardrails


class TestToolPolicy:
    """Test tool policy functionality."""

    def test_shell_disabled_by_default(self):
        """Test that shell tool is blocked by default."""
        policy = ToolPolicy()
        assert policy.is_tool_allowed("exec") is False
        assert policy.is_tool_allowed("shell") is False

    def test_shell_enabled(self):
        """Test that shell tool is allowed when enabled."""
        policy = ToolPolicy(shell_enabled=True)
        assert policy.is_tool_allowed("exec") is True
        assert policy.is_tool_allowed("shell") is True

    def test_other_tools_always_allowed(self):
        """Test that non-shell tools are always allowed."""
        policy = ToolPolicy()
        assert policy.is_tool_allowed("read_file") is True
        assert policy.is_tool_allowed("web_search") is True
        assert policy.is_tool_allowed("analyze_image") is True

    def test_dangerous_command_detection(self):
        """Test that dangerous commands are detected."""
        policy = ToolPolicy()
        assert policy.is_command_dangerous("rm -rf /") is True
        assert policy.is_command_dangerous("rm -fr /") is True
        assert policy.is_command_dangerous("format C:") is True
        assert policy.is_command_dangerous("shutdown -h now") is True

    def test_safe_command(self):
        """Test that safe commands are not flagged."""
        policy = ToolPolicy()
        assert policy.is_command_dangerous("ls -la") is False
        assert policy.is_command_dangerous("cat file.txt") is False
        assert policy.is_command_dangerous("python script.py") is False


class TestGuardrails:
    """Test safety guardrails."""

    def test_path_within_workspace(self):
        """Test that paths within workspace are allowed."""
        workspace = Path("/tmp/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_path("/tmp/workspace/file.txt")
        assert result is None

    def test_path_outside_workspace(self):
        """Test that paths outside workspace are blocked."""
        workspace = Path("/tmp/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_path("/etc/passwd")
        assert result is not None
        assert "outside workspace" in result

    def test_dangerous_shell_command(self):
        """Test that dangerous shell commands are blocked."""
        workspace = Path("/tmp/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_shell_command("rm -rf /")
        assert result is not None
        assert "Dangerous command" in result

    def test_safe_shell_command(self):
        """Test that safe shell commands are allowed."""
        workspace = Path("/tmp/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_shell_command("ls -la")
        assert result is None

    def test_blocked_url_scheme(self):
        """Test that blocked URL schemes are rejected."""
        workspace = Path("/tmp/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_web_url("file:///etc/passwd")
        assert result is not None
        assert "Blocked URL scheme" in result

    def test_allowed_url_scheme(self):
        """Test that allowed URL schemes are accepted."""
        workspace = Path("/tmp/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_web_url("https://example.com")
        assert result is None
