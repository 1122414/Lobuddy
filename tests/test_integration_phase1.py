"""Integration tests for guardrails and ability persistence."""

import pytest
from pathlib import Path

from core.tools.tool_policy import ToolPolicy
from core.safety.guardrails import SafetyGuardrails
from core.abilities.ability_system import AbilityManager, AbilityRegistry
from core.storage.ability_repo import AbilityRepository


class TestGuardrailsIntegration:
    """Test guardrails with various path types."""

    def test_relative_path_in_workspace(self):
        """Test that relative paths within workspace are allowed."""
        workspace = Path("/tmp/workspace")
        guardrails = SafetyGuardrails(workspace)

        # Relative path should be resolved against workspace
        result = guardrails.validate_path("test.txt")
        assert result is None

    def test_relative_subdir_in_workspace(self):
        """Test that relative subdir paths are allowed."""
        workspace = Path("/tmp/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_path("subdir/file.txt")
        assert result is None

    def test_path_traversal_blocked(self):
        """Test that path traversal outside workspace is blocked."""
        workspace = Path("/tmp/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_path("../etc/passwd")
        assert result is not None
        assert "outside workspace" in result

    def test_windows_path_traversal_blocked(self):
        """Test Windows-style path traversal is blocked."""
        workspace = Path("C:/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_path("..\\Windows\\System32")
        assert result is not None
        assert "outside workspace" in result

    def test_absolute_drive_path_blocked(self):
        """Test absolute paths on other drives are blocked."""
        workspace = Path("C:/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_path("D:/secret.txt")
        assert result is not None
        assert "outside workspace" in result

    def test_windows_relative_path_allowed(self):
        """Test Windows-style relative paths within workspace are allowed."""
        workspace = Path("C:/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_path("subfolder\\file.txt")
        assert result is None

    def test_drive_relative_path_blocked(self):
        """Test drive-relative paths like C:secret.txt are blocked."""
        workspace = Path("C:/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_path("C:secret.txt")
        assert result is not None
        assert "blocked" in result

    def test_benign_words_not_blocked(self):
        """Test that benign words containing dangerous substrings are allowed."""
        policy = ToolPolicy()
        assert policy.is_command_dangerous("information") is False
        assert policy.is_command_dangerous("rebooting") is False
        assert policy.is_command_dangerous("formatted text") is False
        assert policy.is_command_dangerous("echo hello") is False
        assert policy.is_command_dangerous("cat file.txt") is False
        assert policy.is_command_dangerous("echo standard /s flag") is False
        assert policy.is_command_dangerous("echo keyword rmdir /safe") is False

    def test_working_dir_outside_workspace_blocked(self):
        """Test that shell working_dir outside workspace is blocked."""
        workspace = Path("/tmp/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_working_dir("/etc")
        assert result is not None
        assert "outside workspace" in result

    def test_working_dir_inside_workspace_allowed(self):
        """Test that shell working_dir inside workspace is allowed."""
        workspace = Path("/tmp/workspace")
        guardrails = SafetyGuardrails(workspace)

        result = guardrails.validate_working_dir("subfolder")
        assert result is None

    def test_dangerous_commands_all_patterns(self):
        """Test every dangerous command pattern is detected."""
        policy = ToolPolicy()
        dangerous_commands = [
            "rm -rf /",
            "rm -fr /",
            "del /f file.txt",
            "del /s /q C:\\",
            "del /q /s folder",
            "format C:",
            "mkfs.ext4 /dev/sda1",
            "dd if=/dev/zero of=/dev/sda",
            ":(){ :|:& };:",
            "shutdown -h now",
            "reboot",
            "rd /s folder",
            "rmdir /s folder",
            "rd /s /q folder",
            "powershell -command Get-Process",
            "invoke-expression",
            'iex("do-something")',
        ]
        for cmd in dangerous_commands:
            assert policy.is_command_dangerous(cmd) is True, f"Failed to detect: {cmd}"

    def test_dangerous_commands_whitespace_variations(self):
        """Test that extra whitespace does not bypass detection."""
        policy = ToolPolicy()
        assert policy.is_command_dangerous("rm   -rf   /") is True
        assert policy.is_command_dangerous("del  /s  /q  file") is True
        assert policy.is_command_dangerous("powershell   -command  x") is True

    def test_iex_with_space_blocked(self):
        """Test that iex with space before parenthesis is blocked."""
        policy = ToolPolicy()
        assert policy.is_command_dangerous('iex ("do-something")') is True
        assert policy.is_command_dangerous("iex  (123)") is True

    def test_safe_commands_allowed(self):
        """Test that safe commands are not blocked."""
        policy = ToolPolicy()
        assert policy.is_command_dangerous("ls -la") is False
        assert policy.is_command_dangerous("cat file.txt") is False
        assert policy.is_command_dangerous("python script.py") is False
        assert policy.is_command_dangerous("echo hello") is False
        assert policy.is_command_dangerous("dir") is False

    def test_shell_chaining_blocked(self):
        """Test P0-1: shell chaining operators are blocked."""
        policy = ToolPolicy()
        assert policy.is_command_dangerous("echo safe && rm -rf /") is True
        assert policy.is_command_dangerous("echo safe || rm -rf /") is True
        assert policy.is_command_dangerous("echo safe ; rm -rf /") is True
        assert policy.is_command_dangerous("echo safe | rm -rf /") is True

    def test_powershell_encoded_blocked(self):
        """Test P0-1: powershell -enc is blocked."""
        policy = ToolPolicy()
        assert policy.is_command_dangerous("powershell -enc cm0gLXJmIC8=") is True
        assert policy.is_command_dangerous("powershell -encodedcommand cm0gLXJmIC8=") is True

    def test_cmd_c_blocked(self):
        """Test P0-1: cmd /c is blocked."""
        policy = ToolPolicy()
        assert policy.is_command_dangerous("cmd /c del /q C:\\*") is True
        assert policy.is_command_dangerous("cmd /k whoami") is True

    def test_ssrf_localhost_blocked(self):
        """Test P0-2: localhost URLs are blocked."""
        workspace = Path("/tmp/workspace")
        guardrails = SafetyGuardrails(workspace)
        assert guardrails.validate_web_url("http://127.0.0.1:22/") is not None
        assert guardrails.validate_web_url("http://localhost/admin") is not None
        assert guardrails.validate_web_url("http://169.254.169.254/latest/meta-data/") is not None
        assert guardrails.validate_web_url("https://api.openai.com/") is None

    def test_cd_chaining_blocked(self):
        """Test P0-5: cd .. && rm -rf / style working dir bypass is blocked."""
        policy = ToolPolicy()
        assert policy.is_command_dangerous("cd .. && rm -rf /") is True
        assert policy.is_command_dangerous("cd /tmp && rm -rf /") is True
        assert policy.is_command_dangerous("pushd .. || rm -rf /") is True

    def test_quoted_flag_bypass_blocked(self):
        """Test P0-1: quoted interpreter flags like python3 '-c' are blocked."""
        policy = ToolPolicy()
        assert policy.is_command_dangerous('python3 "-c" pass') is True
        assert policy.is_command_dangerous('python \'-c\' pass') is True
        assert policy.is_command_dangerous('node "-e" console.log(1)') is True
        assert policy.is_command_dangerous('powershell "-command" Get-Process') is True

    def test_intermediate_flag_bypass_blocked(self):
        """Test P0-1: interpreter flags with intermediate options are blocked."""
        policy = ToolPolicy()
        assert policy.is_command_dangerous("python3 -I -c pass") is True
        assert policy.is_command_dangerous("python -W all -c pass") is True
        assert policy.is_command_dangerous("node --no-warnings -e console.log(1)") is True
        assert policy.is_command_dangerous("powershell -NoProfile -command Get-Process") is True
        assert policy.is_command_dangerous("pwsh -c echo hi") is True


class TestTokenAccountingIntegration:
    """Test token accounting at adapter level."""

    def test_all_modules_recorded(self):
        """Test that all token modules are recorded."""
        from core.runtime.token_meter import TokenMeter

        meter = TokenMeter()
        meter.increment_turn("session_1")
        meter.record_usage("session_1", "system", prompt_tokens=100)
        meter.record_usage("session_1", "history", prompt_tokens=200)
        meter.record_usage("session_1", "user_input", prompt_tokens=50)
        meter.record_usage("session_1", "output", completion_tokens=150)
        meter.record_usage("session_1", "tool_result", prompt_tokens=50)

        stats = meter.get_last_call_stats("session_1")
        assert stats is not None
        assert "system" in stats["modules"]
        assert "history" in stats["modules"]
        assert "user_input" in stats["modules"]
        assert "output" in stats["modules"]
        assert "tool_result" in stats["modules"]
        assert stats["total_tokens"] == 550

    def test_no_tool_usage_no_tool_result(self):
        """Test that tool_result is absent when no tools used."""
        from core.runtime.token_meter import TokenMeter

        meter = TokenMeter()
        meter.increment_turn("session_2")
        meter.record_usage("session_2", "user_input", prompt_tokens=50)
        meter.record_usage("session_2", "output", completion_tokens=100)

        stats = meter.get_last_call_stats("session_2")
        assert "tool_result" not in stats["modules"]
        assert stats["total_tokens"] == 150


class TestAbilityPersistenceIntegration:
    """Test ability persistence end-to-end."""

    def test_persisted_ability_not_re_unlocked(self, tmp_path, monkeypatch):
        """Test that persisted abilities are not re-unlocked after restart."""
        from app.config import Settings
        from core.storage.db import Database

        settings = Settings(
            llm_api_key="test",
            data_dir=tmp_path,
        )
        db = Database(settings)
        db.init_database()

        monkeypatch.setattr("core.storage.db._db", db)

        # First manager - unlock an ability
        manager1 = AbilityManager()
        manager1._ability_repo.save_unlocked_ability("advanced_chat")

        # Restart - create new manager
        manager2 = AbilityManager()

        # Verify ability is loaded but not re-emitted
        assert manager2.is_unlocked("advanced_chat") is True

        # check_and_unlock should not return already unlocked abilities
        from core.models.pet import PetState

        pet = PetState()
        new_unlocks = manager2.check_and_unlock(
            pet=pet,
            personality=None,
            tasks_completed=10,
        )
        assert "advanced_chat" not in [a.id for a in new_unlocks]

    def test_ability_can_unlock_again_after_db_clear(self, tmp_path, monkeypatch):
        """Test that ability can re-unlock after DB is cleared."""
        from app.config import Settings
        from core.storage.db import Database

        settings = Settings(
            llm_api_key="test",
            data_dir=tmp_path,
        )
        db = Database(settings)
        db.init_database()

        monkeypatch.setattr("core.storage.db._db", db)

        # First manager - unlock an ability
        manager1 = AbilityManager()
        manager1._ability_repo.save_unlocked_ability("advanced_chat")
        # Manually add to in-memory state since we bypassed check_and_unlock
        from core.abilities.ability_system import AbilityRegistry

        ability = AbilityRegistry.get_ability("advanced_chat")
        if ability:
            from dataclasses import replace

            manager1.unlocked_abilities["advanced_chat"] = replace(ability, unlocked_at="now")
        assert manager1.is_unlocked("advanced_chat") is True

        # Clear DB
        manager1._ability_repo.clear_all()

        # New manager - ability should be unlockable again
        manager2 = AbilityManager()
        assert manager2.is_unlocked("advanced_chat") is False
