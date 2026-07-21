"""Regression tests for the governed Relationship Rhythm Module."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.companion.models import (
    CompanionEnergy,
    CompanionFeedbackAction,
    CompanionMood,
    CompanionSupportMode,
    InterventionKind,
)
from core.companion.runtime import CompanionRuntime
from core.config import Settings
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    MemoryItem,
    MemoryRevisionType,
    MemoryStatus,
    MemoryType,
)
from core.memory.memory_service import MemoryService
from core.memory.memory_write_gateway import MemoryWriteGateway
from core.memory.privacy_mode import PrivacyModeManager
from core.relationship.rhythm_service import RelationshipRhythmService
from core.storage.companion_event_repo import CompanionEventRepository
from core.storage.db import Database
from core.storage.pet_repo import PetRepository


def _build_stack(tmp_path: Path):
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
    companion_repo = CompanionEventRepository(database)
    companion = CompanionRuntime(
        settings,
        history=companion_repo,
        checkins=companion_repo,
    )
    pets = PetRepository(database)
    rhythm = RelationshipRhythmService(
        control,
        companion,
        pets=pets,
        privacy=privacy,
    )
    return (
        database,
        privacy,
        memory_service,
        control,
        companion_repo,
        companion,
        pets,
        rhythm,
    )


def test_manual_relationship_memory_crosses_gateway_and_records_revision(
    tmp_path: Path,
) -> None:
    _db, privacy, _service, control, _events, _companion, _pets, _rhythm = _build_stack(
        tmp_path
    )

    saved = control.remember_manual(
        memory_type=MemoryType.USER_PROFILE,
        title="关怀偏好",
        content="长任务结束后，先给结论，再提醒我休息。",
        session_id="daily",
    )

    assert saved.source == "manual"
    assert saved.confidence == 1.0
    assert control.explain_memory(saved).source_label == "手动添加"
    revision = control.list_revisions(memory_id=saved.id)[0]
    assert revision.revision_type == MemoryRevisionType.LEARNED
    assert revision.actor == "manual"
    assert "主动告诉" in revision.reason

    privacy.enable_privacy("private")
    with pytest.raises(ValueError, match="隐私模式"):
        control.remember_manual(
            memory_type=MemoryType.EPISODIC_MEMORY,
            title="私密瞬间",
            content="不应写入",
            session_id="private",
        )


def test_relationship_snapshot_uses_explicit_evidence_without_relationship_score(
    tmp_path: Path,
) -> None:
    (
        _db,
        _privacy,
        memory_service,
        control,
        events,
        companion,
        pets,
        rhythm,
    ) = _build_stack(tmp_path)
    now = datetime(2026, 7, 19, 15, 30)
    manual = control.remember_manual(
        memory_type=MemoryType.USER_PROFILE,
        title="沟通节奏",
        content="复杂任务先安静执行，遇到授权点再叫我。",
        session_id="daily",
    )
    memory_service.save_memory(
        MemoryItem(
            id="uncertain-moment",
            memory_type=MemoryType.EPISODIC_MEMORY,
            title="可能重要的瞬间",
            content="一起完成过一次发布",
            source="ai_patch",
            confidence=0.68,
            importance=0.9,
            status=MemoryStatus.NEEDS_REVIEW,
        )
    )
    check_in = companion.submit_check_in(
        CompanionMood.STEADY,
        CompanionEnergy.MEDIUM,
        CompanionSupportMode.FOCUS,
        now=now,
    )
    event_id = events.record(InterventionKind.REST, now - timedelta(minutes=5))
    companion.submit_feedback(
        event_id,
        CompanionFeedbackAction.MUTE_KIND,
        now=now,
    )
    pet = pets.get_or_create_pet()
    pet.personality.technical_skill = 57.5
    pet.personality.interaction_counts["technical_skill:task_analysis"] = 4
    pets.save_pet(pet)

    snapshot = rhythm.snapshot(session_id="daily", now=now)

    assert snapshot.headline == "我会按你刚刚选择的方式陪着你"
    assert snapshot.active_check_in == check_in.check_in
    assert snapshot.active_memory_count == 1
    assert snapshot.explicitly_confirmed_count == 1
    assert snapshot.pending_review_count == 1
    assert snapshot.memories[0].memory_id == "uncertain-moment"
    assert snapshot.memories[0].trust_label == "等待你确认"
    manual_evidence = next(item for item in snapshot.memories if item.memory_id == manual.id)
    assert manual_evidence.trust_label == "你主动留下"
    assert snapshot.preference_summary.muted_kinds == [InterventionKind.REST]
    technical = next(
        trait for trait in snapshot.growth_traits if trait.dimension == "technical_skill"
    )
    assert technical.value == 57.5
    assert technical.delta_from_baseline == 7.5
    assert technical.evidence_count == 4
    assert "成功任务" in technical.explanation
    assert "score" not in snapshot.model_dump()


def test_relationship_controls_revoke_only_the_intended_care_state(
    tmp_path: Path,
) -> None:
    _db, _privacy, _service, _control, events, companion, _pets, rhythm = _build_stack(
        tmp_path
    )
    now = datetime(2026, 7, 19, 20)
    check_in = companion.submit_check_in(
        CompanionMood.TIRED,
        CompanionEnergy.LOW,
        CompanionSupportMode.QUIET,
        now=now,
    )
    helpful_id = events.record(InterventionKind.RECOVERY, now)
    muted_id = events.record(InterventionKind.LATE_NIGHT, now + timedelta(seconds=1))
    companion.submit_feedback(helpful_id, CompanionFeedbackAction.HELPFUL, now=now)
    companion.submit_feedback(
        muted_id,
        CompanionFeedbackAction.MUTE_KIND,
        now=now + timedelta(seconds=1),
    )

    assert check_in.accepted
    assert rhythm.clear_current_check_in() == 1
    assert companion.active_check_in(now=now) is None
    assert rhythm.restore_care_boundaries() == 1
    summary = companion.feedback_summary(now=now)
    assert summary.helpful_count == 1
    assert summary.muted_kinds == []
