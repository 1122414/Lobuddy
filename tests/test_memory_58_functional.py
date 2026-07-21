"""Functional test script for Lobuddy 5.8 Memory System Evolution.

Run this script to verify the 5.8 implementation manually or in CI:

    python tests/test_memory_58_functional.py

Requires:
    - pip install -e lib/nanobot
    - pip install -e .
    - pytest (for assertions)
"""

import asyncio
import os
import sys
import tempfile
import uuid

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import Settings
from core.memory.memory_conflict_resolver import MemoryConflictResolver
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    ConflictStatus,
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
from core.storage.db import Database


def make_test_settings(tmpdir: str) -> Settings:
    return Settings(
        llm_api_key="test-key",
        data_dir=tmpdir,
        logs_dir=os.path.join(tmpdir, "logs"),
        workspace_path=os.path.join(tmpdir, "workspace"),
        memory_enable_migration=False,
    )


def test_memory_control_service_crud():
    """P1-C1: Memory console CRUD operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = make_test_settings(tmpdir)
        db = Database(settings)
        repo = MemoryRepository(db)
        service = MemoryService(settings, repo=repo)
        control = MemoryControlService(settings=settings, memory_service=service, repo=repo)

        item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="User Preference",
            content="User likes dark mode",
            confidence=0.9,
            importance=0.8,
        )
        repo.save(item)

        items = control.list_memories()
        assert len(items) >= 1
        assert any(i.id == item.id for i in items)

        found = control.get_memory(item.id)
        assert found is not None
        assert found.id == item.id

        ok = control.edit_memory(item.id, "User likes light mode")
        assert ok is True
        updated = repo.get(item.id)
        assert updated.content == "User likes light mode"

        ok = control.deprecate_memory(item.id)
        assert ok is True
        deprecated = repo.get(item.id)
        assert deprecated.status == MemoryStatus.DEPRECATED

        ok = control.delete_memory(item.id)
        assert ok is True
        assert repo.get(item.id) is None

        print("  PASS: MemoryControlService CRUD")


def test_provenance_display():
    """P1-C2: Provenance tracking and display."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = make_test_settings(tmpdir)
        db = Database(settings)
        repo = MemoryRepository(db)
        service = MemoryService(settings, repo=repo)
        control = MemoryControlService(settings=settings, memory_service=service, repo=repo)

        item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="User Name",
            content="Alice",
            source="ai",
            source_session_id="sess-123",
            source_message_id="msg-456",
            confidence=0.95,
            importance=0.9,
        )
        repo.save(item)

        prov = control.get_provenance(item)
        assert prov.has_precise_source is True
        assert prov.source == "ai"
        assert prov.confidence == 0.95
        assert prov.importance == 0.9

        legacy = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="Legacy",
            content="Old data",
            source="migration",
        )
        repo.save(legacy)
        legacy_prov = control.get_provenance(legacy)
        assert legacy_prov.has_precise_source is False

        print("  PASS: Provenance display")


def test_conflict_detection():
    """P1-C3: Memory conflict detection and resolution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = make_test_settings(tmpdir)
        db = Database(settings)
        repo = MemoryRepository(db)

        resolver = MemoryConflictResolver(repo)

        existing = MemoryItem(
            id="existing",
            memory_type=MemoryType.USER_PROFILE,
            content="User likes cats",
            title="Pets",
            confidence=0.9,
        )
        new_item = MemoryItem(
            id="new",
            memory_type=MemoryType.USER_PROFILE,
            content="User likes dogs",
            title="Pets",
            confidence=0.7,
        )
        repo.save(existing)
        repo.save(new_item)

        candidates = resolver.detect_conflicts(MemoryType.USER_PROFILE)
        assert len(candidates) == 1
        assert candidates[0].conflict_type.value == "different_value"

        resolved = resolver.resolve_conflict(candidates[0].id, accept_new=True)
        assert resolved.status == ConflictStatus.RESOLVED
        assert repo.get("existing").status == MemoryStatus.DEPRECATED
        assert repo.get("new").status == MemoryStatus.ACTIVE

        print("  PASS: Conflict detection and resolution")


def test_privacy_mode():
    """P1-C4: Privacy mode blocking memory writes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = make_test_settings(tmpdir)
        settings.privacy_mode_enabled = False
        db = Database(settings)
        repo = MemoryRepository(db)
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
        context = WriteContext(source="ai_patch", session_id="sess-normal", triggered_by="adapter")

        async def _normal():
            result = await gateway.submit_patch(patch, context)
            assert len(result.accepted) == 1

        asyncio.run(_normal())

        privacy.enable_privacy("sess-private")
        context_priv = WriteContext(
            source="ai_patch", session_id="sess-private", triggered_by="adapter"
        )

        async def _private():
            result = await gateway.submit_patch(patch, context_priv)
            assert len(result.accepted) == 0
            assert len(result.rejected) == 0

        asyncio.run(_private())

        try:
            gateway.submit_identity_memory(
                memory_type=MemoryType.USER_PROFILE,
                title="name",
                content="Alice",
                context=WriteContext(
                    source="strong_signal", session_id="sess-private", triggered_by="adapter"
                ),
            )
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Privacy mode active" in str(e)

        print("  PASS: Privacy mode blocking")


def test_chat_history_privacy_control():
    """P1-C4: Chat history saving respects privacy_mode_allow_chat_history."""
    from app.ui_controller import UiController
    from unittest.mock import MagicMock

    with tempfile.TemporaryDirectory() as tmpdir:
        settings = make_test_settings(tmpdir)
        settings.privacy_mode_enabled = True
        settings.privacy_mode_allow_chat_history = False

        container = MagicMock()
        container.settings = settings
        container.services = MagicMock()
        container.services.privacy_manager = PrivacyModeManager(settings)

        controller = UiController(container)

        container.services.privacy_manager.enable_privacy("sess-private")
        should_save = controller._should_save_chat_history("sess-private")
        assert should_save is False

        container.services.privacy_manager.disable_privacy("sess-normal")
        should_save_normal = controller._should_save_chat_history("sess-normal")
        assert should_save_normal is True

        print("  PASS: Chat history privacy control")


def test_sanitization():
    """Security: Memory content sanitization."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = make_test_settings(tmpdir)
        db = Database(settings)
        repo = MemoryRepository(db)
        service = MemoryService(settings, repo=repo)
        control = MemoryControlService(settings=settings, memory_service=service, repo=repo)

        api_key = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
        item = MemoryItem(
            id=str(uuid.uuid4()),
            memory_type=MemoryType.USER_PROFILE,
            title="Secret",
            content=f"API key: {api_key}",
        )
        repo.save(item)

        masked = control.get_sanitized_content(item, show_full=False)
        assert "sk-***" in masked
        assert "abcdefghijklmnopqrstuvwxyz123456" not in masked

        print("  PASS: Content sanitization")


def test_memory_console_ui_entry_point():
    """P1-C1: Memory console UI has an entry point from pet window."""
    from ui.pet_window import PetWindow
    from PySide6.QtCore import Signal

    # Verify signal exists
    assert hasattr(PetWindow, "memory_console_requested")
    assert isinstance(getattr(PetWindow, "memory_console_requested"), Signal)

    print("  PASS: Memory console UI entry point")


def run_all_tests():
    print("=" * 60)
    print("Lobuddy 5.8 Memory System Functional Tests")
    print("=" * 60)

    tests = [
        test_memory_control_service_crud,
        test_provenance_display,
        test_conflict_detection,
        test_privacy_mode,
        test_chat_history_privacy_control,
        test_sanitization,
        test_memory_console_ui_entry_point,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test.__name__} - {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
