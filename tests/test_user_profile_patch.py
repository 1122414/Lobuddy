"""Tests for profile patch operations."""

import pytest
from pathlib import Path

from core.memory.user_profile_manager import UserProfileManager, build_default_profile
from core.memory.user_profile_schema import (
    PatchAction,
    ProfilePatch,
    ProfilePatchItem,
    ProfileSection,
)


class TestProfilePatch:
    """Test ProfilePatch validation."""

    def test_patch_item_max_length(self):
        with pytest.raises(Exception):
            ProfilePatchItem(
                section=ProfileSection.BASIC_NOTES,
                action=PatchAction.ADD,
                content="x" * 501,
            )

    def test_patch_items_max_count(self):
        items = [
            ProfilePatchItem(
                section=ProfileSection.BASIC_NOTES,
                action=PatchAction.ADD,
                content=f"item {i}",
            )
            for i in range(9)
        ]
        with pytest.raises(Exception):
            ProfilePatch(items=items)


class TestApplyPatch:
    """Test UserProfileManager.apply_patch."""

    def test_add_item(self, tmp_path: Path):
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)
        manager.ensure_profile_file()

        patch = ProfilePatch(items=[
            ProfilePatchItem(
                section=ProfileSection.PREFERENCES,
                action=PatchAction.ADD,
                content="Likes Python",
                confidence=0.9,
            )
        ])

        profile, rejected = manager.apply_patch(patch)
        assert "Likes Python" in profile.sections[ProfileSection.PREFERENCES]
        assert len(rejected) == 0

    def test_update_item(self, tmp_path: Path):
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)

        profile = build_default_profile()
        profile.sections[ProfileSection.PREFERENCES] = ["Old preference"]
        manager.save_profile(profile)

        patch = ProfilePatch(items=[
            ProfilePatchItem(
                section=ProfileSection.PREFERENCES,
                action=PatchAction.UPDATE,
                content="New preference",
                confidence=0.9,
            )
        ])

        result, _ = manager.apply_patch(patch)
        assert result.sections[ProfileSection.PREFERENCES] == ["New preference"]

    def test_remove_item(self, tmp_path: Path):
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)

        profile = build_default_profile()
        profile.sections[ProfileSection.PREFERENCES] = ["Keep", "Remove this"]
        manager.save_profile(profile)

        patch = ProfilePatch(items=[
            ProfilePatchItem(
                section=ProfileSection.PREFERENCES,
                action=PatchAction.REMOVE,
                content="Remove this",
                confidence=0.9,
            )
        ])

        result, _ = manager.apply_patch(patch)
        assert result.sections[ProfileSection.PREFERENCES] == ["Keep"]

    def test_reject_low_confidence(self, tmp_path: Path):
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)
        manager.ensure_profile_file()

        patch = ProfilePatch(items=[
            ProfilePatchItem(
                section=ProfileSection.BASIC_NOTES,
                action=PatchAction.ADD,
                content="Uncertain info",
                confidence=0.3,
            )
        ])

        _, rejected = manager.apply_patch(
            patch,
            require_high_confidence=True,
            min_confidence=0.75,
        )
        assert len(rejected) == 1

    def test_reject_uncertain_action(self, tmp_path: Path):
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)
        manager.ensure_profile_file()

        patch = ProfilePatch(items=[
            ProfilePatchItem(
                section=ProfileSection.BASIC_NOTES,
                action=PatchAction.UNCERTAIN,
                content="Maybe true",
                confidence=0.9,
            )
        ])

        _, rejected = manager.apply_patch(patch)
        assert len(rejected) == 1

    def test_redact_secrets(self, tmp_path: Path):
        profile_path = tmp_path / "USER.md"
        manager = UserProfileManager(profile_path)
        manager.ensure_profile_file()

        patch = ProfilePatch(items=[
            ProfilePatchItem(
                section=ProfileSection.BASIC_NOTES,
                action=PatchAction.ADD,
                content="API key is sk-abc123def456ghi789jkl012mno345pqr",
                confidence=0.9,
            )
        ])

        profile, _ = manager.apply_patch(patch)
        note = profile.sections[ProfileSection.BASIC_NOTES][0]
        assert "sk-abc123def456ghi789jkl012mno345pqr" not in note
        assert "[REDACTED]" in note
