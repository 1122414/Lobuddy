"""Integration tests for Lobuddy 5.8 memory system evolution.

Tests cover:
- P1-C1: Memory console operations (list/deprecate/delete/edit)
- P1-C2: Provenance display
- P1-C3: Conflict detection
- P1-C4: Privacy mode
- P2-C5: Cold recall reserved interfaces
"""

import asyncio
import os
import tempfile
import uuid

import pytest

from core.config import Settings
from core.memory.memory_conflict_resolver import MemoryConflictResolver
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    ConflictStatus,
    ConflictType,
    MemoryItem,
    MemoryPatch,
    MemoryPatchAction,
    MemoryPatchItem,
    MemoryStatus,
    MemoryType,
)
from core.memory.memory_service import MemoryService
from core.memory.memory_write_gateway import MemoryWriteGateway, WriteContext
from core.memory.privacy_mode import PrivacyModeManager
from core.memory.recall_policy import RecallBudget, RecallPolicy, SessionRecallCandidate
from core.storage.db import Database


@pytest.fixture
def test_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = Settings(
            llm_api_key="test-key",
            data_dir=tmpdir,
            logs_dir=os.path.join(tmpdir, "logs"),
        )
        db = Database(settings)
        yield db


@pytest.fixture
def settings():
    return Settings(
        llm_api_key="test-key",
        data_dir="./data",
        logs_dir="./logs",
    )


@pytest.fixture
def repo(test_db):
    return MemoryRepository(test_db)


@pytest.fixture
def memory_service(repo, settings):
    return MemoryService(settings, repo=repo)


@pytest.fixture
def control_service(memory_service, repo):
    return MemoryControlService(
        settings=memory_service._settings,
        memory_service=memory_service,
        repo=repo,
    )


class TestMemoryControlService:
    """P1-C1: Memory console operations."""

    def test_list_memories(self, control_service, repo):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="test",
            content="test content",
        )
        repo.save(item)

        items = control_service.list_memories()
        assert len(items) >= 1
        assert any(i.id == item.id for i in items)

    def test_get_memory(self, control_service, repo):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="test",
            content="test content",
        )
        repo.save(item)

        found = control_service.get_memory(item.id)
        assert found is not None
        assert found.id == item.id

    def test_edit_memory(self, control_service, repo):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="test",
            content="original",
        )
        repo.save(item)

        ok = control_service.edit_memory(item.id, "updated")
        assert ok is True

        updated = repo.get(item.id)
        assert updated.content == "updated"

    def test_deprecate_memory(self, control_service, repo):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="test",
            content="test",
        )
        repo.save(item)

        ok = control_service.deprecate_memory(item.id)
        assert ok is True

        deprecated = repo.get(item.id)
        assert deprecated.status == MemoryStatus.DEPRECATED

    def test_delete_memory(self, control_service, repo):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="test",
            content="test",
        )
        repo.save(item)

        ok = control_service.delete_memory(item.id)
        assert ok is True

        assert repo.get(item.id) is None

    def test_get_provenance(self, control_service, repo):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="test",
            content="test",
            source="ai",
            source_session_id="sess-123",
            confidence=0.9,
            importance=0.8,
        )
        repo.save(item)

        prov = control_service.get_provenance(item)
        assert prov.source == "ai"
        assert prov.has_precise_source is True
        assert prov.confidence == 0.9
        assert prov.importance == 0.8

    def test_get_provenance_legacy(self, control_service, repo):
        item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="test",
            content="test",
            source="migration",
        )
        repo.save(item)

        prov = control_service.get_provenance(item)
        assert prov.has_precise_source is False

    def test_sanitized_content(self, control_service, repo):
        api_key = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
        item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="test",
            content=f"API key: {api_key}",
        )
        repo.save(item)

        masked = control_service.get_sanitized_content(item, show_full=False)
        assert "sk-***" in masked
        assert "abcdefghijklmnopqrstuvwxyz123456" not in masked

        full = control_service.get_sanitized_content(item, show_full=True)
        assert api_key in full


class TestConflictDetection:
    """P1-C3: Memory conflict detection."""

    def test_detect_conflicts_same_title_different_value(self, repo):
        resolver = MemoryConflictResolver(repo)

        item1 = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="preference",
            content="User likes dark mode",
            confidence=0.9,
        )
        item2 = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="preference",
            content="User likes light mode",
            confidence=0.8,
        )
        repo.save(item1)
        repo.save(item2)

        candidates = resolver.detect_conflicts(MemoryType.USER_PROFILE)
        assert len(candidates) == 1
        assert candidates[0].conflict_type == ConflictType.DIFFERENT_VALUE
        assert candidates[0].status == ConflictStatus.PENDING

    def test_no_conflict_same_content(self, repo):
        resolver = MemoryConflictResolver(repo)

        item1 = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="name",
            content="User name is Alice",
        )
        item2 = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="name",
            content="User name is Alice",
        )
        repo.save(item1)
        repo.save(item2)

        candidates = resolver.detect_conflicts(MemoryType.USER_PROFILE)
        assert len(candidates) == 0

    def test_no_conflict_substring(self, repo):
        resolver = MemoryConflictResolver(repo)

        item1 = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="bio",
            content="User is a developer",
        )
        item2 = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="bio",
            content="User is a developer who likes Python",
        )
        repo.save(item1)
        repo.save(item2)

        candidates = resolver.detect_conflicts(MemoryType.USER_PROFILE)
        assert len(candidates) == 0

    def test_resolve_conflict_accept_new(self, repo):
        resolver = MemoryConflictResolver(repo)

        existing = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="pref",
            content="old value",
        )
        new_item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="pref",
            content="new value",
        )
        repo.save(existing)
        repo.save(new_item)

        candidates = resolver.detect_conflicts_for_new_item(new_item)
        assert len(candidates) == 1

        resolved = resolver.resolve_conflict(candidates[0].id, accept_new=True)
        assert resolved is not None
        assert resolved.status == ConflictStatus.RESOLVED

        assert repo.get(existing.id).status == MemoryStatus.DEPRECATED
        assert repo.get(new_item.id).status == MemoryStatus.ACTIVE

    def test_resolve_conflict_reject_new(self, repo):
        resolver = MemoryConflictResolver(repo)

        existing = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="pref",
            content="old value",
        )
        new_item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="pref",
            content="new value",
        )
        repo.save(existing)
        repo.save(new_item)

        candidates = resolver.detect_conflicts_for_new_item(new_item)
        resolved = resolver.resolve_conflict(candidates[0].id, accept_new=False)
        assert resolved is not None
        assert resolved.status == ConflictStatus.REJECTED

        assert repo.get(existing.id).status == MemoryStatus.ACTIVE
        assert repo.get(new_item.id).status == MemoryStatus.DEPRECATED


class TestPrivacyMode:
    """P1-C4: Privacy mode."""

    def test_default_privacy_disabled(self, settings):
        mgr = PrivacyModeManager(settings)
        assert mgr.is_privacy_active("sess-1") is False

    def test_enable_disable_privacy(self, settings):
        mgr = PrivacyModeManager(settings)
        mgr.enable_privacy("sess-1")
        assert mgr.is_privacy_active("sess-1") is True
        mgr.disable_privacy("sess-1")
        assert mgr.is_privacy_active("sess-1") is False

    def test_empty_session_id(self, settings):
        mgr = PrivacyModeManager(settings)
        assert mgr.is_privacy_active("") is False
        assert mgr.is_privacy_active(None) is False

    def test_default_from_settings(self, settings):
        settings.privacy_mode_enabled = True
        mgr = PrivacyModeManager(settings)
        assert mgr.is_privacy_active("sess-new") is True


class TestGatewayPrivacyBlocking:
    """Gateway-level functional tests for privacy mode blocking actual writes."""

    def test_gateway_blocks_patch_in_privacy_mode(self, test_db, settings):
        repo = MemoryRepository(test_db)
        service = MemoryService(settings, repo=repo)
        privacy = PrivacyModeManager(settings)
        privacy.enable_privacy("sess-private")
        gateway = MemoryWriteGateway(service, settings, privacy=privacy)

        patch = MemoryPatch(
            items=[
                MemoryPatchItem(
                    action=MemoryPatchAction.ADD,
                    memory_type=MemoryType.USER_PROFILE,
                    title="test",
                    content="test content",
                    confidence=0.9,
                    importance=0.8,
                )
            ]
        )
        context = WriteContext(
            source="ai_patch",
            session_id="sess-private",
            triggered_by="adapter",
        )

        async def _run():
            result = await gateway.submit_patch(patch, context)
            assert len(result.accepted) == 0
            assert len(result.rejected) == 0
            assert len(result.needs_review) == 0
            assert len(result.conflicts) == 0

        asyncio.run(_run())

    def test_gateway_allows_patch_when_privacy_disabled(self, test_db, settings):
        repo = MemoryRepository(test_db)
        service = MemoryService(settings, repo=repo)
        privacy = PrivacyModeManager(settings)
        gateway = MemoryWriteGateway(service, settings, privacy=privacy)

        patch = MemoryPatch(
            items=[
                MemoryPatchItem(
                    action=MemoryPatchAction.ADD,
                    memory_type=MemoryType.USER_PROFILE,
                    title="test",
                    content="test content",
                    confidence=0.9,
                    importance=0.8,
                )
            ]
        )
        context = WriteContext(
            source="ai_patch",
            session_id="sess-normal",
            triggered_by="adapter",
        )

        async def _run():
            result = await gateway.submit_patch(patch, context)
            assert len(result.accepted) == 1

        asyncio.run(_run())

    def test_gateway_blocks_identity_memory_in_privacy_mode(self, test_db, settings):
        repo = MemoryRepository(test_db)
        service = MemoryService(settings, repo=repo)
        privacy = PrivacyModeManager(settings)
        privacy.enable_privacy("sess-private")
        gateway = MemoryWriteGateway(service, settings, privacy=privacy)

        context = WriteContext(
            source="strong_signal",
            session_id="sess-private",
            triggered_by="adapter",
        )

        with pytest.raises(ValueError, match="Privacy mode active"):
            gateway.submit_identity_memory(
                memory_type=MemoryType.USER_PROFILE,
                title="name",
                content="Alice",
                context=context,
            )


class TestColdRecallInterfaces:
    """P2-C5: Cold recall reserved interfaces."""

    def test_recall_budget_allocation(self):
        budget = RecallBudget(total_chars=1000, remaining_chars=200)
        allocated = budget.allocate(150)
        assert allocated == 150
        assert budget.remaining_chars == 50
        assert budget.is_exhausted is False

    def test_recall_budget_exhaustion(self):
        budget = RecallBudget(total_chars=1000, remaining_chars=50)
        allocated = budget.allocate(100)
        assert allocated == 50
        assert budget.is_exhausted is True

    def test_recall_policy_disabled(self):
        policy = RecallPolicy(enabled=False)
        candidates = [
            SessionRecallCandidate(
                item=MemoryItem(id="1", memory_type=MemoryType.EPISODIC_MEMORY, content="x"),
                relevance_score=0.9,
            )
        ]
        result = policy.should_recall(candidates)
        assert result == []

    def test_recall_policy_filtering(self):
        policy = RecallPolicy(enabled=True, max_candidates_per_turn=2, min_relevance_threshold=0.6)
        candidates = [
            SessionRecallCandidate(
                item=MemoryItem(id="1", memory_type=MemoryType.EPISODIC_MEMORY, content="x"),
                relevance_score=0.9,
            ),
            SessionRecallCandidate(
                item=MemoryItem(id="2", memory_type=MemoryType.EPISODIC_MEMORY, content="y"),
                relevance_score=0.5,
            ),
            SessionRecallCandidate(
                item=MemoryItem(id="3", memory_type=MemoryType.EPISODIC_MEMORY, content="z"),
                relevance_score=0.8,
            ),
        ]
        result = policy.should_recall(candidates)
        assert len(result) == 2
        assert result[0].relevance_score == 0.9
        assert result[1].relevance_score == 0.8

    def test_recall_policy_budget(self):
        policy = RecallPolicy(enabled=True)
        budget = policy.create_budget(hot_memory_used_chars=300, total_budget_chars=1000)
        assert budget.remaining_chars == 700
        assert budget.total_chars == 1000

    def test_session_recall_candidate_high_relevance(self):
        candidate = SessionRecallCandidate(
            item=MemoryItem(id="1", memory_type=MemoryType.EPISODIC_MEMORY, content="x"),
            relevance_score=0.75,
        )
        assert candidate.is_high_relevance is True

    def test_session_recall_candidate_low_relevance(self):
        candidate = SessionRecallCandidate(
            item=MemoryItem(id="1", memory_type=MemoryType.EPISODIC_MEMORY, content="x"),
            relevance_score=0.5,
        )
        assert candidate.is_high_relevance is False
