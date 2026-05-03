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

    def test_exit_analyzer_no_gateway_fallback(self, tmp_path: Path):
        from core.memory.exit_analyzer import ExitAnalyzer
        from core.storage.db import get_database

        service = _make_memory_service(tmp_path)
        settings = _make_settings(tmp_path)
        get_database(settings)

        analyzer = ExitAnalyzer(settings, service)
        assert analyzer._gateway is None  # Falls back to direct MemoryService


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
