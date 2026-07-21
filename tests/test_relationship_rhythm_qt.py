"""Real Qt regressions for the Relationship Rhythm control surface."""

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QProgressBar

from core.companion.models import (
    CompanionEnergy,
    CompanionMood,
    CompanionSupportMode,
)
from core.companion.runtime import CompanionRuntime
from core.config import Settings
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import MemoryType
from core.memory.memory_service import MemoryService
from core.memory.memory_write_gateway import MemoryWriteGateway
from core.memory.privacy_mode import PrivacyModeManager
from core.relationship.rhythm_service import RelationshipRhythmService
from core.storage import db as db_module
from core.storage.db import Database
from core.storage.pet_repo import PetRepository
from ui.relationship_rhythm_dialog import RelationshipRhythmDialog


def _ensure_qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_relationship_rhythm_renders_governed_evidence_and_navigation(
    tmp_path,
) -> None:
    app = _ensure_qapp()
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
        user_name="",
    )
    database = Database(settings)
    database.init_database()
    db_module._db = database
    try:
        repo = MemoryRepository(database)
        privacy = PrivacyModeManager(settings)
        memory_service = MemoryService(settings, repo=repo, privacy=privacy)
        gateway = MemoryWriteGateway(memory_service, settings, privacy=privacy)
        control = MemoryControlService(
            settings,
            memory_service=memory_service,
            repo=repo,
            gateway=gateway,
        )
        control.remember_manual(
            memory_type=MemoryType.USER_PROFILE,
            title="沟通节奏",
            content="复杂任务先安静执行，授权时再叫我。",
            session_id="daily",
        )
        companion = CompanionRuntime(settings, db=database)
        now = datetime.now()
        companion.submit_check_in(
            CompanionMood.STEADY,
            CompanionEnergy.MEDIUM,
            CompanionSupportMode.FOCUS,
            now=now,
        )
        pets = PetRepository(database)
        pet = pets.get_or_create_pet()
        pet.personality.diligence = 53.6
        pet.personality.interaction_counts["diligence:task_analysis"] = 12
        pets.save_pet(pet)
        rhythm = RelationshipRhythmService(
            control,
            companion,
            pets=pets,
            privacy=privacy,
        )
        dialog = RelationshipRhythmDialog(
            rhythm,
            session_id_provider=lambda: "daily",
        )
        dialog.show()
        app.processEvents()

        assert dialog.windowTitle() == "我们的相处节奏"
        assert dialog.minimumWidth() >= 900
        assert dialog._memory_summary.text() == "有效 1 · 待确认 0"
        assert "还算平稳" in dialog._checkin_label.text()
        assert "陪我专注" in dialog._checkin_label.text()
        assert len(dialog.findChildren(QProgressBar)) == 5
        texts = {label.text() for label in dialog.findChildren(QLabel)}
        assert "沟通节奏" in texts
        assert "你主动留下" in texts
        assert dialog._growth_history_button.text() == "成长版本 · 1"
        assert dialog._snapshot.personality_version_count == 1

        memory_requested: list[bool] = []
        check_in_requested: list[bool] = []
        dialog.memory_requested.connect(lambda: memory_requested.append(True))
        dialog.check_in_requested.connect(lambda: check_in_requested.append(True))
        dialog._memory_button.click()
        dialog._checkin_button.click()
        assert memory_requested == [True]
        assert check_in_requested == [True]
        assert dialog.grab().width() >= 900
        assert dialog.grab().height() >= 680
        dialog.close()
    finally:
        db_module._db = None


def test_relationship_rhythm_exposes_privacy_and_revocable_check_in(
    tmp_path,
    monkeypatch,
) -> None:
    app = _ensure_qapp()
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
        user_name="",
    )
    database = Database(settings)
    database.init_database()
    db_module._db = database
    try:
        repo = MemoryRepository(database)
        privacy = PrivacyModeManager(settings)
        memory_service = MemoryService(settings, repo=repo, privacy=privacy)
        control = MemoryControlService(settings, memory_service=memory_service, repo=repo)
        companion = CompanionRuntime(settings, db=database)
        companion.submit_check_in(
            CompanionMood.TIRED,
            CompanionEnergy.LOW,
            CompanionSupportMode.QUIET,
        )
        privacy.enable_privacy("private")
        rhythm = RelationshipRhythmService(
            control,
            companion,
            pets=PetRepository(database),
            privacy=privacy,
        )
        dialog = RelationshipRhythmDialog(
            rhythm,
            session_id_provider=lambda: "private",
        )
        dialog.show()
        app.processEvents()

        assert dialog._privacy_chip.text() == "隐私会话 · 只查看"
        assert "不会写入新的长期记忆" in dialog._guidance_label.text()
        assert dialog._clear_checkin_button.isVisible()
        monkeypatch.setattr(
            QMessageBox,
            "question",
            staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes),
        )
        dialog._clear_checkin_button.click()
        app.processEvents()
        assert not dialog._clear_checkin_button.isVisible()
        assert companion.active_check_in() is None
        dialog.close()
    finally:
        db_module._db = None
