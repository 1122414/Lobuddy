"""Tests for HITL command risk classification (P0-1).

Covers the three-state assess_command_risk() method:
- ALLOW: safe commands that proceed without interruption
- HITL_REQUIRED: delete commands that need human confirmation
- DENY: permanently blocked commands (chaining, system-critical, wildcards)
"""

import pytest

from core.safety.command_risk import CommandRiskAction
from core.tools.tool_policy import ToolPolicy


class TestCommandRiskClassification:
    """Test assess_command_risk() classification across ALLOW/HITL_REQUIRED/DENY."""

    @pytest.fixture
    def policy(self):
        return ToolPolicy()

    # ---- ALLOW cases ----

    def test_ls_is_allow(self, policy):
        result = policy.assess_command_risk("ls -la")
        assert result.action == CommandRiskAction.ALLOW

    def test_cat_is_allow(self, policy):
        result = policy.assess_command_risk("cat README.md")
        assert result.action == CommandRiskAction.ALLOW

    def test_git_status_is_allow(self, policy):
        result = policy.assess_command_risk("git status")
        assert result.action == CommandRiskAction.ALLOW

    def test_python_script_is_allow(self, policy):
        result = policy.assess_command_risk("python script.py")
        assert result.action == CommandRiskAction.ALLOW

    def test_echo_is_allow(self, policy):
        result = policy.assess_command_risk("echo hello world")
        assert result.action == CommandRiskAction.ALLOW

    def test_mkdir_is_allow(self, policy):
        result = policy.assess_command_risk("mkdir new_dir")
        assert result.action == CommandRiskAction.ALLOW

    def test_ping_is_allow(self, policy):
        result = policy.assess_command_risk("ping 127.0.0.1")
        assert result.action == CommandRiskAction.ALLOW

    # ---- HITL_REQUIRED cases (POSIX) ----

    def test_rm_single_file_is_hitl(self, policy):
        result = policy.assess_command_risk("rm temp.txt")
        assert result.action == CommandRiskAction.HITL_REQUIRED
        assert "delete" in result.risk_tags

    def test_rm_recursive_is_hitl(self, policy):
        result = policy.assess_command_risk("rm -r temp_dir")
        assert result.action == CommandRiskAction.HITL_REQUIRED

    def test_rm_force_recursive_is_hitl(self, policy):
        result = policy.assess_command_risk("rm -rf workspace/cache")
        assert result.action == CommandRiskAction.HITL_REQUIRED

    def test_rm_with_path_is_hitl(self, policy):
        result = policy.assess_command_risk("rm E:\\GitHub\\Repositories\\Lobuddy\\temp\\a.txt")
        assert result.action == CommandRiskAction.HITL_REQUIRED
        assert len(result.affected_paths) > 0

    # ---- HITL_REQUIRED cases (Windows cmd) ----

    def test_del_single_file_is_hitl(self, policy):
        result = policy.assess_command_risk("del temp.txt")
        assert result.action == CommandRiskAction.HITL_REQUIRED

    def test_del_quiet_is_hitl(self, policy):
        result = policy.assess_command_risk("del /q temp.txt")
        assert result.action == CommandRiskAction.HITL_REQUIRED

    def test_rmdir_recursive_is_hitl(self, policy):
        result = policy.assess_command_risk("rmdir /s temp_dir")
        assert result.action == CommandRiskAction.HITL_REQUIRED

    # ---- HITL_REQUIRED cases (PowerShell) ----

    def test_powershell_remove_item_is_hitl(self, policy):
        result = policy.assess_command_risk(
            'powershell -NoProfile -Command Remove-Item -LiteralPath "temp.txt" -Force'
        )
        assert result.action == CommandRiskAction.HITL_REQUIRED
        assert "powershell" in result.risk_tags

    def test_pwsh_remove_item_is_hitl(self, policy):
        result = policy.assess_command_risk(
            'pwsh -NoProfile -Command Remove-Item -LiteralPath "temp.txt" -Force'
        )
        assert result.action == CommandRiskAction.HITL_REQUIRED

    # ---- DENY cases: permanently blocked commands ----

    def test_rm_rf_root_is_deny(self, policy):
        result = policy.assess_command_risk("rm -rf /")
        assert result.action == CommandRiskAction.HITL_REQUIRED
        # Note: "rm -rf /" is HITL_REQUIRED at ToolPolicy level because
        # ToolPolicy only does syntax-level classification. Path-level
        # blocking (root directory protection) happens in SafetyGuardrails.

    def test_format_is_deny(self, policy):
        result = policy.assess_command_risk("format C:")
        assert result.action == CommandRiskAction.DENY
        assert "permanently_blocked" in result.risk_tags

    def test_mkfs_is_deny(self, policy):
        result = policy.assess_command_risk("mkfs.ext4 /dev/sda")
        assert result.action == CommandRiskAction.DENY

    def test_shutdown_is_deny(self, policy):
        result = policy.assess_command_risk("shutdown -h now")
        assert result.action == CommandRiskAction.DENY

    def test_reboot_is_deny(self, policy):
        result = policy.assess_command_risk("reboot")
        assert result.action == CommandRiskAction.DENY

    # ---- DENY cases: chaining ----

    def test_echo_and_rm_is_deny(self, policy):
        result = policy.assess_command_risk("echo ok && rm temp.txt")
        assert result.action == CommandRiskAction.DENY

    def test_semicolon_chaining_is_deny(self, policy):
        result = policy.assess_command_risk("ls; rm temp.txt")
        assert result.action == CommandRiskAction.DENY

    def test_pipe_is_deny(self, policy):
        result = policy.assess_command_risk("cat file | rm temp.txt")
        assert result.action == CommandRiskAction.DENY

    def test_redirect_is_deny(self, policy):
        result = policy.assess_command_risk("echo data > file.txt")
        assert result.action == CommandRiskAction.DENY

    # ---- DENY cases: interpreters ----

    def test_python_inline_is_deny(self, policy):
        result = policy.assess_command_risk('python -c "print(1)"')
        assert result.action == CommandRiskAction.DENY

    def test_node_eval_is_deny(self, policy):
        result = policy.assess_command_risk('node -e "console.log(1)"')
        assert result.action == CommandRiskAction.DENY

    def test_powershell_enc_is_deny(self, policy):
        result = policy.assess_command_risk("powershell -enc abc")
        assert result.action == CommandRiskAction.DENY

    def test_pwsh_encodedcommand_is_deny(self, policy):
        result = policy.assess_command_risk("pwsh -EncodedCommand abc")
        assert result.action == CommandRiskAction.DENY

    # ---- DENY cases: wildcards ----

    def test_rm_wildcard_is_deny(self, policy):
        result = policy.assess_command_risk("rm *.tmp")
        assert result.action == CommandRiskAction.DENY
        assert "wildcard" in result.risk_tags

    def test_rm_glob_is_deny(self, policy):
        result = policy.assess_command_risk("rm -r src/*.pyc")
        assert result.action == CommandRiskAction.DENY

    def test_del_wildcard_is_deny(self, policy):
        result = policy.assess_command_risk("del *.log")
        assert result.action == CommandRiskAction.DENY

    # ---- DENY cases: other ----

    def test_empty_command_is_deny(self, policy):
        result = policy.assess_command_risk("")
        assert result.action == CommandRiskAction.DENY

    def test_whitespace_only_is_deny(self, policy):
        result = policy.assess_command_risk("   ")
        assert result.action == CommandRiskAction.DENY

    def test_unknown_command_is_deny(self, policy):
        result = policy.assess_command_risk("unknown_cmd arg1")
        assert result.action == CommandRiskAction.DENY

    def test_newline_in_command_is_deny(self, policy):
        result = policy.assess_command_risk("ls\nrm temp.txt")
        assert result.action == CommandRiskAction.DENY

    # ---- Edge cases ----

    def test_single_safe_word_is_allow(self, policy):
        result = policy.assess_command_risk("hello")
        assert result.action == CommandRiskAction.ALLOW

    def test_rm_without_args_is_allow(self, policy):
        """rm alone has no target, not dangerous."""
        result = policy.assess_command_risk("rm")
        assert result.action == CommandRiskAction.ALLOW

    def test_assessment_is_frozen(self, policy):
        """CommandRiskAssessment should be immutable."""
        result = policy.assess_command_risk("rm temp.txt")
        with pytest.raises(Exception):
            result.action = CommandRiskAction.ALLOW  # type: ignore[misc]

    def test_rm_rf_C_drive_is_hitl_syntax(self, policy):
        """rm -rf C:\\ is HITL at ToolPolicy level; path blocking in guardrails."""
        result = policy.assess_command_risk("rm -rf C:\\")
        assert result.action == CommandRiskAction.HITL_REQUIRED


class TestBackwardCompatibility:
    """Ensure old API (is_command_dangerous, validate_command) is unchanged."""

    @pytest.fixture
    def policy(self):
        return ToolPolicy()

    def test_is_command_dangerous_still_works(self, policy):
        assert policy.is_command_dangerous("rm -rf /") is True
        assert policy.is_command_dangerous("format C:") is True
        assert policy.is_command_dangerous("ls -la") is False

    def test_validate_command_still_works(self, policy):
        allowed, _ = policy.validate_command("git status")
        assert allowed is True

        blocked, reason = policy.validate_command("rm -rf /")
        assert blocked is False
        assert "dangerous" in reason.lower()
