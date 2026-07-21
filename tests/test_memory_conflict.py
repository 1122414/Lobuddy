"""Tests for memory conflict detection and resolution."""

from pathlib import Path

from core.config import Settings
from core.memory.memory_conflict_resolver import MemoryConflictResolver
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    ConflictCandidate,
    ConflictStatus,
    ConflictType,
    MemoryItem,
    MemoryStatus,
    MemoryType,
)
from core.memory.memory_service import MemoryService
from core.storage.db import Database


class TestConflictCandidateModel:
    def test_default_status_is_pending(self):
        candidate = ConflictCandidate(
            id="c1",
            existing_item_id="a",
            new_item_id="b",
            conflict_type=ConflictType.DIFFERENT_VALUE,
        )
        assert candidate.status == ConflictStatus.PENDING
        assert candidate.resolved_at is None


class TestMemoryRepositoryConflictCandidates:
    def test_save_and_get_roundtrip(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        repo.save(MemoryItem(id="a", memory_type=MemoryType.USER_PROFILE, content="A"))
        repo.save(MemoryItem(id="b", memory_type=MemoryType.USER_PROFILE, content="B"))
        candidate = ConflictCandidate(
            id="c1",
            existing_item_id="a",
            new_item_id="b",
            conflict_type=ConflictType.DIFFERENT_VALUE,
        )
        saved = repo.save_conflict_candidate(candidate)
        assert saved.id == "c1"

        loaded = repo.get_conflict_candidate("c1")
        assert loaded is not None
        assert loaded.existing_item_id == "a"
        assert loaded.new_item_id == "b"
        assert loaded.status == ConflictStatus.PENDING

    def test_list_all_and_filter_by_status(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        repo.save(MemoryItem(id="a", memory_type=MemoryType.USER_PROFILE, content="A"))
        repo.save(MemoryItem(id="b", memory_type=MemoryType.USER_PROFILE, content="B"))
        repo.save(MemoryItem(id="c", memory_type=MemoryType.USER_PROFILE, content="C"))
        repo.save(MemoryItem(id="d", memory_type=MemoryType.USER_PROFILE, content="D"))
        repo.save_conflict_candidate(
            ConflictCandidate(
                id="c1", existing_item_id="a", new_item_id="b",
                conflict_type=ConflictType.DIFFERENT_VALUE,
            )
        )
        repo.save_conflict_candidate(
            ConflictCandidate(
                id="c2", existing_item_id="c", new_item_id="d",
                conflict_type=ConflictType.DIFFERENT_VALUE,
                status=ConflictStatus.RESOLVED,
            )
        )

        all_candidates = repo.list_conflict_candidates()
        assert len(all_candidates) == 2

        pending = repo.list_conflict_candidates(ConflictStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].id == "c1"

    def test_update_status(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        repo.save(MemoryItem(id="a", memory_type=MemoryType.USER_PROFILE, content="A"))
        repo.save(MemoryItem(id="b", memory_type=MemoryType.USER_PROFILE, content="B"))
        repo.save_conflict_candidate(
            ConflictCandidate(
                id="c1", existing_item_id="a", new_item_id="b",
                conflict_type=ConflictType.DIFFERENT_VALUE,
            )
        )
        ok = repo.update_conflict_status("c1", ConflictStatus.RESOLVED)
        assert ok is True

        loaded = repo.get_conflict_candidate("c1")
        assert loaded is not None
        assert loaded.status == ConflictStatus.RESOLVED
        assert loaded.resolved_at is not None

    def test_get_nonexistent_returns_none(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        assert repo.get_conflict_candidate("nonexistent") is None


class TestMemoryConflictResolver:
    def test_detect_conflicts_same_title_different_content(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        repo.save(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        repo.save(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs", title="Pets", confidence=0.7,
        ))

        resolver = MemoryConflictResolver(repo)
        candidates = resolver.detect_conflicts(MemoryType.USER_PROFILE)
        assert len(candidates) == 1
        assert candidates[0].existing_item_id == "a"
        assert candidates[0].new_item_id == "b"
        assert candidates[0].conflict_type == ConflictType.DIFFERENT_VALUE

        item_b = repo.get("b")
        assert item_b is not None
        assert item_b.status == MemoryStatus.NEEDS_REVIEW

    def test_no_conflict_on_same_content(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        repo.save(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        repo.save(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.7,
        ))

        resolver = MemoryConflictResolver(repo)
        candidates = resolver.detect_conflicts(MemoryType.USER_PROFILE)
        assert len(candidates) == 0

    def test_no_conflict_on_substring_content(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        repo.save(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        repo.save(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats and dogs", title="Pets", confidence=0.7,
        ))

        resolver = MemoryConflictResolver(repo)
        candidates = resolver.detect_conflicts(MemoryType.USER_PROFILE)
        assert len(candidates) == 0

    def test_no_conflict_on_different_titles(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        repo.save(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="Color preference", title="Preferences", confidence=0.9,
        ))
        repo.save(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="Different content", title="Habits", confidence=0.7,
        ))

        resolver = MemoryConflictResolver(repo)
        candidates = resolver.detect_conflicts(MemoryType.USER_PROFILE)
        assert len(candidates) == 0

    def test_idempotent_conflict_detection(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        repo.save(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        repo.save(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs", title="Pets", confidence=0.7,
        ))

        resolver = MemoryConflictResolver(repo)
        first = resolver.detect_conflicts(MemoryType.USER_PROFILE)
        second = resolver.detect_conflicts(MemoryType.USER_PROFILE)
        assert len(first) == 1
        assert len(second) == 0

    def test_detect_conflicts_for_new_item(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        repo.save(MemoryItem(
            id="existing", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        new_item = MemoryItem(
            id="new", memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs", title="Pets", confidence=0.7,
        )
        repo.save(new_item)

        resolver = MemoryConflictResolver(repo)
        candidates = resolver.detect_conflicts_for_new_item(new_item)
        assert len(candidates) == 1
        assert candidates[0].existing_item_id == "existing"
        assert candidates[0].new_item_id == "new"

    def test_resolve_conflict_accept_new(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        repo.save(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        repo.save(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs", title="Pets", confidence=0.7,
        ))

        resolver = MemoryConflictResolver(repo)
        candidates = resolver.detect_conflicts(MemoryType.USER_PROFILE)
        result = resolver.resolve_conflict(candidates[0].id, accept_new=True)
        assert result is not None
        assert result.status == ConflictStatus.RESOLVED

        item_a = repo.get("a")
        item_b = repo.get("b")
        assert item_a.status == MemoryStatus.DEPRECATED
        assert item_b.status == MemoryStatus.ACTIVE

    def test_resolve_conflict_reject_new(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        repo.save(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        repo.save(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs", title="Pets", confidence=0.7,
        ))

        resolver = MemoryConflictResolver(repo)
        candidates = resolver.detect_conflicts(MemoryType.USER_PROFILE)
        result = resolver.resolve_conflict(candidates[0].id, accept_new=False)
        assert result is not None
        assert result.status == ConflictStatus.REJECTED

        item_a = repo.get("a")
        item_b = repo.get("b")
        assert item_a.status == MemoryStatus.ACTIVE
        assert item_b.status == MemoryStatus.DEPRECATED

    def test_resolve_already_resolved_returns_none(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        repo.save(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        repo.save(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs", title="Pets", confidence=0.7,
        ))

        resolver = MemoryConflictResolver(repo)
        candidates = resolver.detect_conflicts(MemoryType.USER_PROFILE)
        resolver.resolve_conflict(candidates[0].id, accept_new=True)
        result = resolver.resolve_conflict(candidates[0].id, accept_new=False)
        assert result is None

    def test_list_pending_vs_list_all(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        repo.save(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        repo.save(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs", title="Pets", confidence=0.7,
        ))

        resolver = MemoryConflictResolver(repo)
        resolver.detect_conflicts(MemoryType.USER_PROFILE)
        assert len(resolver.list_pending()) == 1
        assert len(resolver.list_all()) == 1

        candidates = resolver.list_pending()
        resolver.resolve_conflict(candidates[0].id, accept_new=True)
        assert len(resolver.list_pending()) == 0
        assert len(resolver.list_all()) == 1


class TestMemoryServiceConflicts:
    def test_detect_conflicts_through_service(self, tmp_path: Path):
        service = _make_service(tmp_path)
        service.save_memory(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        service.save_memory(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs", title="Pets", confidence=0.7,
        ))

        candidates = service.detect_conflicts(MemoryType.USER_PROFILE)
        assert len(candidates) == 1

    def test_list_pending_conflicts_through_service(self, tmp_path: Path):
        service = _make_service(tmp_path)
        service.save_memory(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        service.save_memory(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs", title="Pets", confidence=0.7,
        ))
        service.detect_conflicts(MemoryType.USER_PROFILE)
        assert len(service.list_pending_conflicts()) == 1

    def test_resolve_conflict_through_service(self, tmp_path: Path):
        service = _make_service(tmp_path)
        service.save_memory(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        service.save_memory(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs", title="Pets", confidence=0.7,
        ))
        candidates = service.detect_conflicts(MemoryType.USER_PROFILE)
        ok = service.resolve_conflict(candidates[0].id, accept_new=True)
        assert ok is True
        assert len(service.list_pending_conflicts()) == 0


class TestMemoryControlServiceConflicts:
    def test_list_conflicts_includes_candidates(self, tmp_path: Path):
        service = _make_service(tmp_path)
        service.save_memory(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        service.save_memory(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs", title="Pets", confidence=0.7,
        ))
        service.detect_conflicts(MemoryType.USER_PROFILE)

        settings = _make_settings(tmp_path)
        control = MemoryControlService(settings, memory_service=service, repo=service._repo)
        conflicts = control.list_conflicts()
        assert len(conflicts) == 2

        candidate_entries = [c for c in conflicts if c.get("type") == "conflict_candidate"]
        assert len(candidate_entries) == 1
        assert candidate_entries[0]["conflict_type"] == "different_value"
        assert candidate_entries[0]["existing_item"] is not None
        assert candidate_entries[0]["new_item"] is not None

    def test_resolve_conflict_through_control_service(self, tmp_path: Path):
        service = _make_service(tmp_path)
        service.save_memory(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        service.save_memory(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs", title="Pets", confidence=0.7,
        ))
        candidates = service.detect_conflicts(MemoryType.USER_PROFILE)

        settings = _make_settings(tmp_path)
        control = MemoryControlService(settings, memory_service=service, repo=service._repo)
        ok = control.resolve_conflict(candidates[0].id, accept_new=True)
        assert ok is True
        pending = control.count_pending_conflicts()
        assert pending == 0

    def test_count_pending_conflicts(self, tmp_path: Path):
        service = _make_service(tmp_path)
        control = MemoryControlService(_make_settings(tmp_path), memory_service=service, repo=service._repo)
        assert control.count_pending_conflicts() == 0

        service.save_memory(MemoryItem(
            id="a", memory_type=MemoryType.USER_PROFILE,
            content="User likes cats", title="Pets", confidence=0.9,
        ))
        service.save_memory(MemoryItem(
            id="b", memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs", title="Pets", confidence=0.7,
        ))
        service.detect_conflicts(MemoryType.USER_PROFILE)
        assert control.count_pending_conflicts() == 1


def _make_repo(tmp_path: Path) -> MemoryRepository:
    settings = _make_settings(tmp_path)
    db = Database(settings)
    return MemoryRepository(db)


def _make_service(tmp_path: Path, **kwargs) -> MemoryService:
    settings = _make_settings(tmp_path, **kwargs)
    db = Database(settings)
    repo = MemoryRepository(db)
    return MemoryService(settings, repo)


def _make_settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
        memory_conflict_identity_keys="*",
        **kwargs,
    )
