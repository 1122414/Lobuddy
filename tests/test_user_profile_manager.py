"""Tests for UserProfileManager."""

import pytest
from pathlib import Path

from core.memory.user_profile_manager import UserProfileManager, build_default_profile
from core.memory.user_profile_schema import ProfileSection, UserProfile


class TestUserProfileManager:
    """Test UserProfileManager file operations."""

    def test_ensure_profile_file_creates_default(self, tmp_path: Path):
        """Test that ensure_profile_file creates USER.md with defaults."""
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)
        manager.ensure_profile_file()

        assert profile_path.exists()
        content = profile_path.read_text(encoding="utf-8")
        assert "## Basic Notes" in content
        assert "## Preferences" in content

    def test_ensure_profile_file_no_overwrite(self, tmp_path: Path):
        """Test that ensure_profile_file does not overwrite existing file."""
        profile_path = tmp_path / "USER.md"
        profile_path.write_text("custom content", encoding="utf-8")

        manager = UserProfileManager(profile_path)
        manager.ensure_profile_file()

        assert profile_path.read_text(encoding="utf-8") == "custom content"

    def test_load_profile_returns_default_when_missing(self, tmp_path: Path):
        """Test that load_profile returns default when file does not exist."""
        profile_path = tmp_path / "nonexistent.md"
        manager = UserProfileManager(profile_path)

        profile = manager.load_profile()
        assert isinstance(profile, UserProfile)
        assert len(profile.sections) == len(ProfileSection)

    def test_save_and_load_roundtrip(self, tmp_path: Path):
        """Test that save/load roundtrip preserves data."""
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)

        profile = build_default_profile()
        profile.sections[ProfileSection.BASIC_NOTES] = ["Test note 1", "Test note 2"]
        manager.save_profile(profile)

        loaded = manager.load_profile()
        assert loaded.sections[ProfileSection.BASIC_NOTES] == ["Test note 1", "Test note 2"]

    def test_compact_profile_for_prompt_respects_limit(self, tmp_path: Path):
        """Test that compact_profile_for_prompt respects max_chars."""
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)

        profile = build_default_profile()
        profile.sections[ProfileSection.BASIC_NOTES] = ["A" * 1000]
        manager.save_profile(profile)

        compact = manager.compact_profile_for_prompt(max_chars=500)
        assert len(compact) <= 500

    def test_get_profile_sections_returns_dict(self, tmp_path: Path):
        """Test that get_profile_sections returns dict."""
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)
        manager.ensure_profile_file()

        sections = manager.get_profile_sections()
        assert isinstance(sections, dict)
        assert ProfileSection.BASIC_NOTES in sections

    def test_atomic_write_cleanup_on_error(self, tmp_path: Path, monkeypatch):
        """Test that atomic write cleans up temp file on error."""
        import os

        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)

        original_replace = os.replace

        def failing_replace(src, dst):
            raise OSError("Simulated failure")

        monkeypatch.setattr(os, "replace", failing_replace)

        with pytest.raises(OSError):
            manager.save_profile(build_default_profile())

        tmp_files = list(tmp_path.glob(".user_md_*.tmp"))
        assert len(tmp_files) == 0
