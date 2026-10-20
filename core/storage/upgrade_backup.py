"""Private, checksummed backups and atomic imports into a fresh desktop directory."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from core.config import Settings
from core.storage.db import Database
from core.storage.desktop_migrations import migrate_desktop
from core.storage.service_repo import ServiceRepository


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: int = 1
    identity: str
    source_data: str
    source_workspace: str
    created_at: str
    files: dict[str, str]


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy(source: Path, target: Path) -> None:
    if source.is_symlink():
        raise ValueError("备份包含符号链接，请先确认资源归属")
    if source.is_dir():
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        for child in source.iterdir():
            _copy(child, target / child.name)
    elif source.is_file():
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o600)
    else:
        raise ValueError("备份只支持普通文件和目录")


def _validate_destination(destination: Path, sources: tuple[Path, ...]) -> None:
    if destination.exists():
        raise ValueError("目标目录已存在，不覆盖已有资料")
    resolved = destination.resolve()
    if any(resolved.is_relative_to(source.resolve()) for source in sources):
        raise ValueError("备份或导入目录不能位于源资料内部")


def create_backup(data: Path, workspace: Path, destination: Path) -> BackupManifest:
    data, workspace, destination = data.resolve(), workspace.resolve(), destination.absolute()
    _validate_destination(destination, (data, workspace))
    for ready in (data / "dsh-home").glob("bridge-*/ready.json"):
        pid = json.loads(ready.read_text(encoding="utf-8")).get("pid")
        if not isinstance(pid, int) or pid <= 0:
            raise ValueError("引擎状态无法校验，请关闭应用后备份")
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError as error:
            raise ValueError("引擎状态无法校验，请关闭应用后备份") from error
        raise ValueError("请先退出应用，再备份引擎会话记录")
    if not (data / "lobuddy.db").is_file():
        raise ValueError("源数据库不存在")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".lobuddy-backup-", dir=destination.parent
    ) as directory:
        stage = Path(directory) / "snapshot"
        (stage / "data").mkdir(parents=True, mode=0o700)
        (stage / "workspace").mkdir(mode=0o700)
        # SQLite's online backup includes WAL changes and produces a consistent snapshot.
        source = sqlite3.connect(f"{(data / 'lobuddy.db').as_uri()}?mode=ro", uri=True)
        target = sqlite3.connect(stage / "data/lobuddy.db")
        try:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("数据库备份完整性校验失败")
        finally:
            target.close()
            source.close()
        (stage / "data/lobuddy.db").chmod(0o600)
        for child in data.iterdir():
            if child.name not in {
                "lobuddy.db",
                "lobuddy.db-wal",
                "lobuddy.db-shm",
                "backups",
            }:
                _copy(child, stage / "data" / child.name)
        for name in ("skills", "memory", "USER.md", "SOUL.md", "SYSTEM.md", "AGENTS.md"):
            if (workspace / name).exists():
                _copy(workspace / name, stage / "workspace" / name)
        manifest = BackupManifest(
            identity=uuid.uuid4().hex,
            source_data=str(data),
            source_workspace=str(workspace),
            created_at=datetime.now().isoformat(),
            files={
                str(path.relative_to(stage)): _hash(path)
                for path in stage.rglob("*")
                if path.is_file()
            },
        )
        (stage / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        (stage / "manifest.json").chmod(0o600)
        os.replace(stage, destination)
        return manifest


def verify_backup(backup: Path) -> BackupManifest:
    manifest = BackupManifest.model_validate_json(
        (backup / "manifest.json").read_text(encoding="utf-8")
    )
    if manifest.format != 1:
        raise ValueError("不支持的备份格式")
    if "data/lobuddy.db" not in manifest.files:
        raise ValueError("备份缺少数据库")
    expected = set(manifest.files)
    actual = {
        str(path.relative_to(backup))
        for folder in ("data", "workspace")
        for path in (backup / folder).rglob("*")
        if path.is_file()
    }
    if expected != actual:
        raise ValueError("备份文件清单不匹配")
    for name, digest in manifest.files.items():
        path = backup / name
        if (
            Path(name).is_absolute()
            or ".." in Path(name).parts
            or not path.resolve().is_relative_to(backup.resolve())
        ):
            raise ValueError("备份路径无效")
        if path.is_symlink() or _hash(path) != digest:
            raise ValueError("备份内容校验失败")
    return manifest


def restore_snapshot(backup: Path, destination: Path) -> None:
    """Restore exact pre-upgrade bytes to a fresh folder; never alter the source backup."""
    verify_backup(backup)
    _validate_destination(destination, (backup,))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".lobuddy-restore-", dir=destination.parent
    ) as directory:
        stage = Path(directory) / "restored"
        _copy(backup, stage)
        os.replace(stage, destination)


def import_backup(backup: Path, destination: Path) -> dict[str, str | bool]:
    manifest = verify_backup(backup)
    destination = destination.absolute()
    if destination.exists():
        marker = destination / "import.json"
        if (
            marker.is_file()
            and json.loads(marker.read_text()).get("backup_id") == manifest.identity
        ):
            existing_db = destination / "data/lobuddy.db"
            if not existing_db.is_file():
                raise ValueError("导入标记存在但数据库缺失")
            with sqlite3.connect(f"{existing_db.as_uri()}?mode=ro", uri=True) as conn:
                found = conn.execute(
                    "SELECT 1 FROM migration_record WHERE migration_id=?", (manifest.identity,)
                ).fetchone()
                if not found:
                    raise ValueError("导入标记与数据库不一致")
            return {
                "imported": False,
                "data_dir": str(destination / "data"),
                "workspace": str(destination / "workspace"),
            }
        raise ValueError("目标目录已有其他资料，不进行合并或覆盖")
    _validate_destination(destination, (backup,))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".lobuddy-import-", dir=destination.parent
    ) as directory:
        stage = Path(directory) / "imported"
        _copy(backup / "data", stage / "data")
        _copy(backup / "workspace", stage / "workspace")
        settings = Settings(
            llm_api_key="", data_dir=stage / "data", workspace_path=stage / "workspace"
        )
        db = Database(settings)
        db.init_database(allow_desktop=True)
        ServiceRepository(db)
        migrate_desktop(db)
        with db.transaction() as conn:
            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "skill_record" in tables:
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(skill_record)")}
                if "content" not in columns:
                    conn.execute(
                        "ALTER TABLE skill_record ADD COLUMN content TEXT NOT NULL DEFAULT ''"
                    )
                for row in conn.execute("SELECT id,name,path,content FROM skill_record").fetchall():
                    old_path = Path(row["path"])
                    if not old_path.is_absolute():
                        old_path = Path(manifest.source_workspace).parent / old_path
                    if not old_path.resolve().is_relative_to(
                        Path(manifest.source_workspace).resolve()
                    ):
                        raise ValueError("旧技能路径超出原工作区，需先核实")
                    relative = old_path.resolve().relative_to(
                        Path(manifest.source_workspace).resolve()
                    )
                    if not relative.parts or relative.parts[0] != "skills":
                        raise ValueError("旧技能路径不属于技能目录")
                    source = stage / "workspace" / relative
                    content = row["content"]
                    if not content and source.is_file():
                        if source.stat().st_size > 256000:
                            raise ValueError("技能正文超过迁移上限")
                        content = source.read_text(encoding="utf-8")
                    conn.execute(
                        "UPDATE skill_record SET path=?,content=? WHERE id=?",
                        (str(destination / "workspace" / relative), content, row["id"]),
                    )
            conn.execute(
                "INSERT INTO migration_record VALUES (?, ?, ?)",
                (
                    manifest.identity,
                    json.dumps({"backup": str(backup.resolve()), "kind": "legacy_import"}),
                    datetime.now().isoformat(),
                ),
            )
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("迁移后数据库完整性校验失败")
        appearance = stage / "data/pet_appearance.json"
        if appearance.exists():
            value = json.loads(appearance.read_text(encoding="utf-8"))
            asset = value.get("custom_asset_path")
            if asset:
                source_asset = Path(asset)
                if not source_asset.is_absolute():
                    source_asset = Path(manifest.source_data).parent / source_asset
                if source_asset.resolve().is_relative_to(Path(manifest.source_data).resolve()):
                    relative = source_asset.resolve().relative_to(
                        Path(manifest.source_data).resolve()
                    )
                    value["custom_asset_path"] = str(destination / "data" / relative)
                else:
                    raise ValueError("外观资源不在备份数据目录内，需先复制资源")
            appearance.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        (stage / "import.json").write_text(
            json.dumps({"backup_id": manifest.identity}), encoding="utf-8"
        )
        (stage / "import.json").chmod(0o600)
        os.replace(stage, destination)
    return {
        "imported": True,
        "data_dir": str(destination / "data"),
        "workspace": str(destination / "workspace"),
    }
