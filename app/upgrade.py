"""Explicit backup/import/rollback and credential upgrade entry points."""

import argparse
import json
from pathlib import Path

from core.config import Settings
from core.config.credentials import migrate_credentials
from core.storage.db import Database
from core.storage.keychain import MacKeychain
from core.storage.upgrade_backup import (
    create_backup,
    import_backup,
    restore_snapshot,
    verify_backup,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lobuddy 备份、迁移与恢复；目标目录必须为空")
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--data-dir", type=Path, required=True)
    backup.add_argument("--workspace", type=Path, required=True)
    backup.add_argument("--destination", type=Path, required=True)
    for name in ("import", "restore"):
        child = commands.add_parser(name)
        child.add_argument("--backup", type=Path, required=True)
        child.add_argument("--destination", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--backup", type=Path, required=True)
    credentials = commands.add_parser("credentials")
    credentials.add_argument("--data-dir", type=Path, required=True)
    credentials.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "backup":
        manifest = create_backup(args.data_dir, args.workspace, args.destination)
        print(json.dumps({"backup_id": manifest.identity, "files": len(manifest.files)}))
    elif args.command == "import":
        print(json.dumps(import_backup(args.backup, args.destination), ensure_ascii=False))
    elif args.command == "restore":
        restore_snapshot(args.backup, args.destination)
        print("已恢复原始快照到新目录。请使用匹配的旧程序和此目录内的数据。")
    elif args.command == "verify":
        manifest = verify_backup(args.backup)
        print(json.dumps({"verified": True, "backup_id": manifest.identity}))
    elif args.command == "credentials":
        db = Database(Settings(llm_api_key="", data_dir=args.data_dir))
        db.init_database(allow_desktop=True)
        count = migrate_credentials(db, args.env_file, MacKeychain())
        print(json.dumps({"migrated_credentials": count, "storage": "macOS Keychain"}))


if __name__ == "__main__":
    main()
