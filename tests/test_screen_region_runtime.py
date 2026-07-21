"""Lifecycle and safety tests for temporary screen-region questions."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

from core.config import Settings
from core.screen_region import (
    ScreenRegionBounds,
    ScreenRegionCaptureStatus,
    ScreenRegionDraft,
    ScreenRegionRuntime,
)


def _settings(**overrides) -> Settings:
    values = {
        "llm_api_key": "test",
        "llm_multimodal_model": "vision-test",
        "screen_region_enabled": True,
        "screen_region_ttl_seconds": 60,
    }
    values.update(overrides)
    return Settings(**values)


def _write_png(path: Path, size: tuple[int, int] = (320, 180)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (224, 196, 168)).save(path, "PNG")
    return path


def _draft(path: Path) -> ScreenRegionDraft:
    return ScreenRegionDraft(
        path=path,
        bounds=ScreenRegionBounds(x=40, y=80, width=320, height=180),
        screen_name="Test display",
    )


def _runtime(tmp_path: Path, **settings_overrides) -> ScreenRegionRuntime:
    return ScreenRegionRuntime(
        _settings(**settings_overrides),
        root=tmp_path / "managed",
        draft_roots=[tmp_path],
        file_hardener=lambda _path: None,
    )


class TestScreenRegionAdoption:
    """A crop becomes managed only after path, magic-byte, and pixel validation."""

    def test_adoption_transfers_ownership_and_deletes_draft(self, tmp_path):
        source = _write_png(tmp_path / "lobuddy-region-draft-test.png")
        runtime = _runtime(tmp_path)
        now = datetime(2026, 7, 19, 8, tzinfo=timezone.utc)

        capture = runtime.adopt_temporary_capture(_draft(source), now=now)

        assert not source.exists()
        assert capture.path.exists()
        assert capture.path.parent == (tmp_path / "managed").resolve()
        assert capture.pixel_width == 320
        assert capture.pixel_height == 180
        assert capture.display_size == "320 × 180"
        assert capture.status == ScreenRegionCaptureStatus.READY
        assert capture.expires_at == now + timedelta(seconds=60)
        assert runtime.owns_path(capture.path)

    def test_new_unsubmitted_crop_replaces_and_deletes_previous_crop(self, tmp_path):
        runtime = _runtime(tmp_path)
        first = runtime.adopt_temporary_capture(_draft(_write_png(tmp_path / "first.png")))
        second = runtime.adopt_temporary_capture(
            _draft(_write_png(tmp_path / "second.png", (420, 240)))
        )

        assert not first.path.exists()
        assert not runtime.owns_path(first.path)
        assert second.path.exists()
        assert runtime.owns_path(second.path)

    @pytest.mark.parametrize("size", [(12, 180), (320, 12)])
    def test_too_small_crop_is_rejected_and_source_is_deleted(self, tmp_path, size):
        source = _write_png(tmp_path / f"small-{size[0]}-{size[1]}.png", size)
        runtime = _runtime(tmp_path)

        with pytest.raises(ValueError, match="too small"):
            runtime.adopt_temporary_capture(_draft(source))

        assert not source.exists()
        assert list((tmp_path / "managed").glob("region-*")) == []

    def test_decoded_pixel_limit_rejects_oversized_crop(self, tmp_path):
        source = _write_png(tmp_path / "large.png", (1100, 1000))
        runtime = _runtime(tmp_path, screen_region_max_pixels=1_000_000)

        with pytest.raises(ValueError, match="too large"):
            runtime.adopt_temporary_capture(_draft(source))

        assert not source.exists()

    def test_unsafe_source_is_rejected_without_deleting_user_file(self, tmp_path):
        allowed = tmp_path / "allowed"
        source = _write_png(tmp_path / "outside" / "private.png")
        runtime = ScreenRegionRuntime(
            _settings(),
            root=tmp_path / "managed",
            draft_roots=[allowed],
            file_hardener=lambda _path: None,
        )

        with pytest.raises(ValueError, match="outside the temporary area"):
            runtime.adopt_temporary_capture(_draft(source))

        assert source.exists()

    def test_permission_hardening_failure_cleans_source_and_managed_copy(self, tmp_path):
        source = _write_png(tmp_path / "permission-failure.png")

        def fail_hardening(_path: Path) -> None:
            raise RuntimeError("permission hardening failed")

        runtime = ScreenRegionRuntime(
            _settings(),
            root=tmp_path / "managed",
            draft_roots=[tmp_path],
            file_hardener=fail_hardening,
        )

        with pytest.raises(RuntimeError, match="permission hardening"):
            runtime.adopt_temporary_capture(_draft(source))

        assert not source.exists()
        assert list((tmp_path / "managed").glob("region-*")) == []


class TestScreenRegionLifecycle:
    """Expiry, task handoff, failure, and settings changes all delete owned pixels."""

    def test_restart_deletes_even_recent_orphaned_managed_crop(self, tmp_path):
        managed_root = tmp_path / "managed"
        orphan = _write_png(managed_root / "region-crashed.png")

        _runtime(tmp_path)

        assert not orphan.exists()

    def test_ready_crop_is_deleted_when_expired(self, tmp_path):
        runtime = _runtime(tmp_path)
        now = datetime(2026, 7, 19, 8, tzinfo=timezone.utc)
        capture = runtime.adopt_temporary_capture(
            _draft(_write_png(tmp_path / "expires.png")),
            now=now,
        )

        assert runtime.prune(now=now + timedelta(seconds=61)) == 1
        assert not capture.path.exists()
        assert not runtime.owns_path(capture.path)

    def test_successful_handoff_keeps_crop_until_bound_task_finishes(self, tmp_path):
        runtime = _runtime(tmp_path)
        now = datetime(2026, 7, 19, 8, tzinfo=timezone.utc)
        capture = runtime.adopt_temporary_capture(
            _draft(_write_png(tmp_path / "handoff.png")),
            now=now,
        )
        received_paths: list[str] = []

        async def submitter(path: str) -> str:
            received_paths.append(path)
            return "task-42"

        task_id = asyncio.run(
            runtime.handoff_to_task(
                capture.path,
                submitter,
                now=now + timedelta(seconds=1),
            )
        )

        assert task_id == "task-42"
        assert received_paths == [str(capture.path)]
        assert runtime.prune(now=now + timedelta(minutes=10)) == 0
        assert capture.path.exists()
        assert runtime.release_task(task_id) is True
        assert not capture.path.exists()
        assert runtime.release_task(task_id) is False

    def test_submission_failure_deletes_claimed_crop(self, tmp_path):
        runtime = _runtime(tmp_path)
        capture = runtime.adopt_temporary_capture(
            _draft(_write_png(tmp_path / "failed-submit.png"))
        )

        async def fail_submitter(_path: str) -> str:
            raise RuntimeError("queue unavailable")

        with pytest.raises(RuntimeError, match="queue unavailable"):
            asyncio.run(runtime.handoff_to_task(capture.path, fail_submitter))

        assert not capture.path.exists()
        assert not runtime.owns_path(capture.path)

    def test_empty_task_id_is_treated_as_failed_handoff(self, tmp_path):
        runtime = _runtime(tmp_path)
        capture = runtime.adopt_temporary_capture(_draft(_write_png(tmp_path / "empty-task.png")))

        async def empty_submitter(_path: str) -> str:
            return ""

        with pytest.raises(RuntimeError, match="did not return an ID"):
            asyncio.run(runtime.handoff_to_task(capture.path, empty_submitter))

        assert not capture.path.exists()

    def test_disabling_feature_deletes_unsubmitted_but_not_claimed_crop(self, tmp_path):
        runtime = _runtime(tmp_path)
        ready = runtime.adopt_temporary_capture(_draft(_write_png(tmp_path / "ready.png")))
        runtime.update_settings(_settings(screen_region_enabled=False))
        assert not ready.path.exists()

        runtime.update_settings(_settings(screen_region_enabled=True))
        claimed = runtime.adopt_temporary_capture(_draft(_write_png(tmp_path / "claimed.png")))

        async def submitter(_path: str) -> str:
            return "active-task"

        asyncio.run(runtime.handoff_to_task(claimed.path, submitter))
        runtime.update_settings(_settings(screen_region_enabled=False))

        assert claimed.path.exists()
        assert runtime.release_task("active-task")
        assert not claimed.path.exists()

    def test_clear_all_removes_every_managed_capture(self, tmp_path):
        runtime = _runtime(tmp_path)
        capture = runtime.adopt_temporary_capture(_draft(_write_png(tmp_path / "shutdown.png")))

        assert runtime.clear_all() == 1
        assert not capture.path.exists()
        assert runtime.clear_all() == 0

    def test_failed_delete_keeps_capture_registered_for_retry(self, tmp_path, monkeypatch):
        runtime = _runtime(tmp_path)
        capture = runtime.adopt_temporary_capture(
            _draft(_write_png(tmp_path / "retry-delete.png"))
        )
        original_unlink = Path.unlink

        def fail_managed_unlink(path: Path, *, missing_ok: bool = False) -> None:
            if path == capture.path:
                raise PermissionError("file is busy")
            original_unlink(path, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", fail_managed_unlink)

        assert runtime.release_capture(capture.id) is False
        assert runtime.owns_path(capture.path)
        assert capture.path.exists()

        monkeypatch.setattr(Path, "unlink", original_unlink)
        assert runtime.release_capture(capture.id) is True
        assert not capture.path.exists()
