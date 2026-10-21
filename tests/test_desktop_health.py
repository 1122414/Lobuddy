"""P9 readiness must inspect the new runtime without bootstrapping or exposing credentials."""

import asyncio
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from core.config import Settings
from core.service.health import inspect_desktop


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "application"
    plugin = root / "bridge/dsh/dist/index.js"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("// synthetic built entry")
    settings = Settings(
        llm_api_key="synthetic-secret",
        llm_model="synthetic-model",
        _env_file=None,
        data_dir=tmp_path / "data",
        workspace_path=tmp_path / "workspace",
    )
    return root, settings


class TestDesktopHealth:
    def test_first_launch_check_never_creates_data_or_workspace(self, setup):
        root, settings = setup
        report = inspect_desktop(settings, root)
        assert report.ready
        assert not settings.data_dir.exists() and not settings.workspace_path.exists()
        assert "synthetic-secret" not in report.model_dump_json()
        assert not any("nanobot" in item.name or "qt" in item.name for item in report.checks)

    def test_stored_model_settings_are_checked_read_only(self, setup):
        root, settings = setup
        settings.data_dir.mkdir()
        path = settings.data_dir / "lobuddy.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE app_settings(key TEXT,value TEXT)")
        conn.execute("INSERT INTO app_settings VALUES('llm_model','')")
        conn.commit()
        conn.close()
        original = path.read_bytes()
        report = inspect_desktop(settings, root)
        assert not report.ready
        assert (
            next(item for item in report.checks if item.name == "model_configuration").state
            == "unavailable"
        )
        assert path.read_bytes() == original

    def test_corrupt_database_does_not_get_reinitialized(self, setup):
        root, settings = setup
        settings.data_dir.mkdir()
        path = settings.data_dir / "lobuddy.db"
        path.write_bytes(b"not a database")
        assert not inspect_desktop(settings, root).ready
        assert path.read_bytes() == b"not a database"

    def test_missing_plugin_and_wrong_runtime_are_unavailable(self, setup, monkeypatch):
        root, settings = setup
        (root / "bridge/dsh/dist/index.js").unlink()
        monkeypatch.setattr("core.service.health.version", lambda name: "wrong-version")
        failed = {
            item.name
            for item in inspect_desktop(settings, root).checks
            if item.state == "unavailable"
        }
        assert failed == {"plugin_bridge", "dsh_runtime"}

    def test_configuration_exception_does_not_expose_secret(self, monkeypatch, capsys):
        from app.health import check

        def fail():
            raise ValueError("sensitive-credential-in-exception")

        monkeypatch.setattr("app.health.load_settings", fail)
        assert asyncio.run(check()) == 1
        assert "sensitive-credential" not in capsys.readouterr().out

    def test_entry_import_does_not_load_legacy_bootstrap(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import app.health, sys; assert 'app.bootstrap' not in sys.modules; assert not any(k.startswith(('PySide6', 'nanobot')) for k in sys.modules)",
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
