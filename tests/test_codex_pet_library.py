"""Subprocess Qt integration test for the Codex pet library."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

from core.services.codex_pet_service import CodexPetService


def _create_pet(root: Path) -> None:
    directory = root / "ui-friend"
    directory.mkdir(parents=True)
    sheet = Image.new("RGBA", CodexPetService.SHEET_SIZES[1], (0, 0, 0, 0))
    for row, durations in (value for value in CodexPetService.ANIMATIONS.values()):
        for column in range(len(durations)):
            left = column * CodexPetService.FRAME_WIDTH + 62
            top = row * CodexPetService.FRAME_HEIGHT + 66
            sheet.paste((255, 128, 70, 255), (left, top, left + 70, top + 90))
    sheet.save(directory / "spritesheet.png")
    (directory / "pet.json").write_text(
        json.dumps(
            {
                "displayName": "UI Friend",
                "description": "Ready to help.",
                "spritesheetPath": "spritesheet.png",
            }
        ),
        encoding="utf-8",
    )


def test_library_and_asset_routing_work_in_real_qt_subprocess(tmp_path: Path) -> None:
    pets_root = tmp_path / ".codex" / "pets"
    data_dir = tmp_path / "data"
    _create_pet(pets_root)
    probe = tmp_path / "codex_pet_qt_probe.py"
    probe.write_text(
        """
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from core.models.appearance import PetAppearance
from core.models.pet import TaskStatus
from core.services.codex_pet_service import CodexPetService
from ui.asset_manager import AssetManager
from ui.codex_pet_library_dialog import CodexPetLibraryDialog

app = QApplication.instance() or QApplication([])
service = CodexPetService(Path(sys.argv[1]), Path(sys.argv[2]))
dialog = CodexPetLibraryDialog(service)
loop = QEventLoop()

def wait_for_local_pets():
    if dialog._discovery_thread is None:
        loop.quit()
    else:
        QTimer.singleShot(20, wait_for_local_pets)

QTimer.singleShot(0, wait_for_local_pets)
QTimer.singleShot(30_000, loop.quit)
loop.exec()
assert dialog.pet_list.count() == 1
assert dialog.name_label.text() == "UI Friend"
assert dialog.use_button.isEnabled()
original_pet = dialog._selected_local_pet()
assert original_pet is not None
builtin_pet = replace(
    original_pet,
    pet_id="codex-builtin:ui-friend",
    source_kind="codex_builtin",
)
dialog.pet_list.clear()
dialog._add_local_pet(builtin_pet)
dialog.pet_list.setCurrentRow(0)
assert "Codex 自带" in dialog.pet_list.currentItem().text()
assert dialog.use_button.text() == "立即使用这只 Codex 伙伴"
dialog.pet_list.clear()
dialog._add_local_pet(original_pet)
dialog.pet_list.setCurrentRow(0)
loop = QEventLoop()
dialog.accepted.connect(loop.quit)
QTimer.singleShot(30_000, loop.quit)
dialog._use_selected_pet()
loop.exec()
result = dialog.selected_result
assert result is not None
assert result.state_asset_paths["running"].exists()

AssetManager._instance = None
AssetManager._pixmap_cache = {}
manager = AssetManager()
manager.appearance = PetAppearance(
    custom_asset_path=str(result.asset_path),
    custom_asset_type="gif",
    custom_asset_source="codex",
    custom_state_asset_paths={key: str(path) for key, path in result.state_asset_paths.items()},
)
assert manager._resolve_pet_image_path(TaskStatus.IDLE).name == "idle.gif"
assert manager._resolve_pet_image_path(TaskStatus.QUEUED).name == "waiting.gif"
assert manager._resolve_pet_image_path(TaskStatus.RUNNING).name == "running.gif"
assert manager._resolve_pet_image_path(TaskStatus.SUCCESS).name == "success.gif"
assert manager._resolve_pet_image_path(TaskStatus.FAILED).name == "failed.gif"
assert manager._resolve_pet_image_path(TaskStatus.CANCELLED).name == "idle.gif"
assert manager._resolve_pet_image_path("waving").name == "waving.gif"
assert manager._resolve_pet_image_path("jumping").name == "jumping.gif"
assert manager._resolve_pet_image_path("review").name == "review.gif"
dialog.close()
app.processEvents()
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"

    completed = subprocess.run(
        [sys.executable, str(probe), str(data_dir), str(pets_root)],
        cwd=Path(__file__).parent.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_online_catalog_can_adopt_and_use_pet_in_real_qt_subprocess(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    pets_root = tmp_path / ".codex" / "pets"
    pets_root.mkdir(parents=True)
    sheet_path = tmp_path / "remote-sheet.webp"
    preview_path = tmp_path / "remote-preview.webp"
    Image.new(
        "RGBA",
        CodexPetService.SHEET_SIZES[1],
        (255, 136, 70, 255),
    ).save(sheet_path, format="WEBP", lossless=True)
    Image.new("RGBA", (320, 320), (255, 136, 70, 255)).save(
        preview_path,
        format="WEBP",
        lossless=True,
    )
    probe = tmp_path / "codex_pet_online_qt_probe.py"
    probe.write_text(
        """
import sys
from pathlib import Path

import httpx
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from core.services.codex_pet_service import CodexPetService
from ui.codex_pet_library_dialog import CodexPetLibraryDialog


class AllowRemote:
    def validate_web_url(self, _url):
        return None


sheet = Path(sys.argv[3]).read_bytes()
preview = Path(sys.argv[4]).read_bytes()


def handler(request):
    if request.url.path == "/api/pets":
        return httpx.Response(
            200,
            json={
                "pets": [{
                    "id": "online-friend",
                    "displayName": "Online Friend",
                    "description": "Adopted directly from the community.",
                    "spriteVersionNumber": 1,
                    "kind": "creature",
                    "ownerName": "Maker",
                    "tags": ["animated", "soft"],
                    "viewCount": 12,
                    "likeCount": 4,
                    "uploadedAt": "2026-07-19T00:00:00Z",
                    "spritesheetUrl": (
                        "https://codex-pets.net/assets/pets/v/1/"
                        "online-friend/spritesheet.webp"
                    ),
                    "previewUrl": (
                        "https://codex-pets.net/assets/pets/v/1/"
                        "online-friend/preview.webp"
                    ),
                    "downloadUrl": "/api/pets/online-friend/download?v=1",
                }],
                "page": 1,
                "pageSize": 30,
                "total": 1,
                "totalPages": 1,
            },
        )
    if request.url.path.endswith("/preview.webp"):
        return httpx.Response(200, content=preview)
    if request.url.path.endswith("/spritesheet.webp"):
        return httpx.Response(200, content=sheet)
    raise AssertionError(str(request.url))


def wait_until(predicate, timeout_ms=30_000):
    loop = QEventLoop()

    def check():
        if predicate():
            loop.quit()
        else:
            QTimer.singleShot(20, check)

    QTimer.singleShot(0, check)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    assert predicate()


app = QApplication.instance() or QApplication([])
service = CodexPetService(
    Path(sys.argv[1]),
    Path(sys.argv[2]),
    http_transport=httpx.MockTransport(handler),
    guardrails=AllowRemote(),
)
dialog = CodexPetLibraryDialog(service, initial_source="online")
assert dialog.source_tabs.currentIndex() == 1
wait_until(lambda: dialog._catalog_thread is None)
wait_until(lambda: dialog._discovery_thread is None)
assert dialog.online_pet_list.count() == 1
assert dialog.name_label.text() == "Online Friend"
assert dialog.use_button.text() == "领养并立即使用"
dialog._use_selected_pet()
wait_until(lambda: dialog._import_thread is None)
wait_until(lambda: dialog._preview_thread is None)
result = dialog.selected_result
assert result is not None
assert result.pet.pet_id == "codex-pets:online-friend"
assert result.pet.directory_path.parent == Path(sys.argv[2]).resolve()
assert result.state_asset_paths["failed"].exists()
dialog.close()
app.processEvents()
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"

    completed = subprocess.run(
        [
            sys.executable,
            str(probe),
            str(data_dir),
            str(pets_root),
            str(sheet_path),
            str(preview_path),
        ],
        cwd=Path(__file__).parent.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
