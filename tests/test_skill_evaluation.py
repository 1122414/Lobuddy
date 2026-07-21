"""Skill candidate evaluation, permission, and approval regressions."""

from __future__ import annotations

from pathlib import Path

import core.skills.skill_manager as skill_manager_module
import pytest
from core.config import Settings
from core.models.pet import TaskRecord, TaskResult, TaskStatus
from core.skills.skill_manager import SkillManager
from core.skills.skill_schema import (
    CandidateSource,
    CandidateStatus,
    EvaluationCheckStatus,
    EvaluationStatus,
    SkillCandidate,
    SkillRecord,
)
from core.storage.db import Database
from core.storage.execution_trace_repository import ExecutionTraceRepository
from core.storage.task_repo import TaskRepository


def _manager(tmp_path: Path) -> SkillManager:
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        skill_archive_dir=tmp_path / "archive",
        skill_evaluation_enabled=True,
        skill_evaluation_min_score=75,
    )
    database = Database(settings)
    database.init_database()
    return SkillManager(settings, database)


def _candidate(
    candidate_id: str = "candidate-1",
    *,
    name: str = "weekly-report",
    tools: list[str] | None = None,
    content: str = "",
) -> SkillCandidate:
    proposed_content = content or (
        f"---\nname: {name}\ndescription: Prepare a reviewed weekly report\n"
        "---\n\n"
        "# Weekly report\n\n"
        "## When to use\n\n"
        "Use this skill when the user asks for a weekly report.\n\n"
        "## Workflow\n\n"
        "1. Use `read_file` to collect approved workspace inputs.\n"
        "2. Use `write_file` to save the report in the workspace.\n"
        "3. Verify the output against the user's request.\n\n"
        "## Safety\n\n"
        "Stop and ask the user before a refused or high-impact action.\n"
    )
    return SkillCandidate(
        id=candidate_id,
        title="每周报告流程",
        rationale="来自已成功且经过脱敏的任务",
        proposed_name=name,
        proposed_content=proposed_content,
        confidence=0.8,
        evidence={
            "tools": tools or ["read_file", "write_file"],
            "privacy_checked": True,
            "activation_requires_review": True,
        },
    )


def test_candidate_creation_persists_content_addressed_evaluation(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    candidate = _candidate()

    manager.create_candidate(candidate)
    report = manager.get_latest_candidate_evaluation(
        candidate.id,
        current_content_only=True,
    )

    assert report is not None
    assert report.status == EvaluationStatus.PASSED
    assert report.score == 100
    assert len(report.content_hash) == 64
    assert len(report.checks) == 9
    assert report.permissions.capabilities == [
        "读取工作区",
        "修改工作区",
    ]
    assert report.permissions.requires_confirmation is True
    assert not (tmp_path / "workspace" / "skills" / candidate.proposed_name).exists()
    evaluation_root = tmp_path / "data" / "skill-evaluations"
    assert evaluation_root.exists()
    assert list(evaluation_root.iterdir()) == []


def test_high_risk_permission_and_path_like_name_are_blocked(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    candidate = _candidate(
        name="../escape",
        tools=["read_file", "shell"],
        content=(
            "---\nname: escape\ndescription: Unsafe\n---\n\n"
            "# Unsafe\n\n## When to use\n\n"
            "Use this skill when the user asks.\n\n"
            "## Workflow\n\n1. Inspect input.\n2. Run `shell`.\n"
        ),
    )

    manager.create_candidate(candidate)
    report = manager.get_latest_candidate_evaluation(candidate.id)

    assert report is not None
    assert report.status == EvaluationStatus.FAILED
    failed_keys = {
        check.key for check in report.checks if check.status == EvaluationCheckStatus.FAILED
    }
    assert {"identity", "permissions"} <= failed_keys
    assert manager.approve_candidate(candidate.id) is None
    assert not (tmp_path / "escape").exists()


def test_unknown_tool_is_visible_and_blocks_behavior_approval(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    candidate = _candidate(tools=["read_file", "custom_lookup"])

    manager.create_candidate(candidate)
    report = manager.get_latest_candidate_evaluation(candidate.id)

    assert report is not None
    assert report.status == EvaluationStatus.FAILED
    assert report.score < 100
    assert report.permissions.unknown_tools == ["custom_lookup"]
    permissions = next(check for check in report.checks if check.key == "permissions")
    assert permissions.status == EvaluationCheckStatus.FAILED
    behavior = next(check for check in report.checks if check.key == "behavior_simulation")
    assert behavior.status == EvaluationCheckStatus.FAILED
    assert manager.approve_candidate(candidate.id) is None


def test_successful_task_claim_requires_real_task_and_tool_evidence(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    candidate = _candidate()
    candidate.source_kind = CandidateSource.SUCCESSFUL_TASK
    candidate.source_task_id = "task-proof"
    candidate.source_session_id = "session-proof"
    candidate.evidence["source"] = "successful_task"

    task_repo = TaskRepository(manager.db)
    task_repo.create_task(
        TaskRecord(
            id="task-proof",
            input_text="private source prompt that must not enter provenance",
            status=TaskStatus.SUCCESS,
            session_id="session-proof",
        )
    )
    task_repo.save_task_result(
        TaskResult(
            task_id="task-proof",
            success=True,
            raw_result="private source output that must not enter provenance",
            summary="completed",
        )
    )
    traces = ExecutionTraceRepository(manager.db)
    traces.record(
        session_id="task-proof",
        intent="workspace_task",
        tool_name="read_file",
        arguments={"path": "private-source.txt"},
        status="completed",
    )

    manager.create_candidate(candidate)
    blocked = manager.get_latest_candidate_evaluation(candidate.id)

    assert blocked is not None
    assert blocked.status == EvaluationStatus.FAILED
    assert blocked.provenance.status.value == "unverified"
    assert blocked.provenance.missing_tools == ["write_file"]
    assert manager.approve_candidate(candidate.id) is None

    traces.record(
        session_id="task-proof",
        intent="workspace_task",
        tool_name="write_file",
        arguments={"path": "private-report.md"},
        status="completed",
    )
    verified = manager.evaluate_candidate(candidate.id)

    assert verified is not None
    assert verified.status == EvaluationStatus.PASSED
    assert verified.provenance.status.value == "verified"
    assert verified.provenance.observed_tools == ["read_file", "write_file"]
    serialized = verified.model_dump_json()
    assert "private source prompt" not in serialized
    assert "private source output" not in serialized
    assert "private-source.txt" not in serialized
    assert manager.approve_candidate(candidate.id) is not None


def test_forged_successful_task_claim_fails_closed(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    candidate = _candidate()
    candidate.source_task_id = "missing-task"
    candidate.source_session_id = "session-proof"
    candidate.evidence["source"] = "successful_task"

    manager.create_candidate(candidate)
    assert manager.get_candidate(candidate.id).source_kind == CandidateSource.SUCCESSFUL_TASK
    report = manager.get_latest_candidate_evaluation(candidate.id)

    assert report is not None
    assert report.status == EvaluationStatus.FAILED
    provenance_check = next(check for check in report.checks if check.key == "provenance")
    assert provenance_check.status == EvaluationCheckStatus.FAILED
    assert manager.approve_candidate(candidate.id) is None


def test_disabling_automatic_evaluation_does_not_bypass_approval_gate(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    manager._settings.skill_evaluation_enabled = False
    candidate = _candidate()
    manager.create_candidate(candidate)
    assert manager.get_latest_candidate_evaluation(candidate.id) is None

    created = manager.approve_candidate(candidate.id)

    assert created is not None
    report = manager.get_latest_candidate_evaluation(
        candidate.id,
        current_content_only=True,
    )
    assert report is not None
    assert report.status == EvaluationStatus.PASSED


def test_changed_content_cannot_reuse_stale_passing_report(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    candidate = _candidate()
    manager.create_candidate(candidate)
    assert (
        manager.get_latest_candidate_evaluation(
            candidate.id,
            current_content_only=True,
        ).status
        == EvaluationStatus.PASSED
    )

    with manager.db.transaction() as conn:
        conn.execute(
            """
            UPDATE skill_candidate
            SET proposed_content = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            ("rm -rf /", candidate.id),
        )

    assert (
        manager.get_latest_candidate_evaluation(
            candidate.id,
            current_content_only=True,
        )
        is None
    )
    assert manager.approve_candidate(candidate.id) is None
    latest = manager.get_latest_candidate_evaluation(
        candidate.id,
        current_content_only=True,
    )
    assert latest is not None
    assert latest.status == EvaluationStatus.FAILED


def test_candidate_edits_create_immutable_reviewable_revisions(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    candidate = _candidate()
    manager.create_candidate(candidate)
    original = manager.get_candidate(candidate.id)
    original_report = manager.get_latest_candidate_evaluation(candidate.id)

    assert original is not None
    assert original.revision == 1
    assert original_report is not None
    assert original_report.candidate_revision == 1

    revised_content = original.proposed_content.replace(
        "Verify the output against the user's request.",
        "Validate the saved output against the user's stated request.",
    )
    revised = manager.update_candidate_content(
        candidate.id,
        revised_content,
    )

    assert revised is not None
    assert revised.revision == 2
    revisions = manager.list_candidate_revisions(candidate.id)
    assert [revision.revision for revision in revisions] == [2, 1]
    assert revisions[0].content == revised_content
    assert revisions[1].content == original.proposed_content
    diff = manager.get_candidate_diff(candidate.id)
    assert diff is not None
    assert diff.from_revision == 1
    assert diff.to_revision == 2
    assert diff.added_lines == 1
    assert diff.removed_lines == 1
    assert "Validate the saved output" in diff.unified_diff
    assert "Verify the output" in diff.unified_diff

    latest = manager.get_latest_candidate_evaluation(
        candidate.id,
        current_content_only=True,
    )
    assert latest is not None
    assert latest.candidate_revision == 2
    assert latest.status == EvaluationStatus.PASSED
    created = manager.approve_candidate(candidate.id)
    assert created is not None
    assert created.content == revised_content
    assert manager.update_candidate_content(candidate.id, original.proposed_content) is None


def test_invalid_candidate_revision_is_preserved_but_cannot_be_approved(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    candidate = _candidate()
    manager.create_candidate(candidate)

    revised = manager.update_candidate_content(
        candidate.id,
        "# incomplete proposal",
    )

    assert revised is not None
    assert revised.revision == 2
    assert revised.validation_errors
    report = manager.get_latest_candidate_evaluation(
        candidate.id,
        current_content_only=True,
    )
    assert report is not None
    assert report.candidate_revision == 2
    assert report.status == EvaluationStatus.FAILED
    assert manager.approve_candidate(candidate.id) is None
    diff = manager.get_candidate_diff(candidate.id)
    assert diff is not None
    assert diff.changed is True


def test_candidate_revision_backfill_is_idempotent(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    candidate = _candidate()
    manager.create_candidate(candidate)
    with manager.db.transaction() as conn:
        conn.execute(
            "DELETE FROM skill_candidate_revision WHERE candidate_id = ?",
            (candidate.id,),
        )

    reloaded = SkillManager(manager._settings, manager.db)
    first = reloaded.list_candidate_revisions(candidate.id)
    SkillManager(manager._settings, manager.db)
    second = reloaded.list_candidate_revisions(candidate.id)

    assert len(first) == 1
    assert first[0].revision == 1
    assert first[0].content == candidate.proposed_content
    assert len(second) == 1


def test_approval_rolls_back_database_and_projection_on_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    candidate = _candidate()
    manager.create_candidate(candidate)

    def fail_event(*_args, **_kwargs):
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(manager, "_insert_event", fail_event)

    assert manager.approve_candidate(candidate.id) is None
    assert manager.get_skill_by_name(candidate.proposed_name) is None
    assert manager.get_candidate(candidate.id).status == CandidateStatus.PENDING
    assert not (tmp_path / "workspace" / "skills" / candidate.proposed_name / "SKILL.md").exists()


def test_publication_failure_compensates_committed_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    candidate = _candidate()
    manager.create_candidate(candidate)

    def fail_publish(*_args, **_kwargs):
        raise OSError("atomic publish unavailable")

    monkeypatch.setattr(skill_manager_module.os, "replace", fail_publish)

    assert manager.approve_candidate(candidate.id) is None
    assert manager.get_skill_by_name(candidate.proposed_name) is None
    assert manager.get_candidate(candidate.id).status == CandidateStatus.PENDING
    skill_dir = tmp_path / "workspace" / "skills" / candidate.proposed_name
    assert not skill_dir.exists()


def test_approval_never_overwrites_unmanaged_workspace_skill(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    candidate = _candidate()
    manager.create_candidate(candidate)
    unmanaged = tmp_path / "workspace" / "skills" / candidate.proposed_name / "SKILL.md"
    unmanaged.parent.mkdir(parents=True)
    unmanaged.write_text("# User managed skill", encoding="utf-8")

    assert manager.approve_candidate(candidate.id) is None
    assert unmanaged.read_text(encoding="utf-8") == "# User managed skill"
    assert manager.get_skill_by_name(candidate.proposed_name) is None
    assert manager.get_candidate(candidate.id).status == CandidateStatus.PENDING


def test_managed_skill_paths_cannot_escape_workspace(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    with pytest.raises(ValueError, match="Invalid managed skill name"):
        manager.create_skill(
            SkillRecord(
                id="escape",
                name="../escape",
                path="",
                description="unsafe",
            ),
            "# Unsafe",
        )

    record = SkillRecord(
        id="safe-record",
        name="safe-record",
        path="",
        description="safe",
    )
    manager.create_skill(record, "# Safe")
    outside = tmp_path / "outside.md"
    outside.write_text("do not touch", encoding="utf-8")
    with manager.db.transaction() as conn:
        conn.execute(
            "UPDATE skill_record SET path = ? WHERE id = ?",
            (str(outside), record.id),
        )

    assert manager.get_content(record.id) == ""
    assert manager.disable_skill(record.id) is False
    assert manager.delete_skill(record.id) is False
    assert outside.read_text(encoding="utf-8") == "do not touch"
