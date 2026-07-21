"""Read Codex Desktop's built-in pet sprites from its Electron ASAR archive."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from PIL import Image, UnidentifiedImageError


class CodexBuiltinPetSourceError(ValueError):
    """Raised when a Codex Desktop asset archive is malformed or unsafe."""


@dataclass(frozen=True)
class CodexBuiltinPetAsset:
    """One bounded built-in pet entry inside a Codex Desktop ASAR archive."""

    pet_id: str
    display_name: str
    description: str
    asar_path: Path
    entry_path: str
    entry_size: int
    absolute_offset: int
    source_revision: str


@dataclass(frozen=True)
class _AsarEntry:
    path: str
    size: int
    absolute_offset: int


class CodexBuiltinPetSource:
    """Discover and materialize official pets already installed with Codex Desktop."""

    MAX_HEADER_BYTES = 16 * 1024 * 1024
    MAX_ASSET_BYTES = 20 * 1024 * 1024
    MAX_ENTRY_COUNT = 200_000
    SPRITESHEET_PATTERN = re.compile(
        r"^webview/assets/(?P<pet_id>[a-z0-9-]+)-spritesheet-v\d+-[^/]+\.webp$"
    )
    BUILTIN_DETAILS: Mapping[str, tuple[str, str]] = {
        "codex": ("Codex", "最初的 Codex 伙伴，安静陪你完成每一次任务。"),
        "dewey": ("Dewey", "适合专注工作日的沉静伙伴。"),
        "fireball": ("Fireball", "为快速迭代带来一点热烈的行动力。"),
        "hoots": ("Hoots", "一只目光敏锐、擅长守候复杂任务的猫头鹰。"),
        "rocky": ("Rocky", "面对大型改动依然稳稳陪在身边。"),
        "seedy": ("Seedy", "让新想法慢慢发芽的小小绿色伙伴。"),
        "stacky": ("Stacky", "在深度工作中保持节奏与平衡。"),
        "bsod": ("BSOD", "一只带着蓝屏气质的调皮小精灵。"),
        "null-signal": ("Null Signal", "来自安静虚空的一束微弱信号。"),
    }

    def __init__(self, asar_paths: Iterable[Path] | None = None) -> None:
        self._explicit_paths = (
            tuple(Path(path).expanduser() for path in asar_paths)
            if asar_paths is not None
            else None
        )
        self.active_asar_path: Path | None = None
        self.last_errors: tuple[str, ...] = ()

    def discover(self) -> tuple[CodexBuiltinPetAsset, ...]:
        """Return official built-in pets from the newest readable Codex archive."""
        errors: list[str] = []
        self.active_asar_path = None
        for asar_path in self._candidate_asar_paths():
            try:
                entries = self._read_asar_entries(asar_path)
                assets = self._select_builtin_assets(asar_path, entries)
            except (CodexBuiltinPetSourceError, OSError) as exc:
                errors.append(f"{asar_path.name}: {exc}")
                continue
            if not assets:
                errors.append(f"{asar_path.name}: 未发现可兼容的 Codex 内置宠物")
                continue
            self.active_asar_path = asar_path
            self.last_errors = tuple(errors)
            return assets

        self.last_errors = tuple(errors)
        return ()

    def materialize(
        self,
        asset: CodexBuiltinPetAsset,
        cache_root: Path,
        sheet_sizes: Mapping[int, tuple[int, int]],
    ) -> Path:
        """Copy one bounded archive entry into a validated local compatibility package."""
        cache_root = Path(cache_root).expanduser()
        if cache_root.is_symlink():
            raise CodexBuiltinPetSourceError("内置宠物缓存目录不能是符号链接")
        try:
            cache_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CodexBuiltinPetSourceError(f"无法创建内置宠物缓存：{exc}") from exc
        resolved_root = cache_root.resolve()
        target = (resolved_root / asset.source_revision / asset.pet_id).resolve()
        self._require_within(target, resolved_root, "内置宠物缓存路径越界")

        if target.is_dir() and self._cached_package_is_complete(target, asset):
            return target
        if target.exists() or target.is_symlink():
            self._remove_owned_cache_path(target, resolved_root)

        staging = (resolved_root / f".{asset.pet_id}.materialize-{uuid.uuid4().hex}").resolve()
        self._require_within(staging, resolved_root, "内置宠物临时路径越界")
        try:
            staging.mkdir(parents=False, exist_ok=False)
            spritesheet = staging / "spritesheet.webp"
            self._copy_entry(asset, spritesheet)
            version = self._detect_sprite_version(spritesheet, sheet_sizes)
            manifest = {
                "id": asset.pet_id,
                "displayName": asset.display_name,
                "description": asset.description,
                "spriteVersionNumber": version,
                "spritesheetPath": spritesheet.name,
                "codexBuiltinId": asset.pet_id,
                "source": "codex-desktop-builtin",
                "sourceRevision": asset.source_revision,
            }
            (staging / "pet.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            staging.replace(target)
        except CodexBuiltinPetSourceError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise CodexBuiltinPetSourceError(f"准备 Codex 内置宠物失败：{exc}") from exc
        return target

    def _candidate_asar_paths(self) -> tuple[Path, ...]:
        if self._explicit_paths is not None:
            return self._existing_unique_paths(self._explicit_paths)

        candidates: list[Path] = []
        configured = os.environ.get("CODEX_APP_ASAR", "").strip()
        if configured:
            candidates.append(Path(configured).expanduser())

        if os.name == "nt":
            candidates.extend(self._running_codex_asar_paths())
            program_files = os.environ.get("ProgramFiles", "")
            if program_files:
                windows_apps = Path(program_files) / "WindowsApps"
                candidates.extend(
                    self._safe_glob(
                        windows_apps,
                        "OpenAI.Codex_*__2p2nqsd0c76g0/app/resources/app.asar",
                    )
                )
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            if local_app_data:
                local_root = Path(local_app_data)
                candidates.extend(
                    self._safe_glob(
                        local_root / "OpenAI" / "Codex",
                        "app-*/resources/app.asar",
                    )
                )
                candidates.append(local_root / "Programs" / "Codex" / "resources" / "app.asar")
        else:
            candidates.extend(
                (
                    Path("/Applications/Codex.app/Contents/Resources/app.asar"),
                    Path.home()
                    / "Applications"
                    / "Codex.app"
                    / "Contents"
                    / "Resources"
                    / "app.asar",
                    Path("/opt/Codex/resources/app.asar"),
                    Path("/usr/lib/codex/resources/app.asar"),
                )
            )

        return self._existing_unique_paths(candidates)

    @staticmethod
    def _running_codex_asar_paths() -> tuple[Path, ...]:
        """Read executable paths from Windows without spawning a shell."""
        if os.name != "nt":
            return ()

        import ctypes
        from ctypes import wintypes

        class ProcessEntry32W(ctypes.Structure):
            _fields_ = (
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            )

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create_snapshot = kernel32.CreateToolhelp32Snapshot
            create_snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
            create_snapshot.restype = wintypes.HANDLE
            process_first = kernel32.Process32FirstW
            process_first.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
            process_first.restype = wintypes.BOOL
            process_next = kernel32.Process32NextW
            process_next.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
            process_next.restype = wintypes.BOOL
            open_process = kernel32.OpenProcess
            open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            open_process.restype = wintypes.HANDLE
            query_image = kernel32.QueryFullProcessImageNameW
            query_image.argtypes = (
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            )
            query_image.restype = wintypes.BOOL
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = (wintypes.HANDLE,)
            close_handle.restype = wintypes.BOOL
        except (AttributeError, OSError):
            return ()

        snapshot = create_snapshot(0x00000002, 0)
        invalid_handle = wintypes.HANDLE(-1).value
        if not snapshot or snapshot == invalid_handle:
            return ()

        candidates: list[Path] = []
        try:
            entry = ProcessEntry32W()
            entry.dwSize = ctypes.sizeof(ProcessEntry32W)
            has_entry = bool(process_first(snapshot, ctypes.byref(entry)))
            while has_entry:
                if str(entry.szExeFile).casefold() == "codex.exe":
                    handle = open_process(0x1000, False, entry.th32ProcessID)
                    if handle:
                        try:
                            buffer = ctypes.create_unicode_buffer(32768)
                            length = wintypes.DWORD(len(buffer))
                            if query_image(handle, 0, buffer, ctypes.byref(length)):
                                executable = Path(buffer.value)
                                candidates.append(executable.parent / "app.asar")
                        finally:
                            close_handle(handle)
                has_entry = bool(process_next(snapshot, ctypes.byref(entry)))
        finally:
            close_handle(snapshot)
        return tuple(candidates)

    @staticmethod
    def _safe_glob(root: Path, pattern: str) -> tuple[Path, ...]:
        try:
            return tuple(root.glob(pattern))
        except OSError:
            return ()

    @staticmethod
    def _existing_unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
        unique: dict[str, Path] = {}
        for path in paths:
            try:
                if not path.is_file() or path.is_symlink():
                    continue
                resolved = path.resolve(strict=True)
                key = os.path.normcase(str(resolved))
                unique[key] = resolved
            except OSError:
                continue

        def newest_first(path: Path) -> tuple[int, str]:
            try:
                modified = path.stat().st_mtime_ns
            except OSError:
                modified = 0
            return (-modified, os.path.normcase(str(path)))

        return tuple(sorted(unique.values(), key=newest_first))

    def _read_asar_entries(self, asar_path: Path) -> tuple[_AsarEntry, ...]:
        try:
            file_size = asar_path.stat().st_size
            with asar_path.open("rb") as archive:
                prefix = archive.read(16)
                if len(prefix) != 16:
                    raise CodexBuiltinPetSourceError("ASAR 头部不完整")
                size_payload, header_size, header_payload, json_size = struct.unpack("<4I", prefix)
                if size_payload != 4:
                    raise CodexBuiltinPetSourceError("ASAR 大小头不受支持")
                if (
                    header_size < 8
                    or header_size > self.MAX_HEADER_BYTES
                    or header_payload != header_size - 4
                    or json_size <= 1
                    or json_size > header_payload - 4
                ):
                    raise CodexBuiltinPetSourceError("ASAR 索引大小不合法")
                data_offset = 8 + header_size
                if data_offset > file_size:
                    raise CodexBuiltinPetSourceError("ASAR 数据区越界")
                raw_json = archive.read(json_size)
        except CodexBuiltinPetSourceError:
            raise
        except OSError as exc:
            raise CodexBuiltinPetSourceError(f"无法读取 Codex 资源：{exc}") from exc

        try:
            header = json.loads(raw_json.rstrip(b"\0").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CodexBuiltinPetSourceError("ASAR 索引不是有效的 UTF-8 JSON") from exc
        if not isinstance(header, dict):
            raise CodexBuiltinPetSourceError("ASAR 索引顶层必须是对象")

        entries: list[_AsarEntry] = []
        self._walk_asar_tree(
            header,
            prefix="",
            depth=0,
            data_offset=data_offset,
            archive_size=file_size,
            output=entries,
        )
        return tuple(entries)

    def _walk_asar_tree(
        self,
        node: object,
        *,
        prefix: str,
        depth: int,
        data_offset: int,
        archive_size: int,
        output: list[_AsarEntry],
    ) -> None:
        if depth > 32 or len(output) > self.MAX_ENTRY_COUNT:
            raise CodexBuiltinPetSourceError("ASAR 索引层级或条目数量过大")
        if not isinstance(node, dict):
            raise CodexBuiltinPetSourceError("ASAR 目录条目格式错误")
        files = node.get("files")
        if not isinstance(files, dict):
            raise CodexBuiltinPetSourceError("ASAR 目录缺少 files")

        for name, entry in files.items():
            if (
                not isinstance(name, str)
                or not name
                or name in {".", ".."}
                or "/" in name
                or "\\" in name
            ):
                raise CodexBuiltinPetSourceError("ASAR 条目名称不安全")
            if not isinstance(entry, dict):
                raise CodexBuiltinPetSourceError("ASAR 文件条目格式错误")
            relative = f"{prefix}/{name}" if prefix else name
            if "files" in entry:
                self._walk_asar_tree(
                    entry,
                    prefix=relative,
                    depth=depth + 1,
                    data_offset=data_offset,
                    archive_size=archive_size,
                    output=output,
                )
                continue
            if entry.get("unpacked"):
                continue
            size = entry.get("size")
            offset = entry.get("offset")
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                continue
            try:
                relative_offset = int(offset)
            except (TypeError, ValueError):
                continue
            if relative_offset < 0:
                continue
            absolute_offset = data_offset + relative_offset
            if absolute_offset > archive_size or size > archive_size - absolute_offset:
                raise CodexBuiltinPetSourceError("ASAR 文件数据越界")
            output.append(
                _AsarEntry(
                    path=relative,
                    size=size,
                    absolute_offset=absolute_offset,
                )
            )

    def _select_builtin_assets(
        self,
        asar_path: Path,
        entries: tuple[_AsarEntry, ...],
    ) -> tuple[CodexBuiltinPetAsset, ...]:
        stat = asar_path.stat()
        selected: dict[str, CodexBuiltinPetAsset] = {}
        for entry in entries:
            match = self.SPRITESHEET_PATTERN.fullmatch(entry.path)
            if not match or entry.size <= 0 or entry.size > self.MAX_ASSET_BYTES:
                continue
            pet_id = match.group("pet_id")
            details = self.BUILTIN_DETAILS.get(
                pet_id,
                (
                    pet_id.replace("-", " ").title(),
                    "来自本机 Codex Desktop 的内置伙伴。",
                ),
            )
            revision_source = (
                f"{stat.st_size}:{stat.st_mtime_ns}:{entry.path}:"
                f"{entry.absolute_offset}:{entry.size}"
            )
            revision = hashlib.sha256(revision_source.encode("utf-8")).hexdigest()[:16]
            selected[pet_id] = CodexBuiltinPetAsset(
                pet_id=pet_id,
                display_name=details[0],
                description=details[1],
                asar_path=asar_path,
                entry_path=entry.path,
                entry_size=entry.size,
                absolute_offset=entry.absolute_offset,
                source_revision=revision,
            )

        order = {pet_id: index for index, pet_id in enumerate(self.BUILTIN_DETAILS)}
        return tuple(
            sorted(
                selected.values(),
                key=lambda asset: (order.get(asset.pet_id, len(order)), asset.pet_id),
            )
        )

    def _copy_entry(self, asset: CodexBuiltinPetAsset, target: Path) -> None:
        try:
            archive_size = asset.asar_path.stat().st_size
            if (
                asset.entry_size <= 0
                or asset.entry_size > self.MAX_ASSET_BYTES
                or asset.absolute_offset < 0
                or asset.absolute_offset > archive_size
                or asset.entry_size > archive_size - asset.absolute_offset
            ):
                raise CodexBuiltinPetSourceError("Codex 内置宠物数据范围不合法")
            remaining = asset.entry_size
            with asset.asar_path.open("rb") as archive, target.open("xb") as output:
                archive.seek(asset.absolute_offset)
                while remaining:
                    chunk = archive.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise CodexBuiltinPetSourceError("Codex 内置宠物数据提前结束")
                    output.write(chunk)
                    remaining -= len(chunk)
        except CodexBuiltinPetSourceError:
            target.unlink(missing_ok=True)
            raise
        except OSError as exc:
            target.unlink(missing_ok=True)
            raise CodexBuiltinPetSourceError(f"无法读取 Codex 内置宠物：{exc}") from exc

    @staticmethod
    def _detect_sprite_version(
        path: Path,
        sheet_sizes: Mapping[int, tuple[int, int]],
    ) -> int:
        try:
            with path.open("rb") as source:
                header = source.read(12)
        except OSError as exc:
            raise CodexBuiltinPetSourceError("无法检查 Codex 内置宠物图片") from exc
        if not (header.startswith(b"RIFF") and len(header) == 12 and header[8:12] == b"WEBP"):
            raise CodexBuiltinPetSourceError("Codex 内置宠物必须是 WebP 图片")
        try:
            with Image.open(path) as image:
                size = image.size
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            raise CodexBuiltinPetSourceError("Codex 内置宠物不是有效图片") from exc
        for version, expected_size in sheet_sizes.items():
            if size == expected_size:
                return version
        supported = " 或 ".join(f"{width}×{height}" for width, height in sheet_sizes.values())
        raise CodexBuiltinPetSourceError(f"Codex 内置宠物尺寸 {size[0]}×{size[1]} 不受支持，应为 {supported}")

    @staticmethod
    def _cached_package_is_complete(
        directory: Path,
        asset: CodexBuiltinPetAsset,
    ) -> bool:
        manifest = directory / "pet.json"
        spritesheet = directory / "spritesheet.webp"
        try:
            if (
                directory.is_symlink()
                or not manifest.is_file()
                or manifest.is_symlink()
                or not spritesheet.is_file()
                or spritesheet.is_symlink()
            ):
                return False
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
            return (
                spritesheet.stat().st_size == asset.entry_size
                and isinstance(metadata, dict)
                and metadata.get("codexBuiltinId") == asset.pet_id
                and metadata.get("sourceRevision") == asset.source_revision
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False

    @staticmethod
    def _require_within(path: Path, root: Path, message: str) -> None:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise CodexBuiltinPetSourceError(message) from exc

    @classmethod
    def _remove_owned_cache_path(cls, path: Path, root: Path) -> None:
        cls._require_within(path, root, "拒绝清理缓存目录之外的路径")
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)
