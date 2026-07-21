"""Real Qt coverage for explainable skill evaluation evidence."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from core.config import Settings
from core.models.pet import TaskRecord, TaskResult, TaskStatus
from core.skills.skill_manager import SkillManager
from core.skills.skill_schema import CandidateSource, SkillCandidate
from core.storage.db import Database
from core.storage.execution_trace_repository import ExecutionTraceRepository
from core.storage.task_repo import TaskRepository
from ui.settings_58_tab import Settings58Tab
from ui.skill_lab_panel import SkillLabPanel


def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_skill_lab_shows_score_permissions_and_blocks_failed_proposal(
    tmp_path: Path,
) -> None:
    app = _qapp()
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        skill_archive_dir=tmp_path / "archive",
    )
    database = Database(settings)
    database.init_database()
    manager = SkillManager(settings, database)
    manager.create_candidate(
        SkillCandidate(
            id="unsafe-proposal",
            title="危险提案",
            rationale="用于验证阻断状态",
            proposed_name="unsafe-proposal",
            proposed_content=(
                "---\nname: unsafe-proposal\ndescription: Unsafe\n---\n\n"
                "# Unsafe\n\n## When to use\n\n"
                "Use this skill when the user asks.\n\n"
                "## Workflow\n\n1. Inspect.\n2. Run `shell`.\n"
            ),
            confidence=0.9,
            evidence={
                "tools": ["read_file", "shell"],
                "privacy_checked": True,
            },
        )
    )

    panel = SkillLabPanel(manager, settings)
    panel.show()
    app.processEvents()

    labels = panel.findChildren(QLabel)
    assert any("隔离评测" in label.text() and "/100" in label.text() for label in labels)
    assert any(
        label.property("permission_summary") and "系统命令或电脑控制" in label.text() for label in labels
    )
    approve = next(button for button in panel.findChildren(QPushButton) if button.text() == "批准并启用")
    assert approve.isEnabled() is False
    assert "受限行为模拟" in approve.toolTip()
    assert panel.grab().width() >= 720
    assert panel.grab().height() >= 560

    panel.close()
    app.processEvents()


def test_skill_evaluation_settings_are_user_visible(tmp_path: Path) -> None:
    _qapp()
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        skill_evaluation_enabled=True,
        skill_evaluation_min_score=82,
    )

    tab = Settings58Tab(settings)

    assert tab._skill_evaluation_enabled.isChecked() is True
    assert tab._skill_evaluation_score_spin.value() == 82
    assert "批准前始终需要通过" in tab._skill_evaluation_enabled.toolTip()
    tab.close()


def test_skill_lab_explains_and_refreshes_task_provenance(
    tmp_path: Path,
) -> None:
    app = _qapp()
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        skill_archive_dir=tmp_path / "archive",
    )
    database = Database(settings)
    database.init_database()
    manager = SkillManager(settings, database)
    candidate = SkillCandidate(
        id="provenance-proposal",
        title="可核验报告流程",
        rationale="来自成功任务的待审流程",
        proposed_name="verified-report",
        proposed_content=(
            "---\nname: verified-report\ndescription: Verified report\n---\n\n"
            "# Verified report\n\n## When to use\n\n"
            "Use this skill when the user asks for a verified report.\n\n"
            "## Workflow\n\n1. Use `read_file` to inspect inputs.\n"
            "2. Use `write_file` to save the report.\n"
            "3. Verify the saved report.\n\n"
            "## Safety\n\n"
            "Stop and ask the user when a tool is refused.\n"
        ),
        source_session_id="session-proof",
        source_task_id="task-proof",
        source_kind=CandidateSource.SUCCESSFUL_TASK,
        confidence=0.9,
        evidence={
            "source": "successful_task",
            "tools": ["read_file", "write_file"],
            "privacy_checked": True,
        },
    )
    manager.create_candidate(candidate)

    panel = SkillLabPanel(manager, settings)
    panel.show()
    app.processEvents()
    labels = panel.findChildren(QLabel)
    assert any(label.property("provenance_badge") and label.text() == "来源待核验" for label in labels)
    approve = next(button for button in panel.findChildren(QPushButton) if button.text() == "批准并启用")
    assert approve.isEnabled() is False
    assert "来源 Task Run" in approve.toolTip()

    tasks = TaskRepository(database)
    tasks.create_task(
        TaskRecord(
            id="task-proof",
            input_text="private task input",
            status=TaskStatus.SUCCESS,
            session_id="session-proof",
        )
    )
    tasks.save_task_result(TaskResult(task_id="task-proof", success=True, summary="completed"))
    traces = ExecutionTraceRepository(database)
    for tool in ("read_file", "write_file"):
        traces.record(
            session_id="task-proof",
            intent="workspace_task",
            tool_name=tool,
            arguments={},
            status="completed",
        )
    manager.evaluate_candidate(candidate.id)
    panel._load_all()
    app.processEvents()

    labels = panel.findChildren(QLabel)
    assert any(label.property("provenance_badge") and label.text() == "来源已核验" for label in labels)
    assert any(
        label.property("provenance_summary") and "read_file、write_file" in label.text()
        for label in labels
    )
    assert any(label.property("behavior_badge") and "2 场景" in label.text() for label in labels)
    assert any(label.property("behavior_summary") and "真实副作用 0" in label.text() for label in labels)
    assert any(
        button.text() == "批准并启用" and button.isEnabled()
        for button in panel.findChildren(QPushButton)
    )

    revised = manager.update_candidate_content(
        candidate.id,
        candidate.proposed_content.replace(
            "Verify the saved report.",
            "Validate the saved report against the request.",
        ),
    )
    assert revised is not None
    panel._load_all()
    app.processEvents()

    labels = panel.findChildren(QLabel)
    assert any(
        label.property("candidate_revision_badge") and label.text() == "提案 v2" for label in labels
    )
    assert any(
        label.property("candidate_diff_summary") and "+1 / -1" in label.text() for label in labels
    )

    panel.close()
    app.processEvents()
