"""Regression tests for user-governed Structured Memory revisions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.config import Settings
from core.memory.memory_conflict_resolver import MemoryConflictResolver
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    ConflictCandidate,
    ConflictStatus,
    ConflictType,
    MemoryItem,
    MemoryRevision,
    MemoryRevisionType,
    MemoryStatus,
    MemoryType,
)
from core.memory.memory_service import MemoryService
from core.storage.db import Database


def _build_memory_stack(
    tmp_path: Path,
) -> tuple[MemoryService, MemoryControlService, MemoryRepository]:
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
        user_name="",
    )
    repo = MemoryRepository(Database(settings))
    service = MemoryService(settings, repo)
    control = MemoryControlService(settings, memory_service=service, repo=repo)
    return service, control, repo


def test_user_governance_records_ordered_revisions_and_explanation(
    tmp_path: Path,
) -> None:
    service, control, repo = _build_memory_stack(tmp_path)
    service.save_memory(
        MemoryItem(
            id="preference",
            memory_type=MemoryType.USER_PROFILE,
            title="沟通偏好",
            content="用户喜欢简短回答",
            source="ai_patch",
            confidence=0.8,
        )
    )

    corrected = control.revise_memory(
        "preference",
        "用户喜欢先给结论，再补充必要细节",
        "原来的表述太绝对",
    )
    assert corrected is not None
    assert corrected.confidence == 1.0
    assert control.confirm_memory("preference") is not None
    assert control.retire_memory("preference", "近期暂时不需要这项偏好")
    assert control.restore_memory("preference", "重新启用这项沟通偏好")

    revisions = repo.list_revisions("preference")
    assert [revision.revision_type for revision in revisions] == [
        MemoryRevisionType.RESTORED,
        MemoryRevisionType.RETIRED,
        MemoryRevisionType.CONFIRMED,
        MemoryRevisionType.CORRECTED,
        MemoryRevisionType.LEARNED,
    ]
    explanation = control.explain_memory(repo.get("preference"))
    assert explanation.trust_label == "你已确认"
    assert explanation.usage_label == "会在相关对话中使用"
    timeline = control.list_timeline(memory_id="preference")
    assert timeline[0].event_label == "恢复使用"
    assert timeline[0].reason == "重新启用这项沟通偏好"


def test_permanent_forgetting_removes_content_from_all_projections(
    tmp_path: Path,
) -> None:
    service, control, repo = _build_memory_stack(tmp_path)
    content = "项目代号是 Aurora-Secret"
    service.save_memory(
        MemoryItem(
            id="project-secret",
            memory_type=MemoryType.PROJECT_MEMORY,
            title="项目代号",
            content=content,
            source="manual",
        )
    )
    project_projection = tmp_path / "data" / "memory" / "PROJECT.md"
    workspace_projection = tmp_path / "workspace" / "memory" / "MEMORY.md"
    assert content in project_projection.read_text(encoding="utf-8")
    assert content in workspace_projection.read_text(encoding="utf-8")

    assert control.forget_memory(
        "project-secret",
        f"项目已经结束，请永久清除：{content}",
    )

    assert repo.get("project-secret") is None
    assert content not in project_projection.read_text(encoding="utf-8")
    assert content not in workspace_projection.read_text(encoding="utf-8")
    revisions = repo.list_revisions("project-secret")
    assert revisions[0].revision_type == MemoryRevisionType.FORGOTTEN
    assert revisions[0].previous_content_hash
    assert content not in revisions[0].reason
    assert "[已移除]" in revisions[0].reason
    timeline = control.list_timeline(memory_id="project-secret")
    assert timeline[0].forgotten is True
    assert timeline[0].title == "已永久忘记的记忆"
    assert all(entry.content_preview == "" for entry in timeline)


def test_conflict_resolution_rolls_back_every_change_on_revision_failure(
    tmp_path: Path,
) -> None:
    _service, _control, repo = _build_memory_stack(tmp_path)
    repo.save(
        MemoryItem(
            id="old",
            memory_type=MemoryType.USER_PROFILE,
            title="工作时间",
            content="用户上午工作",
        )
    )
    repo.save(
        MemoryItem(
            id="new",
            memory_type=MemoryType.USER_PROFILE,
            title="工作时间",
            content="用户晚上工作",
        )
    )
    candidate = repo.save_conflict_candidate(
        ConflictCandidate(
            id="conflict",
            existing_item_id="old",
            new_item_id="new",
            conflict_type=ConflictType.DIFFERENT_VALUE,
        )
    )
    duplicate_revision = MemoryRevision(
        id="same-revision",
        memory_id="old",
        revision_type=MemoryRevisionType.CONFLICT_RESOLVED,
        actor="user",
        reason="test rollback",
    )
    revision_ids_before = {revision.id for revision in repo.list_revisions()}

    with pytest.raises(sqlite3.IntegrityError):
        repo.resolve_conflict_atomic(
            candidate.id,
            True,
            [
                duplicate_revision,
                duplicate_revision.model_copy(update={"memory_id": "new"}),
            ],
        )

    assert repo.get("old").status == MemoryStatus.ACTIVE
    assert repo.get("new").status == MemoryStatus.ACTIVE
    assert repo.get_conflict_candidate(candidate.id).status == ConflictStatus.PENDING
    assert {revision.id for revision in repo.list_revisions()} == revision_ids_before


def test_legacy_memory_without_revision_appears_as_synthetic_timeline_entry(
    tmp_path: Path,
) -> None:
    _service, control, repo = _build_memory_stack(tmp_path)
    repo.save(
        MemoryItem(
            id="legacy",
            memory_type=MemoryType.EPISODIC_MEMORY,
            title="第一次协作",
            content="一起完成了发布检查",
            source="migration",
        )
    )

    timeline = control.list_timeline(memory_id="legacy")

    assert len(timeline) == 1
    assert timeline[0].revision_id == "legacy:legacy"
    assert timeline[0].event_label == "最初记住"
    assert "关系时间线启用之前" in timeline[0].reason


def test_automatic_conflict_resolution_is_explainable_and_prefers_confidence(
    tmp_path: Path,
) -> None:
    _service, _control, repo = _build_memory_stack(tmp_path)
    existing = repo.save(
        MemoryItem(
            id="less-certain",
            memory_type=MemoryType.USER_PROFILE,
            title="工作节奏",
            content="上午更适合复杂任务",
            confidence=0.72,
        )
    )
    newer = repo.save(
        MemoryItem(
            id="more-certain",
            memory_type=MemoryType.USER_PROFILE,
            title="工作节奏",
            content="晚上更适合复杂任务",
            confidence=0.99,
        )
    )

    candidates = MemoryConflictResolver(repo).detect_conflicts_for_new_item(newer)

    assert candidates == []
    assert repo.get(existing.id).status == MemoryStatus.DEPRECATED
    assert repo.get(newer.id).status == MemoryStatus.ACTIVE
    revisions = repo.list_revisions(limit=20)
    auto_revisions = [
        revision for revision in revisions if revision.memory_id in {existing.id, newer.id}
    ]
    assert len(auto_revisions) == 2
    assert all(
        revision.revision_type == MemoryRevisionType.CONFLICT_RESOLVED
        for revision in auto_revisions
    )
    assert all(revision.actor == "system" for revision in auto_revisions)


def test_automatic_conflict_resolution_never_overrides_stronger_existing_fact(
    tmp_path: Path,
) -> None:
    _service, _control, repo = _build_memory_stack(tmp_path)
    repo.save(
        MemoryItem(
            id="confirmed-existing",
            memory_type=MemoryType.USER_PROFILE,
            title="沟通语言",
            content="优先使用中文",
            confidence=1.0,
        )
    )
    newer = repo.save(
        MemoryItem(
            id="less-certain-new",
            memory_type=MemoryType.USER_PROFILE,
            title="沟通语言",
            content="优先使用英文",
            confidence=0.99,
        )
    )

    candidates = MemoryConflictResolver(repo).detect_conflicts_for_new_item(newer)

    assert len(candidates) == 1
    assert repo.get("confirmed-existing").status == MemoryStatus.ACTIVE
    assert repo.get("less-certain-new").status == MemoryStatus.NEEDS_REVIEW


def test_console_search_can_find_retired_memory_for_restoration(tmp_path: Path) -> None:
    service, control, _repo = _build_memory_stack(tmp_path)
    service.save_memory(
        MemoryItem(
            id="retired-project",
            memory_type=MemoryType.PROJECT_MEMORY,
            title="北极星项目",
            content="项目使用蓝绿色视觉语言",
        )
    )
    assert control.retire_memory("retired-project", "项目暂时搁置")

    all_statuses = control.search_memories("北极星")
    retired_only = control.search_memories(
        "北极星",
        status=MemoryStatus.DEPRECATED,
    )

    assert [item.id for item in all_statuses] == ["retired-project"]
    assert [item.id for item in retired_only] == ["retired-project"]
