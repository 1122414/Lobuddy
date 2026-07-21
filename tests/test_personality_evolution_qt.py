"""Real Qt regressions for user-governed Personality Evolution history."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox, QProgressBar

from core.config import Settings
from core.models.pet import TaskDifficulty, TaskRecord
from core.personality.evolution import PersonalityEvolution
from core.personality.evolution_models import PersonalityEvolutionKind
from core.storage import db as db_module
from core.storage.ability_repo import AbilityRepository
from core.storage.db import Database
from core.storage.personality_evolution_repo import PersonalityEvolutionRepository
from core.storage.pet_repo import PetRepository
from ui.personality_evolution_dialog import PersonalityEvolutionDialog


def _ensure_qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_personality_history_renders_versions_and_restores_append_only(
    tmp_path,
    monkeypatch,
) -> None:
    app = _ensure_qapp()
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
    )
    database = Database(settings)
    database.init_database()
    db_module._db = database
    try:
        pets = PetRepository(database)
        revisions = PersonalityEvolutionRepository(database)
        evolution = PersonalityEvolution(pets=pets, revisions=revisions)
        pet = pets.get_or_create_pet()
        pet.level = 5
        pet.exp = 28
        pets.save_pet(pet)
        AbilityRepository(database).save_unlocked_ability("advanced_chat")
        evolution.evolve_from_task(
            TaskRecord(
                id="qt-growth",
                input_text="设计并优化一个 Python 应用",
                difficulty=TaskDifficulty.COMPLEX,
            )
        )
        dialog = PersonalityEvolutionDialog(evolution)
        dialog.show()
        app.processEvents()

        assert dialog.windowTitle() == "Lobuddy 的成长版本"
        assert dialog._table.rowCount() == 2
        assert dialog._version_chip.text() == "2 个可追溯版本"
        assert len(dialog.findChildren(QProgressBar)) == 5
        assert dialog._current_version is not None
        assert dialog._current_version.kind == PersonalityEvolutionKind.TASK_COMPLETED
        assert not dialog._restore_btn.isEnabled()
        assert dialog.grab().width() >= 900
        assert dialog.grab().height() >= 620

        baseline_row = 1
        baseline = dialog._table.item(baseline_row, 0).data(Qt.ItemDataRole.UserRole)
        dialog._table.selectRow(baseline_row)
        app.processEvents()
        assert baseline.kind == PersonalityEvolutionKind.BASELINE
        assert dialog._restore_btn.isEnabled()

        monkeypatch.setattr(
            QInputDialog,
            "getText",
            staticmethod(
                lambda *_args, **_kwargs: (
                    "我希望回到版本历史开始时的伙伴倾向",
                    True,
                )
            ),
        )
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes),
        )
        monkeypatch.setattr(
            QMessageBox,
            "information",
            staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok),
        )
        restored: list[str] = []
        dialog.restored.connect(restored.append)
        dialog._restore_btn.click()
        app.processEvents()

        assert len(restored) == 1
        assert dialog._table.rowCount() == 3
        assert dialog._current_version is not None
        assert dialog._current_version.kind == PersonalityEvolutionKind.RESTORED
        assert pets.get_or_create_pet().level == 5
        assert pets.get_or_create_pet().exp == 28
        assert AbilityRepository(database).is_unlocked("advanced_chat") is True
        dialog.close()
    finally:
        db_module._db = None
