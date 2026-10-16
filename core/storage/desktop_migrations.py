"""Atomic, versioned additions for the DSH desktop database."""

from core.storage.db import Database

DESKTOP_SCHEMA_VERSION = 2


def migrate_desktop(db: Database) -> None:
    with db.transaction() as conn:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version > DESKTOP_SCHEMA_VERSION:
            raise RuntimeError("数据库版本比当前程序新，请使用匹配版本或恢复备份")
        if version >= DESKTOP_SCHEMA_VERSION:
            return
        conn.execute("""CREATE TABLE IF NOT EXISTS turn_settlement (
            task_id TEXT PRIMARY KEY, turn_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL, progress_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS skill_use (
            task_id TEXT NOT NULL, skill_id TEXT NOT NULL,
            PRIMARY KEY(task_id, skill_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS model_usage (
            turn_id TEXT NOT NULL, sequence INTEGER NOT NULL,
            session_id TEXT NOT NULL, input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL, cached_tokens INTEGER NOT NULL,
            created_at TEXT NOT NULL, PRIMARY KEY(turn_id, sequence))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS migration_record (
            migration_id TEXT PRIMARY KEY, detail_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
        conn.execute("PRAGMA user_version=2")
        conn.execute("INSERT OR IGNORE INTO service_schema_version VALUES (2)")
