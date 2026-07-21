"""Memory Recall Receipt persistence, privacy, and feedback governance tests."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.agent.nanobot_adapter import NanobotAdapter
from core.config import Settings
from core.events import MemoryContextPrepared
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    MemoryContextEvidence,
    MemoryItem,
    MemoryRecallFeedback,
    MemoryRecallReceipt,
    MemoryRevision,
    MemoryRevisionType,
    MemoryStatus,
    MemoryType,
)
from core.memory.memory_service import MemoryService
from core.storage.db import Database


def _memory_stack(
    tmp_path: Path,
) -> tuple[MemoryRepository, MemoryService, MemoryControlService]:
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
    )
    database = Database(settings)
    database.init_database()
    repo = MemoryRepository(database)
    service = MemoryService(settings, repo)
    return (
        repo,
        service,
        MemoryControlService(
            settings,
            memory_service=service,
            repo=repo,
        ),
    )


def test_recall_receipt_is_content_free_idempotent_and_excludes_summary(
    tmp_path: Path,
) -> None:
    repo, service, _control = _memory_stack(tmp_path)
    repo.save(
        MemoryItem(
            id="preference-1",
            memory_type=MemoryType.USER_PROFILE,
            content="User prefers concise status updates",
        )
    )
    api_key = "sk-" + "abcdefghijklmnopqrst"
    evidence = [
        MemoryContextEvidence(
            memory_id="preference-1",
            memory_type=MemoryType.USER_PROFILE,
            reason=f"用户档案优先级 test@example.com {api_key}",
            chars=42,
        ),
        MemoryContextEvidence(
            memory_id="preference-1",
            memory_type=MemoryType.USER_PROFILE,
            reason="重复的选择证据",
            chars=42,
        ),
        MemoryContextEvidence(
            memory_id="summary-1",
            memory_type=MemoryType.CONVERSATION_SUMMARY,
            reason="当前会话摘要",
            chars=80,
        ),
    ]

    assert service.record_recall("task-1", "session-1", evidence) == 1
    assert service.record_recall("task-1", "session-1", evidence) == 1

    receipts = repo.list_recall_receipts("task-1")
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.memory_id == "preference-1"
    assert receipt.reason == "用户档案优先级 [email] sk-***"
    assert receipt.feedback == MemoryRecallFeedback.UNREVIEWED
    stored = receipt.model_dump()
    assert "prompt" not in stored
    assert "response" not in stored
    assert "content" not in stored


def test_recall_receipt_requires_a_coherent_feedback_timestamp() -> None:
    selected_at = datetime.now()
    with pytest.raises(ValueError):
        MemoryRecallReceipt(
            task_id="task-1",
            memory_id="memory-1",
            memory_type=MemoryType.USER_PROFILE,
            feedback=MemoryRecallFeedback.HELPFUL,
            selected_at=selected_at,
        )
    with pytest.raises(ValueError):
        MemoryRecallReceipt(
            task_id="task-1",
            memory_id="memory-1",
            memory_type=MemoryType.USER_PROFILE,
            feedback=MemoryRecallFeedback.HELPFUL,
            selected_at=selected_at,
            feedback_at=selected_at - timedelta(seconds=1),
        )


def test_repository_rejects_feedback_before_selection(tmp_path: Path) -> None:
    repo, service, _control = _memory_stack(tmp_path)
    item = repo.save(
        MemoryItem(
            id="preference-1",
            memory_type=MemoryType.USER_PROFILE,
            content="User prefers concise status updates",
        )
    )
    service.record_recall(
        "task-1",
        "session-1",
        [
            MemoryContextEvidence(
                memory_id=item.id,
                memory_type=item.memory_type,
                reason="用户偏好与请求相关",
                chars=42,
            )
        ],
    )
    receipt = repo.list_recall_receipts("task-1")[0]

    with pytest.raises(ValueError):
        repo.record_recall_feedback(
            "task-1",
            item.id,
            MemoryRecallFeedback.HELPFUL,
            feedback_at=receipt.selected_at - timedelta(seconds=1),
        )

    persisted = repo.list_recall_receipts("task-1")[0]
    assert persisted.feedback == MemoryRecallFeedback.UNREVIEWED
    assert persisted.feedback_at is None


def test_not_relevant_feedback_is_final_but_does_not_mutate_memory(
    tmp_path: Path,
) -> None:
    repo, service, control = _memory_stack(tmp_path)
    item = repo.save(
        MemoryItem(
            id="procedure-1",
            memory_type=MemoryType.PROCEDURAL_MEMORY,
            content="Run the release checklist before publishing",
        )
    )
    service.record_recall(
        "task-1",
        "session-1",
        [
            MemoryContextEvidence(
                memory_id=item.id,
                memory_type=item.memory_type,
                reason="命中 2 个请求关键词",
                chars=56,
            )
        ],
    )

    assert control.record_recall_feedback(
        "task-1",
        item.id,
        MemoryRecallFeedback.NOT_RELEVANT,
    ) == (True, False)
    assert control.record_recall_feedback(
        "task-1",
        item.id,
        MemoryRecallFeedback.HELPFUL,
    ) == (False, False)

    persisted = repo.get(item.id)
    assert persisted is not None
    assert persisted.status == MemoryStatus.ACTIVE
    assert persisted.confidence == item.confidence
    explanation = control.explain_memory(persisted)
    assert explanation.recall_count == 1
    assert explanation.not_relevant_count == 1
    assert explanation.helpful_count == 0


def test_old_receipt_cannot_evaluate_a_newer_memory_version(tmp_path: Path) -> None:
    repo, service, control = _memory_stack(tmp_path)
    item = service.save_memory(
        MemoryItem(
            id="project-versioned",
            memory_type=MemoryType.PROJECT_MEMORY,
            title="发布日",
            content="项目每周五发布",
        )
    )
    service.record_recall(
        "task-versioned",
        "session-1",
        [
            MemoryContextEvidence(
                memory_id=item.id,
                memory_type=item.memory_type,
                reason="当前请求关键词匹配",
                chars=24,
            )
        ],
    )
    service.save_memory(
        MemoryItem(
            id=item.id,
            memory_type=item.memory_type,
            title=item.title,
            content="项目改为每周四发布",
        )
    )

    review = control.list_recall_review("task-versioned")[0]
    assert review.is_current is False
    with pytest.raises(ValueError):
        control.record_recall_feedback(
            "task-versioned",
            item.id,
            MemoryRecallFeedback.INACCURATE,
        )

    receipt = repo.list_recall_receipts("task-versioned")[0]
    assert receipt.feedback == MemoryRecallFeedback.UNREVIEWED
    assert repo.get(item.id).content == "项目改为每周四发布"


def test_inaccurate_feedback_atomically_pauses_memory_and_adds_revision(
    tmp_path: Path,
) -> None:
    repo, service, control = _memory_stack(tmp_path)
    item = repo.save(
        MemoryItem(
            id="project-1",
            memory_type=MemoryType.PROJECT_MEMORY,
            content="The project deploys every Friday",
        )
    )
    service.record_recall(
        "task-2",
        "session-1",
        [
            MemoryContextEvidence(
                memory_id=item.id,
                memory_type=item.memory_type,
                reason="当前请求关键词匹配",
                chars=48,
            )
        ],
    )

    recorded, paused = control.record_recall_feedback(
        "task-2",
        item.id,
        MemoryRecallFeedback.INACCURATE,
    )

    assert recorded is True
    assert paused is True
    persisted = repo.get(item.id)
    assert persisted is not None
    assert persisted.status == MemoryStatus.NEEDS_REVIEW
    revisions = repo.list_revisions(item.id)
    assert revisions[0].revision_type == MemoryRevisionType.FLAGGED_INACCURATE
    assert revisions[0].actor == "user"
    review = control.list_recall_review("task-2")[0]
    assert review.feedback == MemoryRecallFeedback.INACCURATE
    assert review.status == MemoryStatus.NEEDS_REVIEW


def test_feedback_without_matching_receipt_cannot_pause_memory(tmp_path: Path) -> None:
    repo, service, control = _memory_stack(tmp_path)
    item = repo.save(
        MemoryItem(
            id="unrecalled",
            memory_type=MemoryType.EPISODIC_MEMORY,
            content="A retained event",
        )
    )

    assert control.record_recall_feedback(
        "missing-task",
        item.id,
        MemoryRecallFeedback.INACCURATE,
    ) == (False, False)
    assert repo.get(item.id).status == MemoryStatus.ACTIVE
    assert repo.list_revisions(item.id) == []


def test_inaccurate_feedback_rolls_back_when_revision_write_fails(
    tmp_path: Path,
) -> None:
    repo, service, _control = _memory_stack(tmp_path)
    item = repo.save(
        MemoryItem(
            id="atomic-memory",
            memory_type=MemoryType.PROJECT_MEMORY,
            content="A project fact",
        )
    )
    service.record_recall(
        "task-atomic",
        "session-1",
        [
            MemoryContextEvidence(
                memory_id=item.id,
                memory_type=item.memory_type,
                chars=20,
            )
        ],
    )
    repo.save_revision(
        MemoryRevision(
            id="revision-collision",
            memory_id=item.id,
            revision_type=MemoryRevisionType.LEARNED,
        )
    )
    colliding = MemoryRevision(
        id="revision-collision",
        memory_id=item.id,
        revision_type=MemoryRevisionType.FLAGGED_INACCURATE,
        actor="user",
    )

    with pytest.raises(sqlite3.IntegrityError):
        repo.record_recall_feedback(
            "task-atomic",
            item.id,
            MemoryRecallFeedback.INACCURATE,
            revision=colliding,
        )

    assert repo.get(item.id).status == MemoryStatus.ACTIVE
    receipt = repo.list_recall_receipts("task-atomic")[0]
    assert receipt.feedback == MemoryRecallFeedback.UNREVIEWED


def test_adapter_persists_receipt_before_publishing_reviewable_count(
    tmp_path: Path,
) -> None:
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
    )
    database = Database(settings)
    database.init_database()
    repo = MemoryRepository(database)
    service = MemoryService(settings, repo)
    repo.save(
        MemoryItem(
            id="adapter-memory",
            memory_type=MemoryType.USER_PROFILE,
            content="User prefers a concise progress summary",
        )
    )
    adapter = NanobotAdapter(settings)
    adapter.set_memory_service(service)
    events: list[MemoryContextPrepared] = []
    adapter.event_bus.subscribe(MemoryContextPrepared, events.append)

    bundle = adapter._prepare_memory_context(
        "Please help with this task " * 30,
        adapter.build_session_key("session-1"),
        "task-adapter",
    )

    receipts = repo.list_recall_receipts("task-adapter")
    assert bundle.selected_count >= 1
    assert any(receipt.memory_id == "adapter-memory" for receipt in receipts)
    assert len(events) == 1
    assert events[0].reviewable_count == len(receipts)


def test_adapter_hides_review_entry_when_receipt_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
    )
    database = Database(settings)
    database.init_database()
    repo = MemoryRepository(database)
    service = MemoryService(settings, repo)
    repo.save(
        MemoryItem(
            id="adapter-memory",
            memory_type=MemoryType.USER_PROFILE,
            content="User prefers a concise progress summary",
        )
    )
    adapter = NanobotAdapter(settings)
    adapter.set_memory_service(service)
    events: list[MemoryContextPrepared] = []
    adapter.event_bus.subscribe(MemoryContextPrepared, events.append)

    def fail_receipt_write(*_args, **_kwargs) -> int:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service, "record_recall", fail_receipt_write)
    bundle = adapter._prepare_memory_context(
        "Please help with this task " * 30,
        adapter.build_session_key("session-1"),
        "task-adapter",
    )

    assert bundle.selected_count >= 1
    assert repo.list_recall_receipts("task-adapter") == []
    assert len(events) == 1
    assert events[0].reviewable_count == 0
