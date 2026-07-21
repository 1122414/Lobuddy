"""Tests for SQLite migration system."""

import sqlite3

import pytest

from core.storage.migrations import CURRENT_SCHEMA_VERSION, Migration, MigrationRunner
from core.storage.migrations.v001_initial import V001Initial


def _make_runner(db_path: str) -> MigrationRunner:
    runner = MigrationRunner(db_path)
    runner.register(V001Initial())
    return runner


class BrokenMigration:
    version = 2
    name = "broken"

    def up(self, conn):
        conn.execute("CREATE TABLE broken_table (id TEXT)")
        raise RuntimeError("intentional failure")

    def down(self, conn):
        conn.execute("DROP TABLE IF EXISTS broken_table")


class TestMigrationRunner:
    def test_fresh_database_initializes(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        runner = _make_runner(db_path)
        version = runner.migrate()
        assert version == CURRENT_SCHEMA_VERSION

        with sqlite3.connect(db_path) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = [r[0] for r in tables]
            assert "pet_state" in table_names
            assert "task_record" in table_names
            assert "task_result" in table_names
            assert "hitl_approval_log" in table_names

    def test_idempotent_reinit(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        runner = _make_runner(db_path)
        v1 = runner.migrate()
        v2 = runner.migrate()
        assert v1 == CURRENT_SCHEMA_VERSION
        assert v2 == CURRENT_SCHEMA_VERSION

    def test_user_version_upgrade(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
        conn.close()

        runner = _make_runner(db_path)
        assert runner.get_current_version() == 0
        version = runner.migrate()
        assert version == CURRENT_SCHEMA_VERSION
        assert runner.get_current_version() == CURRENT_SCHEMA_VERSION

    def test_migration_rollback_on_failure(self, tmp_path):
        class FailingMigration:
            version = 999
            name = "failing"

            def up(self, conn):
                conn.execute("CREATE TABLE should_not_exist (id)")
                raise RuntimeError("simulated failure")

            def down(self, conn):
                pass

        db_path = str(tmp_path / "test.db")
        runner = MigrationRunner(db_path)
        runner.register(FailingMigration())

        with pytest.raises(RuntimeError, match="simulated failure"):
            runner.migrate()

        with sqlite3.connect(db_path) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [r[0] for r in tables]
            assert "should_not_exist" not in table_names
            assert runner.get_current_version() == 0

    def test_unused_migrations_skipped(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        runner = _make_runner(db_path)
        runner.migrate()
        assert runner.get_current_version() == CURRENT_SCHEMA_VERSION

        runner2 = _make_runner(db_path)
        result = runner2.migrate()
        assert result == CURRENT_SCHEMA_VERSION

    def test_old_version_database_migrates(self, tmp_path):
        """P0-F3: 模拟旧版本数据库，验证迁移能正确升级schema。"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        # Simulate an old schema with core tables but missing newer ones
        # Tables must match V001 schema so CREATE INDEX does not fail
        conn.execute("""
            CREATE TABLE pet_state (
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
            )
        """)
        conn.execute("""
            CREATE TABLE task_record (
                id TEXT PRIMARY KEY,
                input_text TEXT NOT NULL,
                task_type TEXT NOT NULL DEFAULT 'general',
                status TEXT NOT NULL DEFAULT 'created',
                difficulty TEXT NOT NULL DEFAULT 'simple',
                reward_exp INTEGER NOT NULL DEFAULT 5,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE task_result (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL UNIQUE,
                success INTEGER NOT NULL DEFAULT 0,
                raw_result TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                error_message TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
        conn.close()

        runner = _make_runner(db_path)
        version = runner.migrate()
        assert version == CURRENT_SCHEMA_VERSION

        with sqlite3.connect(db_path) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = [r[0] for r in tables]
            assert "hitl_approval_log" in table_names
            assert "unlocked_abilities" in table_names
            assert "app_settings" in table_names

    def test_repeated_migration_is_idempotent(self, tmp_path):
        """P0-F3: 多次重复运行migration不应出错或改变版本。"""
        db_path = str(tmp_path / "test.db")
        runner = _make_runner(db_path)
        for _ in range(5):
            version = runner.migrate()
            assert version == CURRENT_SCHEMA_VERSION

    def test_migration_failure_rollback(self, tmp_path):
        """P0-F3: 验证失败的migration会正确回滚且版本不变。"""
        class BrokenMigration:
            version = 1
            name = "broken"

            def up(self, conn):
                conn.execute("CREATE TABLE broken_table (id TEXT)")
                raise RuntimeError("intentional failure")

            def down(self, conn):
                conn.execute("DROP TABLE IF EXISTS broken_table")

        db_path = str(tmp_path / "test.db")
        runner = MigrationRunner(db_path)
        runner.register(BrokenMigration())

        with pytest.raises(RuntimeError, match="intentional failure"):
            runner.migrate()

        with sqlite3.connect(db_path) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [r[0] for r in tables]
            assert "broken_table" not in table_names
            assert runner.get_current_version() == 0


class TestOldVersionMigration:
    """Simulate an old-version database and verify migration adds missing columns."""

    def test_old_version_database_migrates(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test_old.db")

        # Simulate old DB at version 1 with pet_state missing several columns
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA user_version = 1")
        conn.executescript("""
            CREATE TABLE pet_state (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT 'Lobuddy',
                level INTEGER NOT NULL DEFAULT 1,
                exp INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE task_record (
                id TEXT PRIMARY KEY,
                input_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                created_at TEXT NOT NULL
            );
        """)
        conn.commit()
        conn.close()

        # V002: adds columns that were missing from the old schema
        class V002AddPetColumns(Migration):
            version = 2
            name = "add-missing-pet-columns"

            def up(self, conn):
                conn.execute(
                    "ALTER TABLE pet_state ADD COLUMN evolution_stage "
                    "INTEGER NOT NULL DEFAULT 1"
                )
                conn.execute(
                    "ALTER TABLE pet_state ADD COLUMN mood "
                    "TEXT NOT NULL DEFAULT 'happy'"
                )
                conn.execute(
                    "ALTER TABLE pet_state ADD COLUMN skin "
                    "TEXT NOT NULL DEFAULT 'default'"
                )
                conn.execute("ALTER TABLE pet_state ADD COLUMN personality_json TEXT")

            def down(self, conn):
                pass

        import core.storage.migrations as _mig
        monkeypatch.setattr(_mig, "CURRENT_SCHEMA_VERSION", 2)

        try:
            runner = MigrationRunner(db_path)
            runner.register(V002AddPetColumns())
            version = runner.migrate()
            assert version == 2

            with sqlite3.connect(db_path) as conn:
                info = conn.execute("PRAGMA table_info(pet_state)").fetchall()
                col_names = [r[1] for r in info]
                assert "evolution_stage" in col_names
                assert "mood" in col_names
                assert "skin" in col_names
                assert "personality_json" in col_names
                assert conn.execute("PRAGMA user_version").fetchone()[0] == 2

                # Existing data is preserved
                assert conn.execute("SELECT COUNT(*) FROM pet_state").fetchone()[0] == 0
        finally:
            monkeypatch.undo()
