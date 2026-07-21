"""Regression tests for review-gated Structured Memory portability."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
from core.storage.db import Database


def _build_stack(
    root: Path,
) -> tuple[
    MemoryService,
    MemoryControlService,
    MemoryRepository,
    PrivacyModeManager,
]:
    settings = Settings(
        llm_api_key="test",
        data_dir=root / "data",
        logs_dir=root / "logs",
        workspace_path=root / "workspace",
        memory_enable_migration=False,
        user_name="",
    )
    repo = MemoryRepository(Database(settings))
    privacy = PrivacyModeManager(settings)
    service = MemoryService(settings, repo, privacy)
    gateway = MemoryWriteGateway(service, settings, privacy)
    control = MemoryControlService(
        settings,
        memory_service=service,
        repo=repo,
        gateway=gateway,
    )
    return service, control, repo, privacy


def _seed_portable_memories(service: MemoryService) -> None:
    service.save_memory(
        MemoryItem(
            id="preference",
            memory_type=MemoryType.USER_PROFILE,
            title="沟通偏好",
            content="先给结论，再补充必要细节",
            source="manual",
            source_session_id="private-session-id",
            source_message_id="private-message-id",
            importance=0.9,
        )
    )
    service.save_memory(
        MemoryItem(
            id="procedure",
            memory_type=MemoryType.PROCEDURAL_MEMORY,
            title="发布前检查",
            content="先跑测试，再整理发布说明",
            source="ai_patch",
            importance=0.8,
        )
    )


def test_export_contains_only_portable_content_and_no_provenance(tmp_path: Path) -> None:
    service, control, _repo, _privacy = _build_stack(tmp_path / "source")
    _seed_portable_memories(service)
    service.save_memory(
        MemoryItem(
            id="companion-profile",
            memory_type=MemoryType.SYSTEM_PROFILE,
            title="伙伴身份",
            content="Lobuddy 是温暖的桌面伙伴",
        )
    )
    target = tmp_path / "memories.json"

    result = control.export_memory_package(target)
    preview = control.inspect_memory_package(target)
    payload = json.loads(target.read_text(encoding="utf-8"))

    assert result.exported_count == 2
    assert preview.total_count == 2
    assert payload["format"] == "lobuddy.memory-portability"
    assert payload["version"] == 1
    assert "private-session-id" not in target.read_text(encoding="utf-8")
    assert "private-message-id" not in target.read_text(encoding="utf-8")
    assert {entry["memory_type"] for entry in payload["entries"]} == {
        MemoryType.USER_PROFILE.value,
        MemoryType.PROCEDURAL_MEMORY.value,
    }


def test_import_is_review_gated_content_minimized_and_confirmable(
    tmp_path: Path,
) -> None:
    source_service, source_control, _source_repo, _source_privacy = _build_stack(
        tmp_path / "source"
    )
    _seed_portable_memories(source_service)
    package_path = tmp_path / "memories.json"
    source_control.export_memory_package(package_path)

    _service, control, repo, _privacy = _build_stack(tmp_path / "target")
    preview = control.inspect_memory_package(package_path)
    result = control.import_memory_package(
        package_path,
        expected_file_digest=preview.file_digest,
        session_id="target-session",
    )

    assert result.imported_count == 2
    assert result.duplicate_count == 0
    imported = [repo.get(memory_id) for memory_id in result.imported_memory_ids]
    assert all(item is not None for item in imported)
    assert all(item.status == MemoryStatus.NEEDS_REVIEW for item in imported)
    assert all(item.source == "import" for item in imported)
    assert all(item.source_session_id is None for item in imported)
    assert all(item.source_message_id is None for item in imported)
    revision = repo.list_revisions(result.imported_memory_ids[0])[0]
    assert revision.revision_type == MemoryRevisionType.LEARNED
    assert revision.actor == "import"

    confirmed = control.confirm_memory(result.imported_memory_ids[0])
    assert confirmed is not None
    assert confirmed.status == MemoryStatus.ACTIVE
    assert confirmed.confidence == 1.0


def test_repeated_import_is_idempotent(tmp_path: Path) -> None:
    source_service, source_control, _source_repo, _source_privacy = _build_stack(
        tmp_path / "source"
    )
    _seed_portable_memories(source_service)
    package_path = tmp_path / "memories.json"
    source_control.export_memory_package(package_path)
    _service, control, repo, _privacy = _build_stack(tmp_path / "target")

    preview = control.inspect_memory_package(package_path)
    first = control.import_memory_package(
        package_path,
        expected_file_digest=preview.file_digest,
    )
    second_preview = control.inspect_memory_package(package_path)
    second = control.import_memory_package(
        package_path,
        expected_file_digest=second_preview.file_digest,
    )

    assert first.imported_count == 2
    assert second_preview.importable_count == 0
    assert second_preview.duplicate_count == 2
    assert second.imported_count == 0
    assert second.duplicate_count == 2
    assert repo.count(MemoryStatus.NEEDS_REVIEW) == 2


def test_import_refuses_privacy_mode_and_stale_or_tampered_files(
    tmp_path: Path,
) -> None:
    source_service, source_control, _source_repo, _source_privacy = _build_stack(
        tmp_path / "source"
    )
    _seed_portable_memories(source_service)
    package_path = tmp_path / "memories.json"
    source_control.export_memory_package(package_path)
    _service, control, _repo, privacy = _build_stack(tmp_path / "target")

    preview = control.inspect_memory_package(package_path)
    privacy.enable_privacy("private-session")
    with pytest.raises(ValueError, match="隐私模式"):
        control.import_memory_package(
            package_path,
            expected_file_digest=preview.file_digest,
            session_id="private-session",
        )

    package_path.write_text(
        package_path.read_text(encoding="utf-8") + " ",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="预览后发生了变化"):
        control.import_memory_package(
            package_path,
            expected_file_digest=preview.file_digest,
        )

    payload = json.loads(package_path.read_text(encoding="utf-8"))
    payload["entries"][0]["content"] = "被修改的内容"
    package_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="校验失败"):
        control.inspect_memory_package(package_path)


def test_import_batch_rolls_back_when_any_revision_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_service, source_control, _source_repo, _source_privacy = _build_stack(
        tmp_path / "source"
    )
    _seed_portable_memories(source_service)
    package_path = tmp_path / "memories.json"
    source_control.export_memory_package(package_path)
    _service, control, repo, _privacy = _build_stack(tmp_path / "target")
    preview = control.inspect_memory_package(package_path)
    original_write_revision = repo._write_revision
    calls = 0

    def fail_second_revision(conn, revision) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated revision failure")
        original_write_revision(conn, revision)

    monkeypatch.setattr(repo, "_write_revision", fail_second_revision)
    before = repo.count(MemoryStatus.NEEDS_REVIEW)

    with pytest.raises(RuntimeError, match="simulated revision failure"):
        control.import_memory_package(
            package_path,
            expected_file_digest=preview.file_digest,
        )

    assert repo.count(MemoryStatus.NEEDS_REVIEW) == before
    assert repo.list_imported_digests() == set()
