"""Deep Module for validation, expiry, handoff, and deletion of screen crops."""

from __future__ import annotations

import getpass
import io
import os
import stat
import subprocess
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

from core.agent.image_validation import inspect_image_file, validate_image_file
from core.config import Settings
from core.screen_region.models import (
    ScreenRegionCapture,
    ScreenRegionCaptureStatus,
    ScreenRegionDraft,
    utc_now,
)

TaskSubmitter = Callable[[str], Awaitable[str]]
FileHardener = Callable[[Path], None]


class ScreenRegionRuntime:
    """Own the complete lifetime of user-selected screen pixels."""

    _MANAGED_PREFIX = "region-"

    def __init__(
        self,
        settings: Settings,
        *,
        root: Path | None = None,
        draft_roots: list[Path] | None = None,
        file_hardener: FileHardener | None = None,
    ) -> None:
        self._settings = settings
        self._root = (root or Path(tempfile.gettempdir()) / "lobuddy-screen-regions").resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._draft_roots = [
            item.resolve() for item in (draft_roots or [Path(tempfile.gettempdir())])
        ]
        self._file_hardener = file_hardener or _restrict_file_to_current_user
        self._captures: dict[str, ScreenRegionCapture] = {}
        self._task_captures: dict[str, str] = {}
        self._cleanup_orphans()

    @property
    def available(self) -> bool:
        return bool(
            self._settings.screen_region_enabled and self._settings.llm_multimodal_model.strip()
        )

    @property
    def managed_capture_count(self) -> int:
        """Expose only a count; pixel paths and contents stay inside the Module."""
        self.prune()
        return len(self._captures)

    def update_settings(self, settings: Settings) -> None:
        self._settings = settings
        if not self.available:
            self._discard_unclaimed()
        self.prune()

    def adopt_temporary_capture(
        self,
        draft: ScreenRegionDraft,
        *,
        now: datetime | None = None,
    ) -> ScreenRegionCapture:
        """Validate a UI draft and transfer it into managed temporary storage."""
        now = now or utc_now()
        self.prune(now=now)
        draft_path = Path(draft.path)
        source = draft_path.resolve()
        self._require_safe_draft(draft_path, source)
        target: Path | None = None
        try:
            if not self.available:
                raise RuntimeError("Screen Region Ask requires an enabled visual model")
            inspection = inspect_image_file(source)
            data = validate_image_file(inspection.path)
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                width, height = image.size
            self._validate_dimensions(width, height)

            suffix = ".png" if data.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg"
            target = self._root / f"{self._MANAGED_PREFIX}{uuid.uuid4().hex}{suffix}"
            target.write_bytes(data)
            self._file_hardener(target)
            managed = inspect_image_file(target)
            self._discard_unclaimed()
            capture = ScreenRegionCapture(
                id=str(uuid.uuid4()),
                path=target,
                bounds=draft.bounds,
                screen_name=draft.screen_name,
                pixel_width=width,
                pixel_height=height,
                size_bytes=managed.size_bytes,
                captured_at=now,
                expires_at=now + timedelta(seconds=self._settings.screen_region_ttl_seconds),
            )
            self._captures[capture.id] = capture
            return capture
        except Exception:
            if target is not None:
                target.unlink(missing_ok=True)
            raise
        finally:
            source.unlink(missing_ok=True)

    async def handoff_to_task(
        self,
        image_path: str | Path,
        submitter: TaskSubmitter,
        *,
        now: datetime | None = None,
    ) -> str:
        """Claim a crop, queue one task, and bind deletion to that task."""
        now = now or utc_now()
        capture = self._claim_path(image_path, now)
        try:
            task_id = await submitter(str(capture.path))
            if not task_id:
                raise RuntimeError("Task submission did not return an ID")
        except Exception:
            self.release_capture(capture.id)
            raise
        self._task_captures[task_id] = capture.id
        return task_id

    def owns_path(self, image_path: str | Path) -> bool:
        try:
            candidate = Path(image_path).resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        return any(capture.path.resolve() == candidate for capture in self._captures.values())

    def discard_path(self, image_path: str | Path) -> bool:
        try:
            candidate = Path(image_path).resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        for capture in list(self._captures.values()):
            if capture.path.resolve() == candidate:
                return self.release_capture(capture.id)
        return False

    def release_task(self, task_id: str) -> bool:
        capture_id = self._task_captures.get(task_id, "")
        return self.release_capture(capture_id) if capture_id else False

    def release_capture(self, capture_id: str) -> bool:
        capture = self._captures.get(capture_id)
        if capture is None:
            return False
        try:
            capture.path.unlink(missing_ok=True)
        except OSError:
            self._captures[capture_id] = capture.model_copy(
                update={
                    "status": ScreenRegionCaptureStatus.READY,
                    "expires_at": utc_now(),
                }
            )
            return False
        self._captures.pop(capture_id, None)
        stale_tasks = [
            task_id for task_id, bound_id in self._task_captures.items() if bound_id == capture_id
        ]
        for task_id in stale_tasks:
            self._task_captures.pop(task_id, None)
        return True

    def prune(self, *, now: datetime | None = None) -> int:
        now = now or utc_now()
        expired = [
            capture.id
            for capture in self._captures.values()
            if capture.status == ScreenRegionCaptureStatus.READY and capture.is_expired(now)
        ]
        return sum(1 for capture_id in expired if self.release_capture(capture_id))

    def clear_all(self) -> int:
        capture_ids = list(self._captures)
        removed = sum(1 for capture_id in capture_ids if self.release_capture(capture_id))
        return removed

    def _claim_path(
        self,
        image_path: str | Path,
        now: datetime,
    ) -> ScreenRegionCapture:
        self.prune(now=now)
        candidate = Path(image_path).resolve()
        for capture_id, capture in self._captures.items():
            if capture.path.resolve() != candidate:
                continue
            if capture.status != ScreenRegionCaptureStatus.READY:
                raise ValueError("Screen region is already attached to another task")
            claimed = capture.model_copy(update={"status": ScreenRegionCaptureStatus.CLAIMED})
            self._captures[capture_id] = claimed
            return claimed
        raise ValueError("Screen region expired or is no longer available")

    def _validate_dimensions(self, width: int, height: int) -> None:
        if (
            width < self._settings.screen_region_min_size_px
            or height < self._settings.screen_region_min_size_px
        ):
            raise ValueError("Screen region is too small; select a larger visible area")
        if width * height > self._settings.screen_region_max_pixels:
            raise ValueError("Screen region is too large; select a more focused area")

    def _require_safe_draft(self, draft_path: Path, source: Path) -> None:
        if not source.is_file():
            raise ValueError("Screen-region draft was not found")
        if draft_path.is_symlink():
            raise ValueError("Screen-region draft cannot be a symbolic link")
        if not any(_is_relative_to(source, root) for root in self._draft_roots):
            raise ValueError("Screen-region draft is outside the temporary area")

    def _discard_unclaimed(self) -> None:
        for capture in list(self._captures.values()):
            if capture.status == ScreenRegionCaptureStatus.READY:
                self.release_capture(capture.id)

    def _cleanup_orphans(self) -> None:
        # No capture can survive a process restart: TaskManager deliberately
        # interrupts in-flight work instead of replaying side effects.
        for path in self._root.glob(f"{self._MANAGED_PREFIX}*"):
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink(missing_ok=True)
            except OSError:
                continue


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _restrict_file_to_current_user(path: Path) -> None:
    """Fail closed if a sensitive crop cannot be permission-restricted."""
    if os.name == "nt":
        try:
            identity = os.getlogin()
        except OSError:
            identity = getpass.getuser()
        result = subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{identity}:F",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            path.unlink(missing_ok=True)
            raise RuntimeError("Failed to restrict screen-region file permissions")
        return
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
