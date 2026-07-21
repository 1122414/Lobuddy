"""v001: Initial baseline schema.

Captures the current state of all tables as CREATE TABLE IF NOT EXISTS.
This is the bootstrap baseline — idempotent, safe to run multiple times.
NOTE: chat/memory/skill/execution_trace tables are intentionally deferred
to V002 — they are created ad-hoc by their respective repo/service classes.
"""

import sqlite3

from core.storage.migrations import Migration


class V001Initial(Migration):
    version = 1
    name = "initial-baseline"

    def up(self, conn: sqlite3.Connection) -> None:
        conn.executescript(V001_SQL)

    def down(self, conn: sqlite3.Connection) -> None:
        tables = [
            "hitl_approval_log",
            "unlocked_abilities",
            "user_themes",
            "app_settings",
            "task_result",
            "task_record",
            "pet_state",
        ]
        for table in tables:
            conn.execute(f"DROP TABLE IF EXISTS {table}")


V001_SQL = """
CREATE TABLE IF NOT EXISTS pet_state (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT 'Lobuddy',
    level INTEGER NOT NULL DEFAULT 1,
    exp INTEGER NOT NULL DEFAULT 0,
    evolution_stage INTEGER NOT NULL DEFAULT 1,
    mood TEXT NOT NULL DEFAULT 'happy',
    skin TEXT NOT NULL DEFAULT 'default',
    personality_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_record (
    id TEXT PRIMARY KEY,
    input_text TEXT NOT NULL,
    task_type TEXT NOT NULL DEFAULT 'general',
    status TEXT NOT NULL DEFAULT 'created',
    difficulty TEXT NOT NULL DEFAULT 'simple',
    reward_exp INTEGER NOT NULL DEFAULT 5,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS task_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    success INTEGER NOT NULL DEFAULT 0,
    raw_result TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    error_message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES task_record(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_themes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    colors_json TEXT NOT NULL,
    source_image_path TEXT,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS unlocked_abilities (
    ability_id TEXT PRIMARY KEY,
    unlocked_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_status ON task_record(status);
CREATE INDEX IF NOT EXISTS idx_task_created ON task_record(created_at);

CREATE TABLE IF NOT EXISTS hitl_approval_log (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    command_hash TEXT NOT NULL,
    command_preview TEXT NOT NULL,
    working_dir TEXT,
    affected_paths_json TEXT NOT NULL,
    risk_tags_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    decision TEXT NOT NULL,
    decision_reason TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
"""
