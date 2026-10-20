"""Phase A: Memory write boundary tests.

Verifies:
  - Adapter strong signal writes go through gateway (not direct MemoryService)
  - AI memory update uses gateway.submit_patch()
  - ExitAnalyzer writes go through gateway when available
  - Gateway uses memory_gateway_* settings
  - Gateway enriches provenance
  - Rejection reasons are structured
"""

import asyncio
import uuid
from pathlib import Path

import pytest

from core.config import Settings
from core.storage.db import Database


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _make_settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
        **kwargs,
    )


def _make_memory_service(tmp_path: Path, **kwargs):
    from core.memory.memory_repository import MemoryRepository
    from core.memory.memory_service import MemoryService

    settings = _make_settings(tmp_path, **kwargs)
    db = Database(settings)
    repo = MemoryRepository(db)
    return MemoryService(settings, repo)


def _make_gateway(tmp_path: Path, **kwargs):
    from core.memory.memory_write_gateway import MemoryWriteGateway

    service = _make_memory_service(tmp_path, **kwargs)
    settings = _make_settings(tmp_path, **kwargs)
    return MemoryWriteGateway(service, settings)


# ──────────────────────────────────────────────────────────────
# A2: Strong signal writes through gateway
# ──────────────────────────────────────────────────────────────

class TestAdapterStrongSignalGateway:
    """Verify NanobotAdapter._sync_strong_signal_memory uses gateway."""

    def test_adapter_has_gateway_attribute(self):
        from core.agent.nanobot_adapter import NanobotAdapter
        from core.config import Settings

        adapter = NanobotAdapter(Settings(llm_api_key="test"))
        assert hasattr(adapter, "_memory_gateway"), (
            "Adapter must have _memory_gateway attribute"
        )
        assert adapter._memory_gateway is None  # None until set

    def test_set_memory_gateway_exists(self):
        from core.agent.nanobot_adapter import NanobotAdapter
        from core.config import Settings

        adapter = NanobotAdapter(Settings(llm_api_key="test"))
        assert hasattr(adapter, "set_memory_gateway"), (
            "Adapter must have set_memory_gateway method"
        )

    def test_sync_strong_signal_accepts_session_key(self):
        import inspect
        from core.agent.nanobot_adapter import NanobotAdapter

        sig = inspect.signature(NanobotAdapter._sync_strong_signal_memory)
        params = list(sig.parameters.keys())
        assert "session_key" in params, (
            f"_sync_strong_signal_memory should have session_key parameter, got {params}"
        )

    def test_strong_signal_noop_without_gateway(self, tmp_path: Path):
        from core.agent.nanobot_adapter import NanobotAdapter
        from core.config import Settings

        adapter = NanobotAdapter(Settings(llm_api_key="test"))
        adapter._memory_service = _make_memory_service(tmp_path)
        adapter._memory_gateway = None
        # Should not raise when gateway not set — _sync_strong_signal_memory checks _memory_gateway
        adapter._sync_strong_signal_memory("My name is Alice", session_key="test")
        assert adapter._memory_gateway is None
        # Verify the write was skipped (gateway is None)
        assert adapter._memory_service is not None  # Read-only service still available


# ──────────────────────────────────────────────────────────────
# A3: AI memory update through gateway
# ──────────────────────────────────────────────────────────────

class TestAIMemoryUpdateGateway:
    """Verify _run_memory_update uses gateway.submit_patch()."""

    def test_parse_ai_response_to_patch_exists(self, tmp_path: Path):
        service = _make_memory_service(tmp_path)
        assert hasattr(service, "parse_ai_response_to_patch"), (
            "MemoryService must have parse_ai_response_to_patch method"
        )

    def test_parse_valid_json_patch(self, tmp_path: Path):
        from core.memory.memory_schema import MemoryPatch

        service = _make_memory_service(tmp_path)
        patch = service.parse_ai_response_to_patch(
            '{"memory_type": "project_memory", "action": "add", '
            '"content": "Test memory", "confidence": 0.9, "importance": 0.7}'
        )
        assert patch is not None
        assert isinstance(patch, MemoryPatch)
        assert len(patch.items) == 1
        assert patch.items[0].content == "Test memory"

    def test_parse_json_array_patch(self, tmp_path: Path):
        service = _make_memory_service(tmp_path)
        patch = service.parse_ai_response_to_patch(
            '[{"memory_type": "project_memory", "action": "add", '
            '"content": "Item A", "confidence": 0.9, "importance": 0.7},'
            '{"memory_type": "user_profile", "action": "add", '
            '"content": "Item B", "confidence": 0.8, "importance": 0.6}]'
        )
        assert patch is not None
        assert len(patch.items) == 2

    def test_parse_empty_response_returns_none(self, tmp_path: Path):
        service = _make_memory_service(tmp_path)
        patch = service.parse_ai_response_to_patch("No JSON here")
        assert patch is None

    def test_parse_invalid_json_returns_none(self, tmp_path: Path):
        service = _make_memory_service(tmp_path)
        patch = service.parse_ai_response_to_patch("{invalid")
        assert patch is None

    def test_run_memory_update_noop_without_gateway(self, tmp_path: Path):
        from core.agent.nanobot_adapter import NanobotAdapter
        from core.config import Settings

        adapter = NanobotAdapter(Settings(llm_api_key="test"))
        adapter._memory_service = _make_memory_service(tmp_path)
        adapter._memory_gateway = None
        # Should not raise — returns early when gateway is None
        async def run():
            await adapter._run_memory_update("test-session")
        asyncio.run(run())


# ──────────────────────────────────────────────────────────────
# A4: ExitAnalyzer gateway migration
# ──────────────────────────────────────────────────────────────

class TestExitAnalyzerGateway:
    """Verify ExitAnalyzer uses gateway when available."""

    def test_exit_analyzer_accepts_gateway(self, tmp_path: Path):
        from core.memory.exit_analyzer import ExitAnalyzer
        from core.storage.db import get_database

        service = _make_memory_service(tmp_path)
        settings = _make_settings(tmp_path)
        gateway = _make_gateway(tmp_path)
        get_database(settings)

        analyzer = ExitAnalyzer(settings, service, gateway=gateway)
        assert analyzer._gateway is gateway

    def test_exit_analyzer_requires_gateway(self, tmp_path: Path):
        from core.memory.exit_analyzer import ExitAnalyzer
        from core.storage.db import get_database

        service = _make_memory_service(tmp_path)
        settings = _make_settings(tmp_path)
        get_database(settings)

        with pytest.raises(TypeError, match="gateway"):
            ExitAnalyzer(settings, service)


# ──────────────────────────────────────────────────────────────
# A5: Gateway real strategy
# ──────────────────────────────────────────────────────────────

class TestGatewayRealStrategy:
    """Verify gateway uses memory_gateway_* settings and provenance."""

    def test_gateway_uses_gateway_min_confidence(self, tmp_path: Path):
        gateway = _make_gateway(tmp_path, memory_gateway_min_confidence=0.9)
        assert gateway._min_confidence == 0.9

    def test_gateway_uses_gateway_max_items(self, tmp_path: Path):
        gateway = _make_gateway(tmp_path, memory_gateway_max_items_per_patch=3)
        assert gateway._max_items == 3

    def test_gateway_rejects_low_confidence(self, tmp_path: Path):
        from core.memory.memory_schema import MemoryPatch, MemoryPatchItem, MemoryPatchAction, MemoryType
        from core.memory.memory_write_gateway import WriteContext

        gateway = _make_gateway(tmp_path, memory_gateway_min_confidence=0.9)
        patch = MemoryPatch(items=[
            MemoryPatchItem(
                memory_type=MemoryType.PROJECT_MEMORY,
                action=MemoryPatchAction.ADD,
                content="Low confidence memory",
                confidence=0.5,
                importance=0.3,
            )
        ])
        context = WriteContext(source="ai_patch", triggered_by="test")

        async def run():
            return await gateway.submit_patch(patch, context)

        result = asyncio.run(run())
        assert len(result.accepted) == 0
        assert len(result.rejected) > 0
        assert result.rejected[0].reason == "low_confidence"

    def test_gateway_routes_needs_review(self, tmp_path: Path):
        from core.memory.memory_schema import MemoryPatch, MemoryPatchItem, MemoryPatchAction, MemoryType
        from core.memory.memory_write_gateway import WriteContext

        gateway = _make_gateway(tmp_path, memory_gateway_min_confidence=0.9)
        patch = MemoryPatch(items=[
            MemoryPatchItem(
                memory_type=MemoryType.USER_PROFILE,
                action=MemoryPatchAction.ADD,
                content="Important but uncertain memory",
                confidence=0.55,
                importance=0.95,
            )
        ])
        context = WriteContext(source="ai_patch", triggered_by="test")

        async def run():
            return await gateway.submit_patch(patch, context)

        result = asyncio.run(run())
        # Low confidence + high importance → needs_review (not rejected)
        assert len(result.needs_review) > 0, (
            f"Expected needs_review for high-importance/low-confidence. "
            f"Got accepted={len(result.accepted)} rejected={len(result.rejected)} needs_review={len(result.needs_review)}"
        )

    def test_gateway_enriches_provenance(self, tmp_path: Path):
        from core.memory.memory_schema import MemoryPatch, MemoryPatchItem, MemoryPatchAction, MemoryType
        from core.memory.memory_write_gateway import WriteContext

        gateway = _make_gateway(tmp_path)
        patch = MemoryPatch(items=[
            MemoryPatchItem(
                memory_type=MemoryType.PROJECT_MEMORY,
                action=MemoryPatchAction.ADD,
                content="Provenance test memory",
                confidence=0.95,
                importance=0.8,
            )
        ])
        context = WriteContext(
            source="ai_patch",
            session_id="test-session-123",
            triggered_by="test",
        )

        async def run():
            return await gateway.submit_patch(patch, context)

        result = asyncio.run(run())
        assert len(result.accepted) > 0
        accepted = result.accepted[0]
        assert accepted.source == "ai_patch", f"Expected source='ai_patch', got '{accepted.source}'"
        assert accepted.source_session_id == "test-session-123"

    def test_gateway_budget_enforced(self, tmp_path: Path):
        from core.memory.memory_schema import MemoryPatch, MemoryPatchItem, MemoryPatchAction, MemoryType
        from core.memory.memory_write_gateway import WriteContext

        gateway = _make_gateway(tmp_path, memory_gateway_max_items_per_patch=2)
        items = []
        for i in range(5):
            items.append(MemoryPatchItem(
                memory_type=MemoryType.PROJECT_MEMORY,
                action=MemoryPatchAction.ADD,
                content=f"Item {i}",
                confidence=0.9,
                importance=0.5,
            ))
        patch = MemoryPatch(items=items)
        context = WriteContext(source="ai_patch", triggered_by="test")

        async def run():
            return await gateway.submit_patch(patch, context)

        result = asyncio.run(run())
        # Only first 2 items processed
        assert result.total_processed <= 2, (
            f"Budget of 2 items exceeded: total_processed={result.total_processed}"
        )

    def test_gateway_rejects_empty_content(self, tmp_path: Path):
        from core.memory.memory_schema import MemoryPatch, MemoryPatchItem, MemoryPatchAction, MemoryType
        from core.memory.memory_write_gateway import WriteContext

        gateway = _make_gateway(tmp_path)
        patch = MemoryPatch(items=[
            MemoryPatchItem(
                memory_type=MemoryType.PROJECT_MEMORY,
                action=MemoryPatchAction.ADD,
                content="   ",
                confidence=0.9,
                importance=0.5,
            )
        ])
        context = WriteContext(source="ai_patch", triggered_by="test")

        async def run():
            return await gateway.submit_patch(patch, context)

        result = asyncio.run(run())
        assert len(result.rejected) > 0
        assert result.rejected[0].reason == "empty_content"

    def test_gateway_provenance_persisted_to_sqlite(self, tmp_path: Path):
        from core.memory.memory_schema import MemoryPatch, MemoryPatchItem, MemoryPatchAction, MemoryType
        from core.memory.memory_write_gateway import WriteContext

        service = _make_memory_service(tmp_path)
        settings = _make_settings(tmp_path)
        gateway = _make_gateway(tmp_path)

        patch = MemoryPatch(items=[
            MemoryPatchItem(
                memory_type=MemoryType.PROJECT_MEMORY,
                action=MemoryPatchAction.ADD,
                content="Provenance test item",
                confidence=0.9,
                importance=0.5,
            )
        ])
        context = WriteContext(
            source="ai_patch",
            session_id="session-123",
            message_id="message-456",
            triggered_by="test",
        )

        async def run():
            return await gateway.submit_patch(patch, context)

        result = asyncio.run(run())
        assert len(result.accepted) == 1

        loaded = service.get_memory(result.accepted[0].id)
        assert loaded is not None, "Memory should be retrievable from SQLite"
        assert loaded.source == "ai_patch", f"Expected source='ai_patch', got '{loaded.source}'"
        assert loaded.source_session_id == "session-123", (
            f"Expected source_session_id='session-123', got '{loaded.source_session_id}'"
        )
        assert loaded.source_message_id == "message-456", (
            f"Expected source_message_id='message-456', got '{loaded.source_message_id}'"
        )

    def test_gateway_confidence_not_overridden_by_memory_service(self, tmp_path: Path):
        from core.memory.memory_schema import MemoryPatch, MemoryPatchItem, MemoryPatchAction, MemoryType
        from core.memory.memory_write_gateway import WriteContext

        settings = _make_settings(
            tmp_path,
            memory_gateway_min_confidence=0.5,
            memory_min_confidence=0.95,
        )
        from core.memory.memory_repository import MemoryRepository
        from core.memory.memory_service import MemoryService
        from core.storage.db import Database
        from core.memory.memory_write_gateway import MemoryWriteGateway

        db = Database(settings)
        db.init_database()
        repo = MemoryRepository(db)
        service = MemoryService(settings, repo)
        gateway = MemoryWriteGateway(service, settings)

        patch = MemoryPatch(items=[
            MemoryPatchItem(
                memory_type=MemoryType.PROJECT_MEMORY,
                action=MemoryPatchAction.ADD,
                content="Confidence isolation test",
                confidence=0.7,
                importance=0.5,
            )
        ])
        context = WriteContext(source="test", triggered_by="test")

        async def run():
            return await gateway.submit_patch(patch, context)

        result = asyncio.run(run())
        assert len(result.accepted) == 1, (
            f"Item with confidence 0.7 should be accepted through gateway "
            f"(gateway_min_confidence=0.5), but memory_min_confidence=0.95 "
            f"should NOT block it. Got accepted={len(result.accepted)}"
        )

        loaded = service.get_memory(result.accepted[0].id)
        assert loaded is not None, "Accepted item should persist to SQLite"


# ──────────────────────────────────────────────────────────────
# Integration: Full write boundary
# ──────────────────────────────────────────────────────────────

class TestWriteBoundaryIntegration:
    """End-to-end: write through gateway, verify in SQLite and projection."""

    def test_full_write_pipeline(self, tmp_path: Path):
        """Write via gateway → verify SQLite → verify projection."""
        from core.memory.memory_schema import MemoryPatch, MemoryPatchItem, MemoryPatchAction, MemoryType, MemoryStatus
        from core.memory.memory_write_gateway import WriteContext

        service = _make_memory_service(tmp_path)
        settings = _make_settings(tmp_path)
        gateway = _make_gateway(tmp_path)

        # Write through gateway
        patch = MemoryPatch(items=[
            MemoryPatchItem(
                memory_type=MemoryType.PROJECT_MEMORY,
                action=MemoryPatchAction.ADD,
                content="Integration test: write boundary verified",
                confidence=0.95,
                importance=0.85,
            )
        ])
        context = WriteContext(
            source="test",
            session_id="integration-session",
            triggered_by="integration_test",
        )

        async def run():
            return await gateway.submit_patch(patch, context)

        result = asyncio.run(run())
        assert len(result.accepted) == 1
        mem = result.accepted[0]
        assert "Integration test" in mem.content
        assert mem.source == "test"
        assert mem.source_session_id == "integration-session"

        # Verify in SQLite
        loaded = service.get_memory(mem.id)
        assert loaded is not None
        assert loaded.content == mem.content

        # Verify projection
        project_md = tmp_path / "data" / "memory" / "PROJECT.md"
        assert project_md.exists()
        content = project_md.read_text(encoding="utf-8")
        assert "write boundary verified" in content

        # Verify workspace MEMORY.md
        memory_md = tmp_path / "workspace" / "memory" / "MEMORY.md"
        assert memory_md.exists()


# ──────────────────────────────────────────────────────────────
# A6: Identity memory provenance (6.1, 6.2)
# ──────────────────────────────────────────────────────────────

class TestIdentityMemoryProvenance:
    """Verify identity memory provenance (source_session_id/source_message_id) is
    persisted to SQLite and returned objects match."""

    def test_identity_new_persists_provenance(self, tmp_path: Path):
        """6.1: New identity memory writes provenance to SQLite."""
        from core.memory.memory_schema import MemoryType
        from core.memory.memory_write_gateway import WriteContext

        service = _make_memory_service(tmp_path)
        settings = _make_settings(tmp_path)

        from core.memory.memory_write_gateway import MemoryWriteGateway
        gateway = MemoryWriteGateway(service, settings)

        context = WriteContext(
            source="strong_signal",
            session_id="session-1",
            message_id="message-1",
            triggered_by="adapter",
        )

        result = gateway.submit_identity_memory(
            memory_type=MemoryType.USER_PROFILE,
            title="Basic Notes",
            content="The user's name is Alice.",
            context=context,
        )

        # Returned object must carry provenance
        assert result.source == "strong_signal"
        assert result.source_session_id == "session-1"
        assert result.source_message_id == "message-1"

        # SQLite read-back must match
        loaded = service.get_memory(result.id)
        assert loaded is not None, "Identity memory should be retrievable from SQLite"
        assert loaded.source == "strong_signal", (
            f"Expected source='strong_signal', got '{loaded.source}'"
        )
        assert loaded.source_session_id == "session-1", (
            f"Expected source_session_id='session-1', got '{loaded.source_session_id}'"
        )
        assert loaded.source_message_id == "message-1", (
            f"Expected source_message_id='message-1', got '{loaded.source_message_id}'"
        )

    def test_identity_existing_updates_provenance(self, tmp_path: Path):
        """6.2: Re-confirming identity updates provenance to most recent."""
        from core.memory.memory_schema import MemoryType
        from core.memory.memory_write_gateway import WriteContext

        service = _make_memory_service(tmp_path)
        settings = _make_settings(tmp_path)

        from core.memory.memory_write_gateway import MemoryWriteGateway
        gateway = MemoryWriteGateway(service, settings)

        # First write
        context_1 = WriteContext(
            source="strong_signal",
            session_id="session-1",
            message_id="message-1",
            triggered_by="adapter",
        )
        result_1 = gateway.submit_identity_memory(
            memory_type=MemoryType.USER_PROFILE,
            title="Basic Notes",
            content="The user's name is Alice.",
            context=context_1,
        )
        assert result_1.source_session_id == "session-1"

        # Second write — same identity, different session
        context_2 = WriteContext(
            source="exit_analysis",
            session_id="session-2",
            message_id="message-2",
            triggered_by="exit_analysis",
        )
        result_2 = gateway.submit_identity_memory(
            memory_type=MemoryType.USER_PROFILE,
            title="Basic Notes",
            content="The user's name is Alice.",
            context=context_2,
        )

        # Same item id (upserted)
        assert result_2.id == result_1.id

        # Provenance should now reflect most recent (session-2, exit_analysis)
        assert result_2.source == "exit_analysis"
        assert result_2.source_session_id == "session-2"
        assert result_2.source_message_id == "message-2"

        # SQLite read-back must match
        loaded = service.get_memory(result_2.id)
        assert loaded is not None
        assert loaded.source == "exit_analysis", (
            f"Expected source updated to 'exit_analysis', got '{loaded.source}'"
        )
        assert loaded.source_session_id == "session-2", (
            f"Expected source_session_id updated to 'session-2', got '{loaded.source_session_id}'"
        )
        assert loaded.source_message_id == "message-2", (
            f"Expected source_message_id updated to 'message-2', got '{loaded.source_message_id}'"
        )

    def test_identity_provenance_return_equals_sqlite(self, tmp_path: Path):
        """Gateway return object must match SQLite get_memory() for identity writes."""
        from core.memory.memory_schema import MemoryType
        from core.memory.memory_write_gateway import WriteContext

        service = _make_memory_service(tmp_path)
        settings = _make_settings(tmp_path)

        from core.memory.memory_write_gateway import MemoryWriteGateway
        gateway = MemoryWriteGateway(service, settings)

        context = WriteContext(
            source="exit_analysis",
            session_id="session-abc",
            message_id="message-xyz",
            triggered_by="exit_analysis",
        )

        result = gateway.submit_identity_memory(
            memory_type=MemoryType.SYSTEM_PROFILE,
            title="Identity",
            content="My name is Lobuddy. I am an AI desktop pet assistant.",
            context=context,
        )

        loaded = service.get_memory(result.id)
        assert loaded is not None
        assert loaded.source == result.source
        assert loaded.source_session_id == result.source_session_id
        assert loaded.source_message_id == result.source_message_id
        assert loaded.content == result.content
        assert loaded.memory_type == result.memory_type


# ──────────────────────────────────────────────────────────────
# A7: ExitAnalyzer session provenance (6.3)
# ──────────────────────────────────────────────────────────────

class TestExitAnalyzerSessionProvenance:
    """Verify ExitAnalyzer passes session_id into WriteContext for
    identity/preference writes."""

    def _make_fake_gateway(self, tmp_path: Path):
        """Create a fake gateway that captures WriteContext arguments."""
        from core.memory.memory_schema import MemoryItem, MemoryType
        from core.memory.memory_write_gateway import WriteContext

        captured_contexts: list[WriteContext] = []
        captured_identities: list[tuple] = []

        class FakeGateway:
            def __init__(self, gateway, service):
                self._real_gateway = gateway
                self._service = service

            def submit_identity_memory(self, memory_type, title, content, context, confidence=0.95, importance=0.9):
                captured_contexts.append(context)
                captured_identities.append((memory_type, title, content))
                return self._real_gateway.submit_identity_memory(
                    memory_type=memory_type, title=title, content=content,
                    context=context, confidence=confidence, importance=importance)

            async def submit_patch(self, patch, context):
                captured_contexts.append(context)
                return await self._real_gateway.submit_patch(patch, context)

            # Delegate __getattr__ for other attributes
            def __getattr__(self, name):
                return getattr(self._real_gateway, name)

        service = _make_memory_service(tmp_path)
        settings = _make_settings(tmp_path)

        from core.memory.memory_write_gateway import MemoryWriteGateway
        real_gateway = MemoryWriteGateway(service, settings)
        fake = FakeGateway(real_gateway, service)

        # Attach captured data
        fake.captured_contexts = captured_contexts  # type: ignore[attr-defined]
        fake.captured_identities = captured_identities  # type: ignore[attr-defined]
        return fake, service, settings

    def test_persist_identity_passes_session_id_to_writecontext(self, tmp_path: Path):
        """ExitAnalyzer._persist_identity must include session_id in WriteContext."""
        from core.memory.exit_analyzer import ExitAnalyzer
        from core.storage.db import get_database

        fake_gateway, service, settings = self._make_fake_gateway(tmp_path)
        get_database(settings)
        analyzer = ExitAnalyzer(settings, service, gateway=fake_gateway)

        analyzer._persist_identity(
            {"type": "user_name", "value": "Alice", "confidence": 0.95},
            session_id="session-exit-1",
        )

        assert len(fake_gateway.captured_contexts) == 1  # type: ignore[attr-defined]
        ctx = fake_gateway.captured_contexts[0]  # type: ignore[attr-defined]
        assert ctx.source == "exit_analysis", (
            f"Expected source='exit_analysis', got '{ctx.source}'"
        )
        assert ctx.session_id == "session-exit-1", (
            f"Expected session_id='session-exit-1', got '{ctx.session_id}'"
        )
        assert ctx.triggered_by == "exit_analysis", (
            f"Expected triggered_by='exit_analysis', got '{ctx.triggered_by}'"
        )

    def test_persist_preference_passes_session_id_to_writecontext(self, tmp_path: Path):
        """ExitAnalyzer._persist_preference must include session_id in WriteContext."""
        from core.memory.exit_analyzer import ExitAnalyzer
        from core.storage.db import get_database

        fake_gateway, service, settings = self._make_fake_gateway(tmp_path)
        get_database(settings)
        analyzer = ExitAnalyzer(settings, service, gateway=fake_gateway)

        analyzer._persist_preference(
            {"content": "The user prefers short answers.", "confidence": 0.8},
            session_id="session-exit-2",
        )

        contexts = fake_gateway.captured_contexts  # type: ignore[attr-defined]
        assert len(contexts) > 0, "Expected at least one WriteContext captured"
        ctx = contexts[-1]
        assert ctx.source == "exit_analysis", (
            f"Expected source='exit_analysis', got '{ctx.source}'"
        )
        assert ctx.session_id == "session-exit-2", (
            f"Expected session_id='session-exit-2', got '{ctx.session_id}'"
        )
        assert ctx.triggered_by == "exit_analysis", (
            f"Expected triggered_by='exit_analysis', got '{ctx.triggered_by}'"
        )

    def test_no_memory_service_bypass_in_exit_analyzer(self, tmp_path: Path):
        """ExitAnalyzer should not call MemoryService.upsert_identity_memory directly."""
        import inspect
        from core.memory.exit_analyzer import ExitAnalyzer

        source = inspect.getsource(ExitAnalyzer._persist_identity)
        source += inspect.getsource(ExitAnalyzer._persist_preference)

        forbidden = [
            "_memory_service.upsert_identity_memory",
            "_memory_service.save_memory",
            "_memory_service.apply_ai_response",
            "_memory_service.apply_patch",
        ]
        for pattern in forbidden:
            assert pattern not in source, (
                f"ExitAnalyzer must not call {pattern} directly — "
                f"all writes go through gateway"
            )

        # Gateway calls are expected
        assert "_gateway.submit_identity_memory" in source, (
            "ExitAnalyzer._persist_identity should use gateway.submit_identity_memory"
        )
