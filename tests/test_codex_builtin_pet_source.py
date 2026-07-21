"""Tests for reading built-in pets from a local Codex Desktop ASAR archive."""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import pytest
from PIL import Image

from core.services.codex_builtin_pet_source import (
    CodexBuiltinPetSource,
    CodexBuiltinPetSourceError,
)
from core.services.codex_pet_service import CodexPetService


def _webp_sheet_bytes(version: int = 2) -> bytes:
    sheet = Image.new("RGBA", CodexPetService.SHEET_SIZES[version], (0, 0, 0, 0))
    for row in range(9):
        for column in range(8):
            left = column * CodexPetService.FRAME_WIDTH + 54
            top = row * CodexPetService.FRAME_HEIGHT + 58
            sheet.paste(
                ((60 + column * 17) % 255, (90 + row * 13) % 255, 210, 255),
                (left, top, left + 84, top + 104),
            )
    output = io.BytesIO()
    sheet.save(output, format="WEBP", lossless=True)
    return output.getvalue()


def _write_asar(
    path: Path,
    files: dict[str, bytes],
    *,
    offset_overrides: dict[str, int] | None = None,
) -> None:
    root: dict[str, object] = {"files": {}}
    payload = bytearray()
    for relative_path, content in files.items():
        parts = relative_path.split("/")
        node = root
        for part in parts[:-1]:
            children = node["files"]
            assert isinstance(children, dict)
            child = children.setdefault(part, {"files": {}})
            assert isinstance(child, dict)
            node = child
        children = node["files"]
        assert isinstance(children, dict)
        declared_offset = len(payload)
        if offset_overrides and relative_path in offset_overrides:
            declared_offset = offset_overrides[relative_path]
        children[parts[-1]] = {
            "size": len(content),
            "offset": str(declared_offset),
        }
        payload.extend(content)

    raw_json = json.dumps(root, separators=(",", ":")).encode("utf-8")
    serialized_string = raw_json + b"\0"
    padding = b"\0" * ((4 - len(serialized_string) % 4) % 4)
    header_payload = struct.pack("<I", len(serialized_string)) + serialized_string + padding
    header_pickle = struct.pack("<I", len(header_payload)) + header_payload
    size_pickle = struct.pack("<II", 4, len(header_pickle))
    path.write_bytes(size_pickle + header_pickle + payload)


def test_discovers_materializes_and_activates_codex_builtin_pet(
    tmp_path: Path,
) -> None:
    asar_path = tmp_path / "app.asar"
    entry_path = "webview/assets/codex-spritesheet-v6-fixture.webp"
    bsod_entry_path = "webview/assets/bsod-spritesheet-v5-fixture.webp"
    sheet_bytes = _webp_sheet_bytes()
    _write_asar(
        asar_path,
        {
            entry_path: sheet_bytes,
            bsod_entry_path: sheet_bytes,
        },
    )

    source = CodexBuiltinPetSource((asar_path,))
    assets = source.discover()

    assert [asset.pet_id for asset in assets] == ["codex", "bsod"]
    assert assets[0].display_name == "Codex"
    package_dir = source.materialize(
        assets[0],
        tmp_path / "cache",
        CodexPetService.SHEET_SIZES,
    )
    manifest = json.loads((package_dir / "pet.json").read_text(encoding="utf-8"))
    assert manifest["codexBuiltinId"] == "codex"
    assert manifest["spriteVersionNumber"] == 2
    assert (package_dir / "spritesheet.webp").read_bytes() == sheet_bytes

    service = CodexPetService(
        tmp_path / "data",
        tmp_path / ".codex" / "pets",
        include_builtins=True,
        builtin_asar_paths=(asar_path,),
    )
    pets = service.discover_pets()

    assert [pet.pet_id for pet in pets] == [
        "codex-builtin:codex",
        "codex-builtin:bsod",
    ]
    assert pets[0].pet_id == "codex-builtin:codex"
    assert pets[0].source_kind == "codex_builtin"
    assert service.codex_app_asar_path == asar_path.resolve()
    result = service.activate_pet(pets[0])
    assert result.state_asset_paths["idle"].is_file()
    assert result.state_asset_paths["review"].is_file()

    asar_path.unlink()
    cached_service = CodexPetService(
        tmp_path / "data",
        tmp_path / ".codex" / "pets",
        include_builtins=True,
        builtin_asar_paths=(asar_path,),
    )
    assert [pet.pet_id for pet in cached_service.discover_pets()] == [
        "codex-builtin:codex",
        "codex-builtin:bsod",
    ]


def test_rejects_asar_entry_whose_data_range_escapes_archive(
    tmp_path: Path,
) -> None:
    asar_path = tmp_path / "broken.asar"
    entry_path = "webview/assets/codex-spritesheet-v6-fixture.webp"
    _write_asar(
        asar_path,
        {entry_path: b"RIFF\x04\x00\x00\x00WEBP"},
        offset_overrides={entry_path: 999_999},
    )
    source = CodexBuiltinPetSource((asar_path,))

    assert source.discover() == ()
    assert len(source.last_errors) == 1
    assert "数据越界" in source.last_errors[0]


def test_materialization_rejects_cache_symlink(tmp_path: Path) -> None:
    asar_path = tmp_path / "app.asar"
    entry_path = "webview/assets/codex-spritesheet-v6-fixture.webp"
    _write_asar(asar_path, {entry_path: _webp_sheet_bytes()})
    source = CodexBuiltinPetSource((asar_path,))
    asset = source.discover()[0]
    real_cache = tmp_path / "real-cache"
    real_cache.mkdir()
    linked_cache = tmp_path / "linked-cache"
    try:
        linked_cache.symlink_to(real_cache, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this host")

    with pytest.raises(CodexBuiltinPetSourceError, match="符号链接"):
        source.materialize(asset, linked_cache, CodexPetService.SHEET_SIZES)
