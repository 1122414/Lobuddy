"""Tests for governed, review-only skill evolution."""

from datetime import datetime
from pathlib import Path

from app.config import Settings
from core.agent.nanobot_adapter import AgentResult, NanobotAdapter
from core.models.pet import TaskRecord, TaskResult, TaskStatus
from core.skills.skill_evolution_service import SkillEvolutionService
from core.skills.skill_manager import SkillManager
from core.skills.skill_schema import CandidateStatus, SkillStatus
from core.storage.db import Database
from core.storage.execution_trace_repository import ExecutionTraceRepository
from core.storage.task_repo import TaskRepository


def _make_services(tmp_path: Path, **overrides):
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        workspace_path=tmp_path / "workspace",
        skill_archive_dir=tmp_path / "archive",
        skill_auto_candidate_enabled=True,
        **overrides,
    )
    database = Database(settings)
    database.init_database()
    manager = SkillManager(settings, database)
    return settings, manager, SkillEvolutionService(settings, manager)


def _consider(service: SkillEvolutionService, **overrides):
    payload = {
        "success": True,
        "task_input": "Prepare a weekly report for alice@example.com",
        "tools_used": ["read_file", "write_file"],
        "output_length": 1200,
        "session_id": "session-1",
        "task_id": "task-1",
        "privacy_active": False,
        "has_image": False,
    }
    payload.update(overrides)
    return service.consider_task(**payload)


def _persist_source_evidence(
    manager: SkillManager,
    *,
    task_id: str = "task-1",
    session_id: str = "session-1",
    tools: tuple[str, ...] = ("read_file", "write_file"),
) -> None:
    tasks = TaskRepository(manager.db)
    tasks.create_task(
        TaskRecord(
            id=task_id,
            input_text="Prepare a weekly report",
            status=TaskStatus.SUCCESS,
            session_id=session_id,
        )
    )
    tasks.save_task_result(
        TaskResult(
            task_id=task_id,
            success=True,
            summary="completed",
        )
    )
    traces = ExecutionTraceRepository(manager.db)
    for tool in tools:
        traces.record(
            session_id=task_id,
            intent="workspace_task",
            tool_name=tool,
            arguments={},
            status="completed",
        )


def test_successful_safe_workflow_creates_sanitized_pending_proposal(tmp_path):
    _, manager, service = _make_services(tmp_path)

    candidate = _consider(service)

    assert candidate is not None
    assert candidate.status == CandidateStatus.PENDING
    assert candidate.evidence["activation_requires_review"] is True
    assert candidate.evidence["tools"] == ["read_file", "write_file"]
    assert "alice@example.com" not in candidate.proposed_content
    assert "[REDACTED_EMAIL]" in candidate.proposed_content
    assert "Task-specific output was intentionally omitted" in candidate.proposed_content
    loaded = manager.get_candidate(candidate.id)
    assert loaded is not None
    assert loaded.evidence == candidate.evidence
    assert loaded.validation_errors == []


def test_private_multimodal_and_high_risk_tasks_never_become_proposals(tmp_path):
    _, _, service = _make_services(tmp_path)

    assert _consider(service, privacy_active=True) is None
    assert _consider(service, has_image=True) is None
    assert _consider(service, tools_used=["read_file", "computer_act"]) is None
    assert _consider(service, tools_used=["read_file", "exec"]) is None
    assert _consider(service, success=False) is None


def test_duplicate_evidence_does_not_spam_review_queue(tmp_path):
    _, manager, service = _make_services(tmp_path)

    first = _consider(service)
    second = _consider(service, task_id="task-2")

    assert first is not None
    assert second is None
    assert manager.get_candidate_stats()["pending"] == 1


def test_explicit_request_can_create_proposal_when_automatic_mode_is_off(tmp_path):
    settings, manager, _ = _make_services(tmp_path)
    settings.skill_auto_candidate_enabled = False
    settings.skill_candidate_min_tools_used = 5
    service = SkillEvolutionService(settings, manager)

    candidate = _consider(
        service,
        task_input="以后这样处理，并保存为技能",
        tools_used=["read_file"],
    )

    assert candidate is not None
    assert candidate.confidence == 0.9
    assert candidate.evidence["explicit_user_request"] is True


def test_approved_evolution_can_be_disabled_as_a_rollback(tmp_path):
    _, manager, service = _make_services(tmp_path)
    candidate = _consider(service)
    assert candidate is not None
    _persist_source_evidence(manager)

    skill = manager.approve_candidate(candidate.id)
    assert skill is not None
    assert skill.status == SkillStatus.ACTIVE
    assert Path(skill.path).exists()

    assert manager.disable_skill(skill.id) is True
    assert manager.get_skill(skill.id).status == SkillStatus.DISABLED
    assert not Path(skill.path).exists()

    assert manager.enable_skill(skill.id) is True
    assert Path(skill.path).read_text(encoding="utf-8") == candidate.proposed_content


class _Privacy:
    @staticmethod
    def is_privacy_active(_session_id: str) -> bool:
        return False


def test_adapter_records_candidate_id_without_changing_task_result(tmp_path):
    settings, manager, _ = _make_services(tmp_path)
    adapter = NanobotAdapter(settings)
    adapter.set_skill_manager(manager)
    adapter.set_privacy_manager(_Privacy())
    now = datetime.now()
    result = AgentResult(
        success=True,
        raw_output="completed",
        summary="completed",
        started_at=now,
        finished_at=now,
        tools_used=["read_file", "write_file"],
    )

    adapter._maybe_propose_skill_evolution(
        original_prompt="Prepare the weekly report",
        result=result,
        session_key="lobuddy:session:session-1",
        task_id="task-1",
        has_image=False,
    )

    assert result.evolution_candidate_id is not None
    assert manager.get_candidate(result.evolution_candidate_id) is not None
    assert manager.get_latest_candidate_evaluation(result.evolution_candidate_id) is None

    _persist_source_evidence(manager)
    adapter.finalize_skill_evolution(result.evolution_candidate_id)

    report = manager.get_latest_candidate_evaluation(result.evolution_candidate_id)
    assert report is not None
    assert report.provenance.status.value == "verified"
