"""Discover and adapt custom pets installed by the Codex desktop app."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from core.agent.image_validation import inspect_image_file
from core.models.appearance import PetAppearance
from core.safety.guardrails import SafetyGuardrails
from core.services.codex_builtin_pet_source import (
    CodexBuiltinPetSource,
    CodexBuiltinPetSourceError,
)


class CodexPetError(ValueError):
    """Raised when a Codex pet package is unsafe or malformed."""


@dataclass(frozen=True)
class CodexPetPackage:
    """Validated Codex pet metadata and its local spritesheet."""

    pet_id: str
    slug: str
    display_name: str
    description: str
    sprite_version_number: int
    directory_path: Path
    spritesheet_path: Path
    source_kind: str = "custom"


@dataclass(frozen=True)
class CodexPetImportResult:
    """Lobuddy-compatible animations rendered from a Codex pet."""

    pet: CodexPetPackage
    asset_path: Path
    state_asset_paths: Mapping[str, Path]


def apply_codex_pet_appearance(
    appearance: PetAppearance,
    result: CodexPetImportResult,
) -> None:
    """Apply one validated Codex pet result without changing unrelated appearance settings."""
    appearance.custom_asset_path = str(result.asset_path)
    appearance.custom_asset_type = "gif"
    appearance.custom_asset_source = "codex"
    appearance.custom_asset_name = result.pet.display_name
    appearance.codex_pet_id = result.pet.pet_id
    appearance.custom_state_asset_paths = {
        state: str(path) for state, path in result.state_asset_paths.items()
    }


@dataclass(frozen=True)
class CodexPetCatalogItem:
    """One validated public pet listing from codex-pets.net."""

    pet_id: str
    display_name: str
    description: str
    sprite_version_number: int
    kind: str
    owner_name: str
    tags: tuple[str, ...]
    uploaded_at: str
    view_count: int
    like_count: int
    spritesheet_url: str
    preview_url: str
    download_url: str
    catalog_url: str


@dataclass(frozen=True)
class CodexPetCatalogPage:
    """A validated, paginated catalog response."""

    items: tuple[CodexPetCatalogItem, ...]
    page: int
    page_size: int
    total: int
    total_pages: int
    skipped_items: int = 0


class CodexPetService:
    """Discover, safely adopt, and render Codex-compatible pets."""

    WEBSITE_URL = "https://codex-pets.net/"
    CATALOG_URL = "https://codex-pets.net/api/pets"
    MANIFEST_NAME = "pet.json"
    MAX_MANIFEST_BYTES = 256 * 1024
    MAX_SPRITESHEET_BYTES = 20 * 1024 * 1024
    MAX_CATALOG_BYTES = 2 * 1024 * 1024
    MAX_PREVIEW_BYTES = 5 * 1024 * 1024
    MAX_PREVIEW_DIMENSION = 4096
    MAX_REMOTE_PAGE_SIZE = 30
    HTTP_TIMEOUT_SECONDS = 15.0
    FRAME_WIDTH = 192
    FRAME_HEIGHT = 208
    SHEET_SIZES = {1: (1536, 1872), 2: (1536, 2288)}
    SUPPORTED_SPRITESHEET_EXTENSIONS = {".png", ".webp"}
    REMOTE_HOST = "codex-pets.net"
    REMOTE_ASSET_PREFIX = "/assets/pets/"
    REMOTE_DOWNLOAD_PREFIX = "/api/pets/"
    REMOTE_SORTS = {"newest", "liked", "viewed", "random"}

    # Rows match the Codex desktop app's 8×9 sprite contract. Lobuddy keeps
    # "success" as a task-facing alias of the canonical jumping animation.
    ANIMATIONS: Mapping[str, tuple[int, tuple[int, ...]]] = {
        "idle": (0, (1680, 660, 660, 840, 840, 1920)),
        "running_right": (1, (100, 100, 100, 100, 100, 100, 100, 180)),
        "running_left": (2, (100, 100, 100, 100, 100, 100, 100, 180)),
        "waving": (3, (140, 140, 140, 280)),
        "jumping": (4, (120, 120, 120, 120, 300)),
        "failed": (5, (140, 140, 140, 140, 140, 140, 140, 240)),
        "waiting": (6, (150, 150, 150, 150, 150, 260)),
        "running": (7, (120, 120, 120, 120, 120, 220)),
        "review": (8, (140, 140, 140, 140, 140, 280)),
        "success": (4, (120, 120, 120, 120, 300)),
    }

    def __init__(
        self,
        data_dir: Path | None = None,
        codex_pets_dir: Path | None = None,
        *,
        http_transport: httpx.BaseTransport | None = None,
        guardrails: SafetyGuardrails | None = None,
        include_builtins: bool | None = None,
        builtin_asar_paths: tuple[Path, ...] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir or "data").expanduser()
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        self.codex_pets_dir = Path(codex_pets_dir or codex_home / "pets").expanduser()
        self.cache_dir = self.data_dir / "user_assets" / "codex_pets"
        self.preview_cache_dir = self.cache_dir / "catalog_previews"
        self._http_transport = http_transport
        self._guardrails = guardrails or SafetyGuardrails(self.data_dir)
        self._include_builtins = (
            codex_pets_dir is None if include_builtins is None else include_builtins
        )
        self._builtin_source = CodexBuiltinPetSource(builtin_asar_paths)
        self.last_errors: tuple[str, ...] = ()
        self.last_remote_errors: tuple[str, ...] = ()

    def discover_pets(self) -> list[CodexPetPackage]:
        """Return installed, adopted, and Codex-bundled pets with isolated errors."""
        pets: list[CodexPetPackage] = []
        errors: list[str] = []
        if self.codex_pets_dir.is_dir():
            try:
                candidates = sorted(
                    self.codex_pets_dir.iterdir(),
                    key=lambda item: item.name.casefold(),
                )
            except OSError as exc:
                errors.append(f"无法读取 Codex 宠物目录：{exc}")
                candidates = []

            for directory in candidates:
                if not directory.is_dir() or directory.is_symlink():
                    continue
                try:
                    pets.append(self.load_package(directory))
                except CodexPetError as exc:
                    errors.append(f"{directory.name}: {exc}")

        if self._include_builtins:
            pets.extend(self._discover_cached_builtin_pets(errors))
            for asset in self._builtin_source.discover():
                try:
                    package_dir = self._builtin_source.materialize(
                        asset,
                        self.cache_dir / "codex_desktop",
                        self.SHEET_SIZES,
                    )
                    pets.append(
                        self.load_package(
                            package_dir,
                            full_image_validation=False,
                        )
                    )
                except (CodexBuiltinPetSourceError, CodexPetError) as exc:
                    errors.append(f"Codex 内置 {asset.display_name}: {exc}")
            errors.extend(f"Codex 桌面资源: {error}" for error in self._builtin_source.last_errors)

        self.last_errors = tuple(errors)
        unique = {pet.pet_id: pet for pet in pets}
        source_order = {"codex_builtin": 0, "codex_pets": 1, "custom": 2}
        builtin_order = {
            f"codex-builtin:{pet_id}": index
            for index, pet_id in enumerate(CodexBuiltinPetSource.BUILTIN_DETAILS)
        }
        return sorted(
            unique.values(),
            key=lambda pet: (
                source_order.get(pet.source_kind, 99),
                builtin_order.get(pet.pet_id, len(builtin_order)),
                pet.display_name.casefold(),
            ),
        )

    @property
    def codex_app_asar_path(self) -> Path | None:
        """Return the Codex Desktop archive used for the latest discovery."""
        return self._builtin_source.active_asar_path

    def fetch_remote_catalog(
        self,
        *,
        page: int = 1,
        page_size: int = MAX_REMOTE_PAGE_SIZE,
        query: str = "",
        sort: str = "newest",
    ) -> CodexPetCatalogPage:
        """Fetch and validate one public catalog page without touching local state."""
        page = max(1, int(page))
        page_size = max(1, min(self.MAX_REMOTE_PAGE_SIZE, int(page_size)))
        sort = sort if sort in self.REMOTE_SORTS else "newest"
        query = query.strip()[:120]
        params: dict[str, object] = {
            "page": page,
            "pageSize": page_size,
            "sort": sort,
        }
        if query:
            # The public gallery has used both names during API revisions.
            # Supplying both is backward compatible because unknown query keys are ignored.
            params["q"] = query
            params["search"] = query

        payload = self._request_json(self.CATALOG_URL, params=params)
        raw_items = payload.get("pets")
        if not isinstance(raw_items, list):
            raise CodexPetError("Codex Pets 目录响应缺少 pets 列表")

        items: list[CodexPetCatalogItem] = []
        errors: list[str] = []
        for index, raw in enumerate(raw_items):
            try:
                items.append(self._parse_catalog_item(raw))
            except CodexPetError as exc:
                errors.append(f"item[{index}]: {exc}")
        self.last_remote_errors = tuple(errors)

        response_page = self._safe_int(payload.get("page"), page, minimum=1)
        response_size = self._safe_int(payload.get("pageSize"), page_size, minimum=1)
        total = self._safe_int(payload.get("total"), len(items), minimum=0)
        total_pages = self._safe_int(
            payload.get("totalPages"),
            max(1, (total + response_size - 1) // response_size),
            minimum=1,
        )
        return CodexPetCatalogPage(
            items=tuple(items),
            page=response_page,
            page_size=response_size,
            total=total,
            total_pages=total_pages,
            skipped_items=len(errors),
        )

    def fetch_remote_preview(self, pet: CodexPetCatalogItem) -> Path:
        """Download and validate one selected catalog preview into a bounded cache."""
        self._validate_remote_url(pet.preview_url, (self.REMOTE_ASSET_PREFIX,))
        digest = hashlib.sha256(pet.preview_url.encode("utf-8")).hexdigest()[:20]
        if self.preview_cache_dir.is_symlink():
            raise CodexPetError("在线宠物预览缓存目录不能是符号链接")
        self.preview_cache_dir.mkdir(parents=True, exist_ok=True)
        cache_root = self.preview_cache_dir.resolve()
        suffix = Path(urlparse(pet.preview_url).path).suffix.casefold()
        if suffix not in {".png", ".webp", ".jpg", ".jpeg"}:
            suffix = ".webp"
        target = (cache_root / f"{digest}{suffix}").resolve()
        try:
            target.relative_to(cache_root)
        except ValueError as exc:
            raise CodexPetError("在线宠物预览缓存路径越界") from exc
        if target.is_symlink():
            raise CodexPetError("在线宠物预览缓存文件不能是符号链接")
        if target.is_file():
            try:
                self._validate_preview(target)
                return target
            except CodexPetError:
                target.unlink(missing_ok=True)

        temporary = target.with_name(f"{target.stem}.tmp-{uuid.uuid4().hex}{target.suffix}")
        try:
            self._download_to_path(pet.preview_url, temporary, self.MAX_PREVIEW_BYTES)
            self._validate_preview(temporary)
            temporary.replace(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return target

    def install_remote_pet(self, pet: CodexPetCatalogItem) -> CodexPetPackage:
        """Install one catalog pet as a validated local Codex package."""
        self._validate_remote_url(pet.spritesheet_url, (self.REMOTE_ASSET_PREFIX,))
        root = self.ensure_codex_pets_dir()
        revision = hashlib.sha256(
            f"{pet.pet_id}\0{pet.spritesheet_url}".encode("utf-8")
        ).hexdigest()[:10]
        target_name = f"lobuddy-{self._safe_slug(pet.pet_id)}-{revision}"
        target = (root / target_name).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise CodexPetError("在线宠物安装路径越界") from exc

        if target.exists():
            return self.load_package(target)

        staging = (root / f".{target_name}.install-{uuid.uuid4().hex}").resolve()
        try:
            staging.relative_to(root)
        except ValueError as exc:
            raise CodexPetError("在线宠物临时路径越界") from exc

        try:
            staging.mkdir(parents=False, exist_ok=False)
            spritesheet = staging / "spritesheet.webp"
            self._download_to_path(
                pet.spritesheet_url,
                spritesheet,
                self.MAX_SPRITESHEET_BYTES,
            )
            manifest = {
                "id": pet.pet_id,
                "displayName": pet.display_name,
                "description": pet.description,
                "spriteVersionNumber": pet.sprite_version_number,
                "spritesheetPath": spritesheet.name,
                "remotePetId": pet.pet_id,
                "source": pet.catalog_url,
                "ownerName": pet.owner_name,
                "kind": pet.kind,
                "tags": list(pet.tags),
            }
            manifest_path = staging / self.MANIFEST_NAME
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.load_package(staging)
            staging.replace(target)
        except CodexPetError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise CodexPetError(f"安装在线宠物失败：{exc}") from exc

        return self.load_package(target)

    def activate_remote_pet(self, pet: CodexPetCatalogItem) -> CodexPetImportResult:
        """Adopt one public catalog pet and prepare its Lobuddy state animations."""
        return self.activate_pet(self.install_remote_pet(pet))

    def load_package(
        self,
        directory: Path,
        *,
        full_image_validation: bool = True,
    ) -> CodexPetPackage:
        """Validate one official Codex pet directory."""
        directory = Path(directory).expanduser()
        if directory.is_symlink() or not directory.is_dir():
            raise CodexPetError("宠物包目录不存在或是符号链接")

        try:
            root = directory.resolve(strict=True)
        except OSError as exc:
            raise CodexPetError("无法解析宠物包目录") from exc

        manifest_path = root / self.MANIFEST_NAME
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise CodexPetError("缺少 pet.json")
        try:
            manifest_size = manifest_path.stat().st_size
        except OSError as exc:
            raise CodexPetError("无法读取 pet.json") from exc
        if manifest_size <= 0 or manifest_size > self.MAX_MANIFEST_BYTES:
            raise CodexPetError("pet.json 大小不合法")

        try:
            raw_manifest = manifest_path.read_text(encoding="utf-8")
            metadata = json.loads(raw_manifest)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CodexPetError("pet.json 不是有效的 UTF-8 JSON") from exc
        if not isinstance(metadata, dict):
            raise CodexPetError("pet.json 顶层必须是对象")

        display_name = metadata.get("displayName") or metadata.get("id") or root.name
        if not isinstance(display_name, str) or not display_name.strip():
            raise CodexPetError("displayName 必须是非空文本")
        display_name = display_name.strip()
        if len(display_name) > 128:
            raise CodexPetError("displayName 不能超过 128 个字符")

        description = metadata.get("description") or ""
        if not isinstance(description, str):
            raise CodexPetError("description 必须是文本")
        description = description.strip()
        if len(description) > 2000:
            raise CodexPetError("description 不能超过 2000 个字符")

        version = metadata.get("spriteVersionNumber", 1)
        if isinstance(version, bool) or version not in self.SHEET_SIZES:
            raise CodexPetError("spriteVersionNumber 仅支持 1 或 2")

        relative_sheet = metadata.get("spritesheetPath", "spritesheet.webp")
        spritesheet_path = self._resolve_spritesheet(root, relative_sheet)
        self._validate_spritesheet(
            spritesheet_path,
            version,
            full_image_validation=full_image_validation,
        )
        remote_pet_id = self._source_identifier(metadata.get("remotePetId"), "remotePetId")
        builtin_pet_id = self._source_identifier(
            metadata.get("codexBuiltinId"),
            "codexBuiltinId",
        )
        if remote_pet_id is not None and builtin_pet_id is not None:
            raise CodexPetError("宠物包不能同时声明在线与 Codex 内置来源")
        if builtin_pet_id is not None:
            pet_id = f"codex-builtin:{builtin_pet_id}"
            source_kind = "codex_builtin"
        elif remote_pet_id is not None:
            pet_id = f"codex-pets:{remote_pet_id}"
            source_kind = "codex_pets"
        else:
            pet_id = f"custom:{root.name}"
            source_kind = "custom"

        return CodexPetPackage(
            pet_id=pet_id,
            slug=self._safe_slug(root.name or display_name),
            display_name=display_name,
            description=description,
            sprite_version_number=version,
            directory_path=root,
            spritesheet_path=spritesheet_path,
            source_kind=source_kind,
        )

    def activate_pet(self, pet: CodexPetPackage) -> CodexPetImportResult:
        """Render Codex action rows to cached GIFs consumable by the Qt UI."""
        # Revalidate because packages may have changed after the library was opened.
        validated = self.load_package(pet.directory_path)
        digest = self._fingerprint(validated)
        output_dir = self.cache_dir / validated.slug / digest
        output_dir.mkdir(parents=True, exist_ok=True)
        state_paths = {state: (output_dir / f"{state}.gif").resolve() for state in self.ANIMATIONS}

        if not all(path.is_file() for path in state_paths.values()):
            self._render_animations(validated, state_paths)
            self._write_cache_metadata(validated, output_dir, state_paths)

        return CodexPetImportResult(
            pet=validated,
            asset_path=state_paths["idle"],
            state_asset_paths=state_paths,
        )

    def ensure_codex_pets_dir(self) -> Path:
        """Create and return the local Codex pet directory on explicit UI action."""
        if self.codex_pets_dir.is_symlink():
            raise CodexPetError("Codex 宠物目录不能是符号链接")
        self.codex_pets_dir.mkdir(parents=True, exist_ok=True)
        return self.codex_pets_dir.resolve()

    def _discover_cached_builtin_pets(
        self,
        errors: list[str],
    ) -> list[CodexPetPackage]:
        cache_root = self.cache_dir / "codex_desktop"
        if cache_root.is_symlink() or not cache_root.is_dir():
            return []
        try:
            resolved_root = cache_root.resolve(strict=True)
            revisions = sorted(
                (
                    directory
                    for directory in cache_root.iterdir()
                    if directory.is_dir() and not directory.is_symlink()
                ),
                key=lambda directory: directory.stat().st_mtime_ns,
            )
        except OSError as exc:
            errors.append(f"无法读取 Codex 内置宠物缓存：{exc}")
            return []

        package_dirs: list[Path] = []
        for revision in revisions:
            try:
                candidates = sorted(revision.iterdir(), key=lambda path: path.name.casefold())
            except OSError as exc:
                errors.append(f"Codex 内置缓存 {revision.name}: {exc}")
                continue
            for package_dir in candidates:
                if not package_dir.is_dir() or package_dir.is_symlink():
                    continue
                try:
                    package_dir.resolve(strict=True).relative_to(resolved_root)
                except (OSError, ValueError):
                    errors.append(f"Codex 内置缓存 {package_dir.name}: 路径越界")
                    continue
                package_dirs.append(package_dir)

        pets: list[CodexPetPackage] = []
        for package_dir in package_dirs[-100:]:
            try:
                pet = self.load_package(
                    package_dir,
                    full_image_validation=False,
                )
                if pet.source_kind != "codex_builtin":
                    raise CodexPetError("缓存包缺少 Codex 内置来源")
                pets.append(pet)
            except CodexPetError as exc:
                errors.append(f"Codex 内置缓存 {package_dir.name}: {exc}")
        return pets

    def _resolve_spritesheet(self, root: Path, value: object) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise CodexPetError("spritesheetPath 必须是非空相对路径")
        value = value.strip()
        relative = Path(value)
        if (
            relative.is_absolute()
            or relative.drive
            or value.startswith(("/", "\\"))
            or ".." in relative.parts
        ):
            raise CodexPetError("spritesheetPath 必须留在宠物包目录内")
        try:
            candidate = (root / relative).resolve(strict=True)
            candidate.relative_to(root)
        except (OSError, ValueError) as exc:
            raise CodexPetError("spritesheetPath 指向了宠物包之外或文件不存在") from exc
        if candidate.is_symlink() or not candidate.is_file():
            raise CodexPetError("精灵图不存在或是符号链接")
        if candidate.suffix.lower() not in self.SUPPORTED_SPRITESHEET_EXTENSIONS:
            raise CodexPetError("Codex 精灵图仅支持 PNG 或 WebP")
        return candidate

    def _validate_spritesheet(
        self,
        path: Path,
        version: int,
        *,
        full_image_validation: bool = True,
    ) -> None:
        try:
            if path.stat().st_size > self.MAX_SPRITESHEET_BYTES:
                raise CodexPetError("精灵图不能超过 20 MB")
            inspection = inspect_image_file(path)
            if inspection.mime_type not in {"image/png", "image/webp"}:
                raise CodexPetError("精灵图内容必须是 PNG 或 WebP")
            with Image.open(path) as image:
                if image.size != self.SHEET_SIZES[version]:
                    expected = "×".join(str(value) for value in self.SHEET_SIZES[version])
                    actual = f"{image.width}×{image.height}"
                    raise CodexPetError(f"v{version} 精灵图应为 {expected}，实际为 {actual}")
                if full_image_validation:
                    image.load()
        except CodexPetError:
            raise
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            raise CodexPetError(f"精灵图校验失败：{exc}") from exc

    def _render_animations(
        self,
        pet: CodexPetPackage,
        state_paths: Mapping[str, Path],
    ) -> None:
        try:
            with Image.open(pet.spritesheet_path) as source:
                sheet = source.convert("RGBA")
                for state, (row, durations) in self.ANIMATIONS.items():
                    frames = [
                        self._extract_frame(sheet, row, column) for column in range(len(durations))
                    ]
                    target = state_paths[state]
                    temporary = target.with_suffix(".gif.tmp")
                    frames[0].save(
                        temporary,
                        format="GIF",
                        save_all=True,
                        append_images=frames[1:],
                        duration=list(durations),
                        loop=0,
                        disposal=2,
                        optimize=False,
                    )
                    temporary.replace(target)
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            raise CodexPetError(f"转换 Codex 宠物动画失败：{exc}") from exc

    def _extract_frame(self, sheet: Image.Image, row: int, column: int) -> Image.Image:
        left = column * self.FRAME_WIDTH
        top = row * self.FRAME_HEIGHT
        frame = sheet.crop((left, top, left + self.FRAME_WIDTH, top + self.FRAME_HEIGHT))
        # Lobuddy's pet stage is square; center the original frame without stretching it.
        canvas = Image.new("RGBA", (self.FRAME_HEIGHT, self.FRAME_HEIGHT), (0, 0, 0, 0))
        canvas.alpha_composite(frame, ((self.FRAME_HEIGHT - self.FRAME_WIDTH) // 2, 0))
        return canvas

    @staticmethod
    def _source_identifier(value: object, field_name: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise CodexPetError(f"{field_name} 必须是文本")
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > 128
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", normalized)
        ):
            raise CodexPetError(f"{field_name} 必须是安全的 1–128 字符标识")
        return normalized

    def _fingerprint(self, pet: CodexPetPackage) -> str:
        digest = hashlib.sha256()
        digest.update(str(pet.sprite_version_number).encode("ascii"))
        digest.update(pet.display_name.encode("utf-8"))
        digest.update(pet.description.encode("utf-8"))
        with pet.spritesheet_path.open("rb") as spritesheet:
            for chunk in iter(lambda: spritesheet.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()[:16]

    def _write_cache_metadata(
        self,
        pet: CodexPetPackage,
        output_dir: Path,
        state_paths: Mapping[str, Path],
    ) -> None:
        metadata = {
            "source": "codex",
            "petId": pet.pet_id,
            "displayName": pet.display_name,
            "description": pet.description,
            "spriteVersionNumber": pet.sprite_version_number,
            "sourceDirectory": str(pet.directory_path),
            "animations": {name: path.name for name, path in state_paths.items()},
        }
        target = output_dir / "metadata.json"
        temporary = output_dir / "metadata.json.tmp"
        temporary.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)

    def _request_json(
        self,
        url: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> dict:
        self._validate_remote_url(url, ("/api/pets",))
        try:
            with self._http_client() as client:
                with client.stream("GET", url, params=params) as response:
                    if response.is_redirect:
                        raise CodexPetError("Codex Pets 目录发生了未授权重定向")
                    response.raise_for_status()
                    self._validate_remote_url(str(response.url), ("/api/pets",))
                    payload = self._read_limited(response, self.MAX_CATALOG_BYTES)
        except CodexPetError:
            raise
        except httpx.TimeoutException as exc:
            raise CodexPetError("连接 Codex Pets 超时，请稍后重试") from exc
        except httpx.HTTPStatusError as exc:
            raise CodexPetError(f"Codex Pets 返回 HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise CodexPetError(f"无法连接 Codex Pets：{exc}") from exc

        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CodexPetError("Codex Pets 目录不是有效的 UTF-8 JSON") from exc
        if not isinstance(decoded, dict):
            raise CodexPetError("Codex Pets 目录响应顶层必须是对象")
        return decoded

    def _download_to_path(self, url: str, target: Path, limit: int) -> None:
        self._validate_remote_url(url, (self.REMOTE_ASSET_PREFIX,))
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._http_client() as client:
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        raise CodexPetError("Codex Pets 资源发生了未授权重定向")
                    response.raise_for_status()
                    self._validate_remote_url(
                        str(response.url),
                        (self.REMOTE_ASSET_PREFIX,),
                    )
                    declared_size = self._content_length(response)
                    if declared_size is not None and declared_size > limit:
                        raise CodexPetError(f"Codex 宠物资源超过允许大小（最大 {limit // 1024 // 1024} MB）")
                    total = 0
                    with target.open("xb") as output:
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > limit:
                                raise CodexPetError("Codex 宠物资源下载超过安全大小限制")
                            output.write(chunk)
                    if total <= 0:
                        raise CodexPetError("Codex 宠物资源为空")
        except CodexPetError:
            target.unlink(missing_ok=True)
            raise
        except httpx.TimeoutException as exc:
            target.unlink(missing_ok=True)
            raise CodexPetError("下载 Codex 宠物超时，请稍后重试") from exc
        except httpx.HTTPStatusError as exc:
            target.unlink(missing_ok=True)
            raise CodexPetError(f"宠物资源返回 HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, OSError) as exc:
            target.unlink(missing_ok=True)
            raise CodexPetError(f"下载 Codex 宠物失败：{exc}") from exc

    def _http_client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.HTTP_TIMEOUT_SECONDS,
            follow_redirects=False,
            transport=self._http_transport,
            headers={
                "Accept": "application/json,image/avif,image/webp,image/png,*/*",
                "User-Agent": "Lobuddy/CodexPets",
            },
        )

    def _validate_remote_url(
        self,
        url: str,
        allowed_prefixes: tuple[str, ...],
        *,
        check_dns: bool = True,
    ) -> None:
        if check_dns:
            error = self._guardrails.validate_web_url(url)
            if error:
                raise CodexPetError(f"Codex Pets 地址未通过安全校验：{error}")
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").casefold() != self.REMOTE_HOST
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise CodexPetError("仅允许访问 codex-pets.net 的 HTTPS 资源")
        if not any(parsed.path.startswith(prefix) for prefix in allowed_prefixes):
            raise CodexPetError("Codex Pets 资源路径不在允许范围内")
        if any(part == ".." for part in parsed.path.split("/")):
            raise CodexPetError("Codex Pets 资源路径包含越界片段")

    def _parse_catalog_item(self, raw: object) -> CodexPetCatalogItem:
        if not isinstance(raw, dict):
            raise CodexPetError("目录项目必须是对象")
        pet_id = self._required_text(raw.get("id"), "id", 128)
        display_name = self._required_text(
            raw.get("displayName") or pet_id,
            "displayName",
            128,
        )
        description = self._optional_text(raw.get("description"), "description", 2000)
        version = raw.get("spriteVersionNumber", 1)
        if isinstance(version, bool) or version not in self.SHEET_SIZES:
            raise CodexPetError("spriteVersionNumber 仅支持 1 或 2")

        spritesheet_url = self._required_text(
            raw.get("spritesheetUrl"),
            "spritesheetUrl",
            2048,
        )
        preview_url = self._required_text(
            raw.get("previewUrl") or raw.get("posterUrl"),
            "previewUrl",
            2048,
        )
        self._validate_remote_url(
            spritesheet_url,
            (self.REMOTE_ASSET_PREFIX,),
            check_dns=False,
        )
        self._validate_remote_url(
            preview_url,
            (self.REMOTE_ASSET_PREFIX,),
            check_dns=False,
        )

        raw_download_url = self._required_text(
            raw.get("downloadUrl"),
            "downloadUrl",
            2048,
        )
        download_url = urljoin(self.WEBSITE_URL, raw_download_url)
        self._validate_remote_url(
            download_url,
            (self.REMOTE_DOWNLOAD_PREFIX,),
            check_dns=False,
        )

        raw_tags = raw.get("tags") or []
        if not isinstance(raw_tags, list):
            raise CodexPetError("tags 必须是列表")
        tags = tuple(
            tag.strip()
            for tag in raw_tags[:16]
            if isinstance(tag, str) and tag.strip() and len(tag.strip()) <= 40
        )
        kind = self._optional_text(raw.get("kind"), "kind", 40) or "other"
        owner_name = self._optional_text(
            raw.get("ownerName") or raw.get("ownerHandle"),
            "ownerName",
            128,
        )
        return CodexPetCatalogItem(
            pet_id=pet_id,
            display_name=display_name,
            description=description,
            sprite_version_number=version,
            kind=kind,
            owner_name=owner_name,
            tags=tags,
            uploaded_at=self._optional_text(raw.get("uploadedAt"), "uploadedAt", 80),
            view_count=self._safe_int(raw.get("viewCount"), 0, minimum=0),
            like_count=self._safe_int(raw.get("likeCount"), 0, minimum=0),
            spritesheet_url=spritesheet_url,
            preview_url=preview_url,
            download_url=download_url,
            catalog_url=f"{self.WEBSITE_URL}#/pets/{pet_id}",
        )

    def _validate_preview(self, path: Path) -> None:
        try:
            inspection = inspect_image_file(path)
            if inspection.mime_type not in {"image/png", "image/webp", "image/jpeg"}:
                raise CodexPetError("在线宠物预览必须是 PNG、WebP 或 JPEG")
            with Image.open(path) as image:
                if (
                    image.width <= 0
                    or image.height <= 0
                    or image.width > self.MAX_PREVIEW_DIMENSION
                    or image.height > self.MAX_PREVIEW_DIMENSION
                ):
                    raise CodexPetError("在线宠物预览尺寸不合法（最大 4096×4096）")
                image.verify()
        except CodexPetError:
            raise
        except (
            OSError,
            SyntaxError,
            UnidentifiedImageError,
            ValueError,
            Image.DecompressionBombError,
        ) as exc:
            raise CodexPetError(f"在线宠物预览校验失败：{exc}") from exc

    @staticmethod
    def _read_limited(response: httpx.Response, limit: int) -> bytes:
        declared_size = CodexPetService._content_length(response)
        if declared_size is not None and declared_size > limit:
            raise CodexPetError("Codex Pets 目录响应超过安全大小限制")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > limit:
                raise CodexPetError("Codex Pets 目录响应超过安全大小限制")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _content_length(response: httpx.Response) -> int | None:
        value = response.headers.get("content-length")
        if not value:
            return None
        try:
            return max(0, int(value))
        except ValueError:
            return None

    @staticmethod
    def _required_text(value: object, name: str, limit: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise CodexPetError(f"{name} 必须是非空文本")
        text = value.strip()
        if len(text) > limit:
            raise CodexPetError(f"{name} 不能超过 {limit} 个字符")
        return text

    @staticmethod
    def _optional_text(value: object, name: str, limit: int) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise CodexPetError(f"{name} 必须是文本")
        text = value.strip()
        if len(text) > limit:
            raise CodexPetError(f"{name} 不能超过 {limit} 个字符")
        return text

    @staticmethod
    def _safe_int(value: object, default: int, *, minimum: int) -> int:
        if isinstance(value, bool):
            return default
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
        return (slug or "pet")[:80]
