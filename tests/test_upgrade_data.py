"""Backup, migration idempotency, rollback compatibility and credential failure boundaries."""

from pathlib import Path

import pytest

from core.config import Settings
from core.config.credentials import migrate_credentials
from core.memory.memory_schema import MemoryItem, MemoryType
from core.service.knowledge import KnowledgeService
from core.service.settings_service import SettingsPatch, SettingsService
from core.skills.skill_schema import SkillRecord, SkillStatus
from core.storage.db import Database
from core.storage.keychain import KeychainError
from core.storage.upgrade_backup import (
    create_backup,
    import_backup,
    restore_snapshot,
    verify_backup,
)


@pytest.fixture
def legacy(tmp_path: Path) -> tuple[Settings, Database]:
    settings = Settings(
        llm_api_key="fixture",
        data_dir=tmp_path / "old/data",
        workspace_path=tmp_path / "old/workspace",
    )
    settings.workspace_path.mkdir(parents=True)
    db = Database(settings)
    db.init_database()
    knowledge = KnowledgeService(settings, db)
    knowledge.gateway.save_manual(
        MemoryItem(id="old-memory", memory_type=MemoryType.USER_PROFILE, content="白桃茶")
    )
    knowledge.skills.create_skill(
        SkillRecord(
            id="old-skill", name="tea", path="", description="tea", status=SkillStatus.ACTIVE
        ),
        "original skill",
    )
    (settings.data_dir / "user_assets").mkdir()
    (settings.data_dir / "user_assets/test.txt").write_text("asset")
    return settings, db


class TestBackupMigration:
    def test_engine_session_backup_requires_stopped_runtime(
        self, legacy: tuple[Settings, Database], tmp_path: Path
    ) -> None:
        import json
        import os

        settings, _ = legacy
        home = settings.data_dir / "dsh-home"
        (home / "bridge-test").mkdir(parents=True)
        ready = home / "bridge-test/ready.json"
        ready.write_text(json.dumps({"pid": os.getpid()}))
        with pytest.raises(ValueError, match="退出应用"):
            create_backup(settings.data_dir, settings.workspace_path, tmp_path / "running")
        ready.unlink()
        (home / "synthetic-session.jsonl").write_text('{"type":"synthetic"}\n')
        manifest = create_backup(settings.data_dir, settings.workspace_path, tmp_path / "stopped")
        assert "data/dsh-home/synthetic-session.jsonl" in manifest.files

    def test_backup_import_twice_restore_and_ids(
        self, legacy: tuple[Settings, Database], tmp_path: Path
    ) -> None:
        settings, db = legacy
        before = db.db_path.read_bytes()
        backup, target = tmp_path / "backup", tmp_path / "new"
        manifest = create_backup(settings.data_dir, settings.workspace_path, backup)
        assert verify_backup(backup).identity == manifest.identity
        assert import_backup(backup, target)["imported"] is True
        assert import_backup(backup, target)["imported"] is False
        assert db.db_path.read_bytes() == before
        upgraded_settings = settings.model_copy(
            update={"data_dir": target / "data", "workspace_path": target / "workspace"}
        )
        upgraded_db = Database(upgraded_settings)
        with pytest.raises(RuntimeError, match="已升级"):
            upgraded_db.init_database()
        upgraded_db.init_database(allow_desktop=True)
        knowledge = KnowledgeService(upgraded_settings, upgraded_db)
        assert knowledge.memory.get_memory("old-memory") is not None
        skill = knowledge.skills.get_skill("old-skill")
        assert skill is not None and skill.path == str(target / "workspace/skills/tea/SKILL.md")
        assert knowledge.skills.get_content(skill.id) == "original skill"
        assert knowledge.skills.disable_skill(skill.id)
        assert knowledge.skills.enable_skill(skill.id)
        restored = tmp_path / "restored"
        restore_snapshot(backup, restored)
        assert (restored / "data/lobuddy.db").read_bytes() == (
            backup / "data/lobuddy.db"
        ).read_bytes()
        old_settings = settings.model_copy(update={"data_dir": restored / "data"})
        Database(old_settings).init_database()

    def test_corruption_and_symlink_fail_closed(
        self, legacy: tuple[Settings, Database], tmp_path: Path
    ) -> None:
        settings, _ = legacy
        backup = tmp_path / "backup"
        create_backup(settings.data_dir, settings.workspace_path, backup)
        (backup / "workspace/skills/tea/SKILL.md").write_text("tampered")
        with pytest.raises(ValueError, match="校验失败"):
            import_backup(backup, tmp_path / "new")
        assert not (tmp_path / "new").exists()
        (settings.data_dir / "outside").symlink_to(tmp_path / "outside.txt")
        with pytest.raises(ValueError, match="符号链接"):
            create_backup(settings.data_dir, settings.workspace_path, tmp_path / "second")
        assert not (tmp_path / "second").exists()

    def test_failed_import_keeps_source_and_no_partial_target(
        self, legacy: tuple[Settings, Database], tmp_path: Path
    ) -> None:
        settings, db = legacy
        with db.transaction() as conn:
            conn.execute("UPDATE skill_record SET path='/outside/SKILL.md'")
        backup = tmp_path / "backup"
        create_backup(settings.data_dir, settings.workspace_path, backup)
        with pytest.raises(ValueError, match="超出原工作区"):
            import_backup(backup, tmp_path / "new")
        assert not (tmp_path / "new").exists()
        assert verify_backup(backup)


class Store:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.values: dict[str, str] = {}

    def get(self, account: str) -> str | None:
        return self.values.get(account)

    def set(self, account: str, secret: str) -> None:
        if self.fail:
            raise KeychainError("injected")
        self.values[account] = secret


class TestCredentials:
    def test_failure_retains_original_and_success_removes_all_multiline_binding(
        self, legacy: tuple[Settings, Database], tmp_path: Path
    ) -> None:
        _, db = legacy
        env = tmp_path / ".env"
        original = 'LLM_API_KEY="synthetic\nmultiline"\nLLM_MODEL=test\n# keep comment\n'
        env.write_text(original)
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO app_settings VALUES ('fish_api_key','synthetic-fish',datetime('now'))"
            )
        with pytest.raises(KeychainError):
            migrate_credentials(db, env, Store(fail=True))
        assert env.read_text() == original
        with db.get_connection() as conn:
            assert (
                conn.execute("SELECT value FROM app_settings WHERE key='fish_api_key'").fetchone()[
                    0
                ]
                == "synthetic-fish"
            )
        store = Store()
        assert migrate_credentials(db, env, store) == 2
        assert store.values["llm_api_key"] == "synthetic\nmultiline"
        assert env.read_text() == "LLM_MODEL=test\n# keep comment\n"
        assert migrate_credentials(db, env, store) == 0
        with db.get_connection() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM app_settings WHERE key='fish_api_key'"
                ).fetchone()[0]
                == 0
            )

    def test_renderer_settings_cannot_read_write_secrets(
        self, legacy: tuple[Settings, Database]
    ) -> None:
        settings, db = legacy
        service = SettingsService(settings, db)
        view = service.view()
        assert "llm_api_key" not in view.values
        assert "fixture" not in view.model_dump_json()
        assert view.credentials["llm_api_key"] is True
        with pytest.raises(ValueError):
            service.patch(SettingsPatch(values={"llm_api_key": "new"}))
        with pytest.raises(ValueError):
            service.patch(SettingsPatch(values={"data_dir": "/elsewhere"}))
        changed = service.patch(
            SettingsPatch(values={"pet_name": "小蒂", "execution_max_tool_calls_per_task": 3})
        )
        assert changed.restart_required and changed.values["pet_name"] == "小蒂"
        assert service.settings.pet_name != "小蒂"
