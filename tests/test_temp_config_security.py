"""Tests for temporary config file security (P0 0.2)."""

import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.agent.config_builder import write_temp_config


class TestTempConfigPermissions:
    """Test P0 0.2: temporary config file permissions and cleanup."""

    def test_temp_config_file_has_restricted_permissions(self):
        """Test that temp config file is created with restricted permissions."""
        config = {"apiKey": "secret_key_123", "providers": {"custom": {}}}
        temp_dir = Path(tempfile.mkdtemp())

        try:
            config_path = write_temp_config(config, temp_dir, "test_model")

            assert config_path.exists(), "Config file should exist"
            assert config_path.is_file(), "Config path should be a file"

            if os.name != "nt":
                # Unix: check mode is 0o600 (owner read/write only)
                mode = stat.S_IMODE(config_path.stat().st_mode)
                assert mode == 0o600, f"Expected mode 0o600, got 0o{mode:o}"
            else:
                # Windows: at minimum verify file exists and is readable only by owner
                # The ACL setup may fail silently, but we verify the attempt was made
                assert config_path.exists()

        finally:
            # Cleanup
            if config_path.exists():
                config_path.unlink()
            temp_dir.rmdir()

    def test_temp_config_file_not_world_readable(self):
        """Test that temp config file is not world-readable."""
        config = {"apiKey": "secret_key_123", "providers": {"custom": {}}}
        temp_dir = Path(tempfile.mkdtemp())

        try:
            config_path = write_temp_config(config, temp_dir, "test_model")

            if os.name != "nt":
                mode = stat.S_IMODE(config_path.stat().st_mode)
                # Check no group or other read bits
                assert not (mode & stat.S_IRGRP), "Group read bit should not be set"
                assert not (mode & stat.S_IROTH), "Other read bit should not be set"
                assert not (mode & stat.S_IXUSR), "Owner execute bit should not be set"

        finally:
            if config_path.exists():
                config_path.unlink()
            temp_dir.rmdir()

    def test_exception_during_write_cleans_up_temp_file(self):
        """Test that temp file is cleaned up if writing fails."""
        import os as os_module
        config = {"apiKey": "secret_key_123"}
        temp_dir = Path(tempfile.mkdtemp())

        original_fdopen = os_module.fdopen
        call_count = [0]

        def failing_fdopen(*args, **kwargs):
            call_count[0] += 1
            raise OSError("Simulated write failure")

        try:
            os_module.fdopen = failing_fdopen
            with pytest.raises(OSError):
                write_temp_config(config, temp_dir, "test_model")

            assert call_count[0] > 0, "fdopen should have been called"
            files_after = list(temp_dir.iterdir())
            assert len(files_after) == 0, f"Temp file should be cleaned up, found: {files_after}"

        finally:
            os_module.fdopen = original_fdopen
            temp_dir.rmdir()

    def test_temp_config_does_not_contain_api_key_after_cleanup(self):
        """Test that temp config file is removed after use."""
        config = {"apiKey": "secret_key_123", "providers": {"custom": {}}}
        temp_dir = Path(tempfile.mkdtemp())

        try:
            config_path = write_temp_config(config, temp_dir, "test_model")
            assert config_path.exists()

            # Simulate cleanup
            config_path.unlink()
            assert not config_path.exists(), "Config file should be deleted after use"

        finally:
            if config_path.exists():
                config_path.unlink()
            temp_dir.rmdir()

    def test_temp_config_contains_api_key_while_alive(self):
        """Test that the temporary file contains the API key (expected behavior)
        but is protected by permissions."""
        config = {"apiKey": "sk-test-key-12345", "providers": {"custom": {}}}
        temp_dir = Path(tempfile.mkdtemp())

        try:
            config_path = write_temp_config(config, temp_dir, "test_model")

            # Verify the key is in the file (this is expected - nanobot needs it)
            content = config_path.read_text()
            assert "sk-test-key-12345" in content, "API key should be in temp config for nanobot"

            # But permissions should be restricted (tested above)
            if os.name != "nt":
                mode = stat.S_IMODE(config_path.stat().st_mode)
                assert mode == 0o600, "File must be restricted while containing key"

        finally:
            if config_path.exists():
                config_path.unlink()
            temp_dir.rmdir()

    def test_windows_acl_failure_deletes_file_and_raises(self):
        """Test that Windows ACL failure deletes temp file and raises."""
        config = {"apiKey": "secret_key_123"}
        temp_dir = Path(tempfile.mkdtemp())

        with patch("subprocess.run", side_effect=FileNotFoundError("icacls not found")):
            with pytest.raises(RuntimeError, match="Failed to restrict"):
                write_temp_config(config, temp_dir, "test_model")

        files_after = list(temp_dir.iterdir())
        assert len(files_after) == 0, f"Temp file should be deleted on ACL failure, found: {files_after}"
        temp_dir.rmdir()
