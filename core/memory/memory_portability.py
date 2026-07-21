"""Validated, review-gated portability for user-governed Structured Memory."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    MemoryPatchAction,
    MemoryPatchItem,
    MemoryStatus,
    MemoryType,
)
from core.memory.memory_service import sanitize_memory_text
from core.memory.memory_write_gateway import MemoryWriteGateway

MEMORY_PACKAGE_FORMAT = "lobuddy.memory-portability"
MEMORY_PACKAGE_VERSION = 1
MAX_PACKAGE_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_ENTRIES = 500

_PORTABLE_MEMORY_TYPES = {
    MemoryType.USER_PROFILE,
    MemoryType.PROJECT_MEMORY,
    MemoryType.EPISODIC_MEMORY,
    MemoryType.PROCEDURAL_MEMORY,
}


class MemoryPackageEntry(BaseModel):
    """One content-bounded entry inside a Memory Portability Package."""

    model_config = ConfigDict(extra="forbid")

    memory_type: MemoryType
    scope: str = Field(default="global", min_length=1, max_length=120)
    title: str = Field(default="", max_length=120)
    content: str = Field(min_length=1, max_length=2000)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    original_status: MemoryStatus
    entry_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("scope", "title", "content", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class MemoryPackage(BaseModel):
    """Schema-versioned envelope for portable Structured Memory."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["lobuddy.memory-portability"]
    version: Literal[1]
    package_id: str = Field(min_length=36, max_length=36)
    exported_at: str = Field(min_length=19, max_length=40)
    entries: list[MemoryPackageEntry] = Field(max_length=MAX_PACKAGE_ENTRIES)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("package_id")
    @classmethod
    def validate_package_id(cls, value: str) -> str:
        parsed = uuid.UUID(value)
        if str(parsed) != value.lower():
            raise ValueError("package_id must be a canonical UUID")
        return str(parsed)

    @field_validator("exported_at")
    @classmethod
    def validate_exported_at(cls, value: str) -> str:
        datetime.fromisoformat(value)
        return value


@dataclass(frozen=True)
class MemoryExportResult:
    path: Path
    exported_count: int
    package_id: str
    checksum: str


@dataclass(frozen=True)
class MemoryImportPreview:
    path: Path
    package_id: str
    exported_at: str
    file_digest: str
    total_count: int
    importable_count: int
    duplicate_count: int
    type_counts: dict[str, int]


@dataclass(frozen=True)
class MemoryImportResult:
    imported_count: int
    duplicate_count: int
    imported_memory_ids: tuple[str, ...]


class MemoryPortability:
    """Small Interface for exporting, inspecting, and review-gating memory imports.

    Package parsing, integrity checks, semantic de-duplication, and file replacement
    stay inside this Module. All imported writes cross MemoryWriteGateway.
    """

    def __init__(
        self,
        repo: MemoryRepository,
        gateway: MemoryWriteGateway | None,
    ) -> None:
        self._repo = repo
        self._gateway = gateway

    def export_package(self, path: str | Path) -> MemoryExportResult:
        """Atomically export portable memory types without conversation provenance."""
        target = self._validate_export_target(Path(path))
        entries: list[MemoryPackageEntry] = []
        items = self._repo.list_all(limit=10_000)
        for item in sorted(
            items,
            key=lambda value: (
                value.memory_type.value,
                value.scope,
                value.title,
                value.content,
                value.id,
            ),
        ):
            if item.memory_type not in _PORTABLE_MEMORY_TYPES:
                continue
            title = sanitize_memory_text(item.title).strip()[:120]
            content = sanitize_memory_text(item.content).strip()[:2000]
            scope = item.scope.strip()[:120] or "global"
            if not content:
                continue
            if len(entries) >= MAX_PACKAGE_ENTRIES:
                raise ValueError("可迁移记忆超过 500 条，请先停用或整理部分内容")
            digest = self.entry_digest(item.memory_type, scope, title, content)
            entries.append(
                MemoryPackageEntry(
                    memory_type=item.memory_type,
                    scope=scope,
                    title=title,
                    content=content,
                    importance=item.importance,
                    original_status=item.status,
                    entry_digest=digest,
                )
            )
        payload = {
            "format": MEMORY_PACKAGE_FORMAT,
            "version": MEMORY_PACKAGE_VERSION,
            "package_id": str(uuid.uuid4()),
            "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "entries": [entry.model_dump(mode="json") for entry in entries],
        }
        checksum = self._payload_digest(payload)
        package = MemoryPackage.model_validate({**payload, "checksum": checksum})
        raw = (
            json.dumps(
                package.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        if len(raw) > MAX_PACKAGE_BYTES:
            raise ValueError("记忆迁移包超过 2 MB，请先减少记忆数量")
        self._atomic_write(target, raw)
        return MemoryExportResult(
            path=target,
            exported_count=len(entries),
            package_id=package.package_id,
            checksum=package.checksum,
        )

    def inspect_package(self, path: str | Path) -> MemoryImportPreview:
        """Validate a package without mutating long-term memory."""
        package, file_digest = self._load_package(Path(path))
        return self._build_preview(Path(path), package, file_digest)

    def import_package(
        self,
        path: str | Path,
        *,
        expected_file_digest: str,
        session_id: str | None = None,
    ) -> MemoryImportResult:
        """Import a previously inspected package as NEEDS_REVIEW memories."""
        if self._gateway is None:
            raise RuntimeError("导入记忆需要可用的 MemoryWriteGateway")
        package, file_digest = self._load_package(Path(path))
        if file_digest != expected_file_digest:
            raise ValueError("迁移包在预览后发生了变化，请重新检查")
        preview = self._build_preview(Path(path), package, file_digest)
        existing_digests = self._existing_digests()
        candidates: list[tuple[MemoryPatchItem, str]] = []
        for entry in package.entries:
            if entry.entry_digest in existing_digests:
                continue
            existing_digests.add(entry.entry_digest)
            candidates.append(
                (
                    MemoryPatchItem(
                        memory_type=entry.memory_type,
                        action=MemoryPatchAction.ADD,
                        scope=entry.scope,
                        title=entry.title,
                        content=entry.content,
                        confidence=0.5,
                        importance=entry.importance,
                        reason="从用户选择的记忆迁移包导入，等待确认",
                    ),
                    entry.entry_digest,
                )
            )
        saved, concurrent_duplicates = self._gateway.submit_import_review_batch(
            package_id=package.package_id,
            candidates=candidates,
            session_id=session_id,
        )
        return MemoryImportResult(
            imported_count=len(saved),
            duplicate_count=preview.duplicate_count + len(concurrent_duplicates),
            imported_memory_ids=tuple(item.id for item in saved),
        )

    def _build_preview(
        self,
        path: Path,
        package: MemoryPackage,
        file_digest: str,
    ) -> MemoryImportPreview:
        known = self._existing_digests()
        duplicate_count = 0
        importable_count = 0
        for entry in package.entries:
            if entry.entry_digest in known:
                duplicate_count += 1
                continue
            known.add(entry.entry_digest)
            importable_count += 1
        type_counts = Counter(entry.memory_type.value for entry in package.entries)
        return MemoryImportPreview(
            path=path,
            package_id=package.package_id,
            exported_at=package.exported_at,
            file_digest=file_digest,
            total_count=len(package.entries),
            importable_count=importable_count,
            duplicate_count=duplicate_count,
            type_counts=dict(sorted(type_counts.items())),
        )

    def _existing_digests(self) -> set[str]:
        digests = self._repo.list_imported_digests()
        for item in self._repo.list_all(limit=10_000):
            digests.add(
                self.entry_digest(
                    item.memory_type,
                    item.scope,
                    item.title,
                    item.content,
                )
            )
        return digests

    def _load_package(self, path: Path) -> tuple[MemoryPackage, str]:
        if not path.exists() or not path.is_file():
            raise ValueError("找不到记忆迁移包")
        size = path.stat().st_size
        if size <= 0:
            raise ValueError("记忆迁移包为空")
        if size > MAX_PACKAGE_BYTES:
            raise ValueError("记忆迁移包超过 2 MB")
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("记忆迁移包不是有效的 UTF-8 JSON 文件") from exc
        if not isinstance(payload, dict):
            raise ValueError("记忆迁移包必须是 JSON 对象")
        checksum = payload.get("checksum")
        if not isinstance(checksum, str):
            raise ValueError("记忆迁移包缺少校验和")
        unsigned = {key: value for key, value in payload.items() if key != "checksum"}
        if self._payload_digest(unsigned) != checksum:
            raise ValueError("记忆迁移包校验失败，文件可能已损坏或被修改")
        try:
            package = MemoryPackage.model_validate(payload)
        except Exception as exc:
            raise ValueError("记忆迁移包格式或版本不受支持") from exc
        for entry in package.entries:
            expected = self.entry_digest(
                entry.memory_type,
                entry.scope,
                entry.title,
                entry.content,
            )
            if expected != entry.entry_digest:
                raise ValueError("记忆迁移包中的条目校验失败")
            if entry.memory_type not in _PORTABLE_MEMORY_TYPES:
                raise ValueError("记忆迁移包包含不可迁移的记忆类型")
        return package, hashlib.sha256(raw).hexdigest()

    @staticmethod
    def entry_digest(
        memory_type: MemoryType,
        scope: str,
        title: str,
        content: str,
    ) -> str:
        """Return a source-agnostic semantic fingerprint used for idempotency."""
        payload = {
            "memory_type": memory_type.value,
            "scope": scope.strip() or "global",
            "title": title.strip(),
            "content": content.strip(),
        }
        return MemoryPortability._payload_digest(payload)

    @staticmethod
    def _payload_digest(payload: dict) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _validate_export_target(path: Path) -> Path:
        target = path.expanduser()
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        if not target.parent.exists() or not target.parent.is_dir():
            raise ValueError("导出目录不存在")
        return target

    @staticmethod
    def _atomic_write(path: Path, raw: bytes) -> None:
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp_path.write_bytes(raw)
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
