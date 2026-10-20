"""Start and stop the real legacy UI with disposable data and no external hotkeys.

Run after installing the project: python scripts/smoke_legacy_startup.py
This checks composition and shutdown, not model responses or visual appearance.
"""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def main() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from app.bootstrap import health_check
    from app.main import run_ui_mode
    from core.config import Settings
    from core.storage.settings_repo import SettingsRepository

    class SmokeApplication(QApplication):
        def __init__(self, arguments: list[str]) -> None:
            super().__init__(arguments)
            QTimer.singleShot(500, self.quit)

    original_directory = Path.cwd()
    try:
        with TemporaryDirectory(prefix="lobuddy-startup-") as directory:
            root = Path(directory)
            os.chdir(root)
            settings = Settings(
                llm_api_key="offline-smoke-key",
                llm_base_url="http://127.0.0.1:1/v1",
                data_dir=root / "data",
                logs_dir=root / "logs",
                workspace_path=root / "workspace",
                nanobot_config_path=root / "nanobot.json",
                skill_archive_dir=root / "archive",
                memory_enable_migration=False,
                exit_analysis_enabled=False,
            )
            results = asyncio.run(health_check(settings))
            assert not results["errors"], results["errors"]
            SettingsRepository().set_setting("first_run_completed", "true")
            with (
                patch("app.main.QApplication", SmokeApplication),
                patch("ui.hotkey_manager.HotkeyManager.start"),
            ):
                try:
                    run_ui_mode(settings)
                except SystemExit as exc:
                    assert exc.code == 0, exc.code
            print("PASS: real Qt UI composed, event loop ran, worker shut down; no model call")
    finally:
        os.chdir(original_directory)


if __name__ == "__main__":
    main()
