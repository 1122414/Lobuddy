"""5.4 ToolPolicy chain detection regression tests for execution governance."""

import pytest
from core.tools.tool_policy import ToolPolicy


class TestToolPolicyChainDetection54:
    """Verify ToolPolicy blocks Windows command chaining with redirection."""

    def test_blocks_ampersand_chaining_with_redirection(self):
        policy = ToolPolicy()
        command = (
            'where /R "%USERPROFILE%\\Desktop" 洛克* 2>nul & '
            'dir /s /b "%USERPROFILE%\\Desktop\\*洛克*" 2>nul'
        )
        allowed, reason = policy.validate_command(command)
        assert allowed is False, f"Expected chaining to be blocked, got allowed=True"

    def test_blocks_semicolon_chaining(self):
        policy = ToolPolicy()
        allowed, reason = policy.validate_command("dir /s; where /R foo*")
        assert allowed is False

    def test_blocks_pipe_chaining(self):
        policy = ToolPolicy()
        allowed, reason = policy.validate_command("dir /s | findstr foo")
        assert allowed is False

    def test_blocks_double_ampersand(self):
        policy = ToolPolicy()
        allowed, reason = policy.validate_command("cmd1 && cmd2")
        assert allowed is False

    def test_allows_simple_commands(self):
        policy = ToolPolicy()
        allowed, _ = policy.validate_command("dir Desktop")
        assert allowed is True

    def test_where_r_not_blocked_by_tool_policy(self):
        """where /R is a task-level concern, not a ToolPolicy security concern.
        ExecutionGovernanceHook blocks where /R for LOCAL_OPEN_TARGET, not ToolPolicy."""
        policy = ToolPolicy()
        allowed, reason = policy.validate_command('where /R "C:\\Users" 洛克*')
        assert allowed is True, "where /R should NOT be blocked by ToolPolicy (task rule)"

    def test_dir_s_not_blocked_by_tool_policy(self):
        """dir /s is a task-level concern, handled by ExecutionGovernanceHook."""
        policy = ToolPolicy()
        allowed, reason = policy.validate_command('dir /s /b "C:\\Users"')
        assert allowed is True, "dir /s should NOT be blocked by ToolPolicy (task rule)"
