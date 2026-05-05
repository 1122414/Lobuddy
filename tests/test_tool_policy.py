"""Tests for tool policy and guardrails."""

import pytest
from pathlib import Path

from core.tools.tool_policy import ToolPolicy
from core.safety.guardrails import SafetyGuardrails
from core.safety.command_risk import CommandRiskAction


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

    def test_git_blocked_options(self):
        policy = ToolPolicy(shell_enabled=True)
        assert policy.validate_command("git --git-dir=/tmp status")[0] is False
        assert policy.validate_command("git --work-tree=/tmp status")[0] is False
        assert policy.validate_command("git --exec-path=/tmp status")[0] is False
        assert policy.validate_command("git --config-env=alias.x=ENV status")[0] is False
        assert policy.validate_command('git -c alias.pwn="!echo X" status')[0] is False
        assert policy.validate_command("git -C/tmp status")[0] is False
        assert policy.validate_command("git -ccore.worktree=/tmp status")[0] is False

    def test_git_blocked_subcommands(self):
        policy = ToolPolicy(shell_enabled=True)
        assert policy.validate_command("git config alias.pwn '!echo X'")[0] is False
        assert policy.validate_command("git pwn")[0] is False
        assert policy.validate_command("git pull")[0] is False
        assert policy.validate_command("git clean -fdx")[0] is False

    def test_git_safe_commands(self):
        policy = ToolPolicy(shell_enabled=True)
        assert policy.validate_command("git status")[0] is True
        assert policy.validate_command("git log")[0] is True
        assert policy.validate_command("git diff")[0] is True
        assert policy.validate_command("git show HEAD")[0] is True
        assert policy.validate_command("git blame file.txt")[0] is True

    def test_git_blocked_subcommand_options(self):
        policy = ToolPolicy(shell_enabled=True)
        assert policy.validate_command("git diff --output=/tmp/x")[0] is False
        assert policy.validate_command("git diff --output /tmp/x")[0] is False
        assert policy.validate_command("git diff -o../../x")[0] is False
        assert policy.validate_command("git diff --out=../../x")[0] is False
        assert policy.validate_command("git diff --no-index a b")[0] is False
        assert policy.validate_command("git diff --ext-diff")[0] is False
        assert policy.validate_command("git diff --ext")[0] is False
        assert policy.validate_command("git diff --pat")[0] is False
        assert policy.validate_command("git diff -po../../x")[0] is False
        assert policy.validate_command("git diff -Rpo../../x")[0] is False

    def test_git_safe_subcommand_options(self):
        policy = ToolPolicy(shell_enabled=True)
        assert policy.validate_command("git status -uno")[0] is True
        assert policy.validate_command("git diff -p")[0] is True
        # Clusters must use separate flags to prevent hidden -o bypasses
        assert policy.validate_command("git diff -p -R")[0] is True

    def test_git_blocked_short_clusters(self):
        policy = ToolPolicy(shell_enabled=True)
        assert policy.validate_command("git diff -pR")[0] is False
        assert policy.validate_command("git diff -Rp")[0] is False
        assert policy.validate_command("git log -Sfoo")[0] is False
        assert policy.validate_command("git diff -po../../x")[0] is False
        assert policy.validate_command("git diff -Rpo../../x")[0] is False

    def test_command_chaining_blocked(self):
        """Test that shell chaining operators are blocked (bypass prevention)."""
        policy = ToolPolicy(shell_enabled=True)
        assert policy.is_command_dangerous("echo safe; rm -rf /") is True
        assert policy.is_command_dangerous("cd ..; rm -rf /") is True
        assert policy.is_command_dangerous("echo safe && rm -rf /") is True
        assert policy.is_command_dangerous("cat file | rm -rf /") is True
        assert policy.is_command_dangerous("echo x > /etc/passwd") is True

    def test_cd_blocked(self):
        """Test that cd/pushd/popd are blocked to prevent working dir escape."""
        policy = ToolPolicy(shell_enabled=True)
        assert policy.is_command_dangerous("cd /tmp") is True
        assert policy.is_command_dangerous("pushd /tmp") is True
        assert policy.is_command_dangerous("popd") is True


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

    # ---- HITL guardrails path-level tests (P0-2) ----

    @pytest.fixture
    def ws_guardrails(self, tmp_path):
        """Create guardrails with tmp_path as workspace."""
        return SafetyGuardrails(tmp_path)

    def test_assess_delete_in_workspace_is_hitl(self, ws_guardrails, tmp_path):
        target = tmp_path / "temp.txt"
        target.write_text("test")
        result = ws_guardrails.assess_shell_command(f"rm {target}")
        assert result.action == CommandRiskAction.HITL_REQUIRED

    def test_assess_delete_outside_workspace_is_deny(self, ws_guardrails):
        result = ws_guardrails.assess_shell_command("rm /etc/passwd")
        assert result.action == CommandRiskAction.DENY

    def test_assess_delete_workspace_root_is_deny(self, ws_guardrails, tmp_path):
        result = ws_guardrails.assess_shell_command(f"rm -rf {tmp_path}")
        assert result.action == CommandRiskAction.DENY

    def test_assess_delete_home_root_is_deny(self, ws_guardrails):
        home = str(Path.home())
        result = ws_guardrails.assess_shell_command(f"rm -rf {home}")
        assert result.action == CommandRiskAction.DENY

    def test_assess_delete_wildcard_is_deny(self, ws_guardrails):
        result = ws_guardrails.assess_shell_command("rm *.tmp")
        assert result.action == CommandRiskAction.DENY

    def test_assess_safe_command_is_allow(self, ws_guardrails):
        result = ws_guardrails.assess_shell_command("ls -la")
        assert result.action == CommandRiskAction.ALLOW

    def test_assess_format_is_deny(self, ws_guardrails):
        result = ws_guardrails.assess_shell_command("format C:")
        assert result.action == CommandRiskAction.DENY

    def test_validate_shell_command_still_blocks_hitl(self, ws_guardrails, tmp_path):
        target = tmp_path / "temp.txt"
        target.write_text("test")
        result = ws_guardrails.validate_shell_command(f"rm {target}")
        assert result is not None
        assert "blocked" in result.lower()

    def test_protected_target_root_is_protected(self, ws_guardrails):
        assert ws_guardrails._is_protected_delete_target(Path("/")) is True

    def test_protected_target_workspace_root_is_protected(self, ws_guardrails, tmp_path):
        assert ws_guardrails._is_protected_delete_target(tmp_path) is True

    def test_protected_target_subdir_is_not_protected(self, ws_guardrails, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        assert ws_guardrails._is_protected_delete_target(sub) is False
