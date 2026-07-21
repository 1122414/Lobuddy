"""Tests for the Codex custom-pet compatibility layer."""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from core.models.appearance import PetAppearance
from core.services.codex_pet_service import (
    CodexPetCatalogItem,
    CodexPetError,
    CodexPetService,
    apply_codex_pet_appearance,
)


class _AllowRemoteGuardrails:
    def validate_web_url(self, _url: str) -> None:
        return None


def _create_pet_package(
    root: Path,
    *,
    slug: str = "pixel-friend",
    display_name: str = "Pixel Friend",
    version: int = 1,
    sheet_name: str = "spritesheet.png",
) -> Path:
    directory = root / slug
    directory.mkdir(parents=True)
    width, height = CodexPetService.SHEET_SIZES[version]
    sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for row, durations in (value for value in CodexPetService.ANIMATIONS.values()):
        for column in range(len(durations)):
            left = column * CodexPetService.FRAME_WIDTH + 48
            top = row * CodexPetService.FRAME_HEIGHT + 56
            color = ((40 + column * 24) % 255, (80 + row * 18) % 255, 210, 255)
            sheet.paste(color, (left, top, left + 96, top + 112))
    sheet.save(directory / sheet_name)
    (directory / "pet.json").write_text(
        json.dumps(
            {
                "displayName": display_name,
                "description": "A companion made for Codex.",
                "spriteVersionNumber": version,
                "spritesheetPath": sheet_name,
            }
        ),
        encoding="utf-8",
    )
    return directory


@pytest.mark.parametrize("version", [1, 2])
def test_discovers_official_codex_pet_versions(tmp_path: Path, version: int) -> None:
    pets_root = tmp_path / ".codex" / "pets"
    _create_pet_package(pets_root, version=version)
    service = CodexPetService(tmp_path / "data", pets_root)

    pets = service.discover_pets()

    assert len(pets) == 1
    assert pets[0].display_name == "Pixel Friend"
    assert pets[0].sprite_version_number == version
    assert pets[0].pet_id == "custom:pixel-friend"
    assert service.last_errors == ()


def test_discovery_isolates_invalid_packages(tmp_path: Path) -> None:
    pets_root = tmp_path / "pets"
    _create_pet_package(pets_root)
    broken = pets_root / "broken"
    broken.mkdir()
    (broken / "pet.json").write_text("{not-json", encoding="utf-8")
    service = CodexPetService(tmp_path / "data", pets_root)

    pets = service.discover_pets()

    assert [pet.slug for pet in pets] == ["pixel-friend"]
    assert len(service.last_errors) == 1
    assert service.last_errors[0].startswith("broken:")


def test_rejects_spritesheet_path_traversal(tmp_path: Path) -> None:
    pets_root = tmp_path / "pets"
    directory = pets_root / "escape"
    directory.mkdir(parents=True)
    (directory / "pet.json").write_text(
        json.dumps({"displayName": "Escape", "spritesheetPath": "../outside.png"}),
        encoding="utf-8",
    )
    Image.new("RGBA", CodexPetService.SHEET_SIZES[1]).save(pets_root / "outside.png")
    service = CodexPetService(tmp_path / "data", pets_root)

    with pytest.raises(CodexPetError, match="宠物包目录内"):
        service.load_package(directory)


def test_rejects_wrong_spritesheet_dimensions(tmp_path: Path) -> None:
    pets_root = tmp_path / "pets"
    directory = pets_root / "tiny"
    directory.mkdir(parents=True)
    Image.new("RGBA", (192, 208)).save(directory / "spritesheet.png")
    (directory / "pet.json").write_text(
        json.dumps({"displayName": "Tiny", "spritesheetPath": "spritesheet.png"}),
        encoding="utf-8",
    )
    service = CodexPetService(tmp_path / "data", pets_root)

    with pytest.raises(CodexPetError, match="1536×1872"):
        service.load_package(directory)


def test_activate_renders_state_animations_and_reuses_cache(tmp_path: Path) -> None:
    pets_root = tmp_path / "pets"
    _create_pet_package(pets_root)
    service = CodexPetService(tmp_path / "data", pets_root)
    pet = service.discover_pets()[0]

    result = service.activate_pet(pet)

    assert result.asset_path == result.state_asset_paths["idle"]
    assert set(result.state_asset_paths) == {
        "idle",
        "running_right",
        "running_left",
        "waving",
        "jumping",
        "failed",
        "waiting",
        "running",
        "review",
        "success",
    }
    assert all(path.is_file() for path in result.state_asset_paths.values())
    with Image.open(result.asset_path) as idle:
        assert idle.size == (208, 208)
        assert idle.n_frames == 6
        assert idle.info["loop"] == 0

    first_mtime = result.asset_path.stat().st_mtime_ns
    cached = service.activate_pet(pet)
    assert cached.asset_path == result.asset_path
    assert cached.asset_path.stat().st_mtime_ns == first_mtime


def test_task_success_uses_codex_jumping_row_not_waving_row(tmp_path: Path) -> None:
    pets_root = tmp_path / "pets"
    _create_pet_package(pets_root)
    service = CodexPetService(tmp_path / "data", pets_root)

    result = service.activate_pet(service.discover_pets()[0])

    with Image.open(result.state_asset_paths["waving"]) as waving:
        waving.seek(0)
        waving_color = waving.convert("RGBA").getpixel((70, 70))
    with Image.open(result.state_asset_paths["jumping"]) as jumping:
        jumping.seek(0)
        jumping_color = jumping.convert("RGBA").getpixel((70, 70))
    with Image.open(result.state_asset_paths["success"]) as success:
        success.seek(0)
        success_color = success.convert("RGBA").getpixel((70, 70))

    assert success_color == jumping_color
    assert success_color != waving_color


def test_apply_result_routes_every_state_without_resetting_display_preferences(
    tmp_path: Path,
) -> None:
    pets_root = tmp_path / "pets"
    _create_pet_package(pets_root, display_name="Direct Friend")
    service = CodexPetService(tmp_path / "data", pets_root)
    result = service.activate_pet(service.discover_pets()[0])
    appearance = PetAppearance(scale=1.4, opacity=0.72, always_on_top=False)

    apply_codex_pet_appearance(appearance, result)

    assert appearance.custom_asset_source == "codex"
    assert appearance.custom_asset_name == "Direct Friend"
    assert appearance.codex_pet_id == "custom:pixel-friend"
    assert set(appearance.custom_state_asset_paths) == {
        "idle",
        "running_right",
        "running_left",
        "waving",
        "jumping",
        "review",
        "running",
        "success",
        "failed",
        "waiting",
    }
    assert appearance.scale == 1.4
    assert appearance.opacity == 0.72
    assert appearance.always_on_top is False


def test_activation_revalidates_changed_package(tmp_path: Path) -> None:
    pets_root = tmp_path / "pets"
    directory = _create_pet_package(pets_root)
    service = CodexPetService(tmp_path / "data", pets_root)
    pet = service.discover_pets()[0]
    Image.new("RGBA", (64, 64)).save(directory / "spritesheet.png")

    with pytest.raises(CodexPetError, match="实际为 64×64"):
        service.activate_pet(pet)


def _catalog_item_payload(**overrides) -> dict:
    payload = {
        "id": "cloud-fox",
        "displayName": "Cloud Fox",
        "description": "A calm online companion.",
        "spriteVersionNumber": 1,
        "kind": "animal",
        "ownerName": "Maker",
        "uploadedAt": "2026-07-19T00:00:00Z",
        "viewCount": 24,
        "likeCount": 7,
        "tags": ["animated", "soft"],
        "spritesheetUrl": (
            "https://codex-pets.net/assets/pets/v/123/cloud-fox/spritesheet.webp"
        ),
        "previewUrl": "https://codex-pets.net/assets/pets/v/123/cloud-fox/preview.webp",
        "downloadUrl": "/api/pets/cloud-fox/download?v=123",
    }
    payload.update(overrides)
    return payload


def _spritesheet_bytes(version: int = 1) -> bytes:
    image = Image.new("RGBA", CodexPetService.SHEET_SIZES[version], (0, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", lossless=True)
    return buffer.getvalue()


def test_fetches_validated_remote_catalog_and_adopts_pet(tmp_path: Path) -> None:
    sheet = _spritesheet_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/pets":
            return httpx.Response(
                200,
                json={
                    "pets": [_catalog_item_payload()],
                    "page": 1,
                    "pageSize": 30,
                    "total": 1,
                    "totalPages": 1,
                },
            )
        if request.url.path.endswith("/spritesheet.webp"):
            return httpx.Response(200, content=sheet, headers={"content-type": "image/webp"})
        raise AssertionError(f"Unexpected request: {request.url}")

    service = CodexPetService(
        tmp_path / "data",
        tmp_path / ".codex" / "pets",
        http_transport=httpx.MockTransport(handler),
        guardrails=_AllowRemoteGuardrails(),
    )

    page = service.fetch_remote_catalog(query="fox")
    result = service.activate_remote_pet(page.items[0])

    assert page.total == 1
    assert page.items[0].owner_name == "Maker"
    assert page.items[0].tags == ("animated", "soft")
    assert result.pet.pet_id == "codex-pets:cloud-fox"
    assert result.pet.directory_path.parent == service.codex_pets_dir.resolve()
    assert result.state_asset_paths["idle"].is_file()
    manifest = json.loads(
        (result.pet.directory_path / "pet.json").read_text(encoding="utf-8")
    )
    assert manifest["source"] == "https://codex-pets.net/#/pets/cloud-fox"
    assert manifest["remotePetId"] == "cloud-fox"


def test_remote_catalog_isolates_untrusted_asset_urls(tmp_path: Path) -> None:
    payload = _catalog_item_payload(
        spritesheetUrl="https://example.com/assets/pets/cloud-fox/spritesheet.webp"
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "pets": [payload],
                "page": 1,
                "pageSize": 30,
                "total": 1,
                "totalPages": 1,
            },
        )

    service = CodexPetService(
        tmp_path / "data",
        tmp_path / "pets",
        http_transport=httpx.MockTransport(handler),
        guardrails=_AllowRemoteGuardrails(),
    )

    page = service.fetch_remote_catalog()

    assert page.items == ()
    assert page.skipped_items == 1
    assert "仅允许访问 codex-pets.net" in service.last_remote_errors[0]


def test_remote_download_rejects_declared_oversize(tmp_path: Path) -> None:
    item = CodexPetCatalogItem(
        pet_id="huge",
        display_name="Huge",
        description="",
        sprite_version_number=1,
        kind="other",
        owner_name="",
        tags=(),
        uploaded_at="",
        view_count=0,
        like_count=0,
        spritesheet_url="https://codex-pets.net/assets/pets/huge/spritesheet.webp",
        preview_url="https://codex-pets.net/assets/pets/huge/preview.webp",
        download_url="https://codex-pets.net/api/pets/huge/download",
        catalog_url="https://codex-pets.net/#/pets/huge",
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not-read",
            headers={"content-length": str(CodexPetService.MAX_SPRITESHEET_BYTES + 1)},
        )

    service = CodexPetService(
        tmp_path / "data",
        tmp_path / "pets",
        http_transport=httpx.MockTransport(handler),
        guardrails=_AllowRemoteGuardrails(),
    )

    with pytest.raises(CodexPetError, match="超过允许大小"):
        service.install_remote_pet(item)
    assert not any((tmp_path / "pets").glob(".*.install-*"))


def test_remote_download_rejects_redirect_before_following_it(tmp_path: Path) -> None:
    item = CodexPetCatalogItem(
        pet_id="redirected",
        display_name="Redirected",
        description="",
        sprite_version_number=1,
        kind="other",
        owner_name="",
        tags=(),
        uploaded_at="",
        view_count=0,
        like_count=0,
        spritesheet_url=(
            "https://codex-pets.net/assets/pets/redirected/spritesheet.webp"
        ),
        preview_url="https://codex-pets.net/assets/pets/redirected/preview.webp",
        download_url="https://codex-pets.net/api/pets/redirected/download",
        catalog_url="https://codex-pets.net/#/pets/redirected",
    )
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/private"},
        )

    service = CodexPetService(
        tmp_path / "data",
        tmp_path / "pets",
        http_transport=httpx.MockTransport(handler),
        guardrails=_AllowRemoteGuardrails(),
    )

    with pytest.raises(CodexPetError, match="未授权重定向"):
        service.install_remote_pet(item)
    assert requests == [item.spritesheet_url]
