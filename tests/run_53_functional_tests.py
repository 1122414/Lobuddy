#!/usr/bin/env python
"""Lobuddy 5.3 记忆系统功能测试脚本

使用方法:
    python tests/run_53_functional_tests.py

测试覆盖:
  - 5.3 设置字段完整性
  - MemoryWriteGateway 写入边界
  - SessionSearchService 冷召回
  - PromptContextBundle 热记忆分层
  - MemoryLintService 健康检查
  - SkillManager 孤儿文件清理

不依赖 UI 或网络，纯逻辑验证。
"""

import asyncio
import sys
import uuid
from pathlib import Path
from datetime import datetime


def test_settings_integrity():
    """验证所有 5.3 设置字段存在且默认值正确。"""
    from core.config import Settings

    s = Settings(llm_api_key="test")
    checks = {
        "memory_session_search_enabled": (s.memory_session_search_enabled, False),
        "memory_session_search_default_scope": (s.memory_session_search_default_scope, "current_session"),
        "memory_session_search_max_result_chars": (s.memory_session_search_max_result_chars, 300),
        "memory_session_search_total_budget_chars": (s.memory_session_search_total_budget_chars, 1500),
        "memory_gateway_min_confidence": (s.memory_gateway_min_confidence, 0.75),
        "memory_gateway_max_items_per_patch": (s.memory_gateway_max_items_per_patch, 8),
        "memory_hot_user_profile_tokens": (s.memory_hot_user_profile_tokens, 500),
        "memory_hot_system_profile_tokens": (s.memory_hot_system_profile_tokens, 300),
        "memory_hot_project_context_tokens": (s.memory_hot_project_context_tokens, 800),
        "memory_lint_enabled": (s.memory_lint_enabled, True),
        "memory_lint_duplicate_similarity": (s.memory_lint_duplicate_similarity, 0.8),
        "memory_lint_stale_days": (s.memory_lint_stale_days, 90),
        "memory_lint_low_confidence_days": (s.memory_lint_low_confidence_days, 30),
        "memory_block_dream_commands": (s.memory_block_dream_commands, True),
    }

    for name, (actual, expected) in checks.items():
        assert actual == expected, f"{name}: expected {expected}, got {actual}"

    print("[PASS] Settings integrity: all 14 fields present with correct defaults")
    return True


def test_memory_write_gateway():
    """验证 MemoryWriteGateway 提交/拒绝/待审查流程。"""
    tmp = Path("data/test_53_func")
    import shutil

    from core.config import Settings
    from core.storage.db import Database
    from core.memory.memory_repository import MemoryRepository
    from core.memory.memory_service import MemoryService
    from core.memory.memory_write_gateway import (
        MemoryWriteGateway, WriteContext, WriteResult, Rejection,
    )
    from core.memory.memory_schema import MemoryPatch, MemoryPatchItem, MemoryPatchAction, MemoryType

    try:
        settings = Settings(
            llm_api_key="test",
            data_dir=tmp / "data",
            logs_dir=tmp / "logs",
            workspace_path=tmp / "workspace",
            memory_enable_migration=False,
            memory_gateway_min_confidence=0.75,
            memory_gateway_max_items_per_patch=3,
        )
        db = Database(settings)
        db.init_database()
        repo = MemoryRepository(db)
        service = MemoryService(settings, repo)
        gateway = MemoryWriteGateway(service, settings)

        # Test 1: Accept high confidence item
        patch = MemoryPatch(items=[
            MemoryPatchItem(
                memory_type=MemoryType.PROJECT_MEMORY,
                action=MemoryPatchAction.ADD,
                content="Gateway functional test item",
                confidence=0.9,
                importance=0.7,
            )
        ])
        context = WriteContext(source="test", triggered_by="test")

        async def run():
            return await gateway.submit_patch(patch, context)

        result = asyncio.run(run())
        assert isinstance(result, WriteResult), "submit_patch should return WriteResult"
        assert len(result.accepted) == 1, "High confidence item should be accepted"
        assert len(result.rejected) == 0
        assert result.accepted[0].source == "test", "Source provenance should be set"
        print("  [PASS] High confidence item accepted with provenance")

        # Test 2: Reject low confidence item
        low_patch = MemoryPatch(items=[
            MemoryPatchItem(
                memory_type=MemoryType.EPISODIC_MEMORY,
                action=MemoryPatchAction.ADD,
                content="Low confidence test",
                confidence=0.5,
                importance=0.3,
            )
        ])
        low_result = asyncio.run(gateway.submit_patch(low_patch, context))
        assert len(low_result.rejected) == 1, "Low confidence should be rejected"
        assert low_result.rejected[0].reason == "low_confidence"
        print("  [PASS] Low confidence item rejected with reason")

        # Test 3: High importance but low confidence → needs_review
        review_patch = MemoryPatch(items=[
            MemoryPatchItem(
                memory_type=MemoryType.USER_PROFILE,
                action=MemoryPatchAction.ADD,
                content="Critical user preference",
                confidence=0.6,
                importance=0.9,
            )
        ])
        review_result = asyncio.run(gateway.submit_patch(review_patch, context))
        assert len(review_result.needs_review) == 1, "High importance + low confidence → needs_review"
        print("  [PASS] High importance / low confidence routed to needs_review")

        # Test 4: Budget enforcement
        many_patch = MemoryPatch(items=[
            MemoryPatchItem(
                memory_type=MemoryType.PROJECT_MEMORY,
                action=MemoryPatchAction.ADD,
                content=f"Budget item {i}",
                confidence=0.9,
                importance=0.5,
            )
            for i in range(10)
        ])
        many_result = asyncio.run(gateway.submit_patch(many_patch, context))
        assert many_result.total_processed == 3, f"Budget should cap at 3 items, got {many_result.total_processed}"
        print("  [PASS] Budget enforcement: max_items_per_patch=3 respected")

        print("[PASS] MemoryWriteGateway: all boundary checks pass")
        return True
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def test_session_search():
    """验证 SessionSearchService 搜索/脱敏/预算功能。"""
    tmp = Path("data/test_53_func_search")
    import shutil

    from core.config import Settings
    from core.storage.db import Database
    from core.storage.chat_repo import ChatRepository
    from core.models.chat import ChatMessage

    try:
        settings = Settings(
            llm_api_key="test",
            data_dir=tmp / "data",
            logs_dir=tmp / "logs",
            workspace_path=tmp / "workspace",
            memory_enable_migration=False,
            memory_session_search_max_result_chars=300,
            memory_session_search_total_budget_chars=500,
            memory_session_search_default_scope="current_session",
        )
        db = Database(settings)
        db.init_database()
        repo = ChatRepository(db=db)

        # Seed data with secrets
        repo.get_or_create_session("s1", pet_id="test")
        repo.save_message(ChatMessage(
            id=str(uuid.uuid4()),
            session_id="s1",
            role="user",
            content="My API key is sk-1234567890abcdef1234567890abcdef",
            created_at=datetime(2026, 5, 1, 10, 0),
        ))
        repo.save_message(ChatMessage(
            id=str(uuid.uuid4()),
            session_id="s1",
            role="assistant",
            content="I remember you like Python programming.",
            created_at=datetime(2026, 5, 1, 10, 1),
        ))

        from core.memory.session_search import SessionSearchService, SessionSearchScope

        service = SessionSearchService(settings, chat_repo=repo)

        # Test 1: Sanitization
        response = service.search("API", current_session_id="s1", limit=5)
        for r in response.results:
            assert "sk-" not in r.content, "API key should be redacted"
        print("  [PASS] API key redacted from search results")

        # Test 2: Scope enforcement
        response2 = service.search(
            "Python", current_session_id="s1",
            scope=SessionSearchScope.ALL_SESSIONS, limit=5,
        )
        assert response2.scope == "current_session", "all_sessions should be denied by settings"
        print("  [PASS] all_sessions scope enforced by settings")

        # Test 3: Empty query
        response3 = service.search("", current_session_id="s1", limit=5)
        assert "Empty query" in response3.note or response3.total_found == 0
        print("  [PASS] Empty query rejected")

        print("[PASS] SessionSearchService: search, sanitize, scope all work")
        return True
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def test_prompt_context_bundle():
    """验证 PromptContextBundle 包含新字段 project_context 和 memory_budget_report。"""
    from core.memory.memory_schema import PromptContextBundle

    bundle = PromptContextBundle(
        user_profile="User: TestUser",
        system_profile="System: Lobuddy",
        project_context="Project: 5.3 memory system",
        session_summary="Current session summary",
        retrieved_memories="Past: user likes Python",
        active_skills="- **test-skill**: A test skill",
        memory_budget_report={"user_profile": 100, "system_profile": 80, "project_context": 200},
    )

    assert bundle.project_context == "Project: 5.3 memory system"
    assert "project_context" in bundle.memory_budget_report
    assert bundle.memory_budget_report["user_profile"] == 100

    injection = bundle.build_injection_text()
    assert "### Project Context" in injection, "Project Context section should be in injection"
    assert "### User Profile" in injection
    assert "### Available Skills" in injection
    assert "Project: 5.3 memory system" in injection

    print("[PASS] PromptContextBundle: project_context + budget_report + injection order")
    return True


def test_memory_lint():
    """验证 MemoryLintService 生成报告（不崩溃）。"""
    tmp = Path("data/test_53_func_lint")
    import shutil

    from core.config import Settings
    from core.storage.db import Database
    from core.memory.memory_repository import MemoryRepository
    from core.memory.memory_schema import MemoryItem, MemoryType, MemoryStatus

    try:
        settings = Settings(
            llm_api_key="test",
            data_dir=tmp / "data",
            logs_dir=tmp / "logs",
            workspace_path=tmp / "workspace",
            memory_enable_migration=False,
            memory_lint_enabled=True,
            memory_lint_duplicate_similarity=0.8,
            memory_lint_stale_days=90,
            memory_lint_low_confidence_days=30,
        )
        db = Database(settings)
        db.init_database()
        repo = MemoryRepository(db)

        # Add some test memories
        items = [
            MemoryItem(
                id=f"t{i}",
                memory_type=MemoryType.USER_PROFILE,
                content=f"Test memory {i}",
                confidence=0.9,
                importance=0.7,
            )
            for i in range(3)
        ]
        from core.memory.memory_service import MemoryService
        service = MemoryService(settings, repo)
        for item in items:
            service.save_memory(item)

        from core.memory.memory_lint import MemoryLintReport, MemoryLintService

        lint = MemoryLintService(settings, repo=repo)
        report = lint.lint()

        assert isinstance(report, MemoryLintReport), "Lint should return MemoryLintReport"
        assert report.total_active_memories >= 3, f"Should see at least 3 active memories, got {report.total_active_memories}"

        print(f"  [PASS] MemoryLint ran: {report.total_active_memories} active memories, {len(report.findings)} findings")

        # Test disabled behavior
        disabled_settings = Settings(
            llm_api_key="test",
            data_dir=tmp / "data2",
            logs_dir=tmp / "logs2",
            workspace_path=tmp / "workspace2",
            memory_lint_enabled=False,
        )
        disabled_lint = MemoryLintService(disabled_settings, repo=repo)
        disabled_report = disabled_lint.lint()
        assert disabled_report.total_active_memories == 0, "Disabled lint should skip checks"
        print("  [PASS] Disabled lint skips checks")

        print("[PASS] MemoryLintService: lint runs and disabled mode works")
        return True
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def test_skill_orphan_cleanup():
    """验证 SkillManager.cleanup_orphan_workspace_files() 不崩溃。"""
    tmp = Path("data/test_53_func_skill")
    import shutil

    from core.config import Settings
    from core.storage.db import Database
    from core.skills.skill_manager import SkillManager

    try:
        # Create minimal workspace
        workspace = tmp / "workspace" / "skills"
        workspace.mkdir(parents=True, exist_ok=True)

        settings = Settings(
            llm_api_key="test",
            data_dir=tmp / "data",
            logs_dir=tmp / "logs",
            workspace_path=tmp / "workspace",
            memory_enable_migration=False,
        )
        db = Database(settings)
        db.init_database()
        manager = SkillManager(settings, db=db)

        removed = manager.cleanup_orphan_workspace_files()
        assert isinstance(removed, int), "cleanup should return integer count"
        print(f"  [PASS] Skill orphan cleanup: {removed} files removed from empty workspace")

        print("[PASS] SkillManager: orphan cleanup runs without error")
        return True
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("=" * 60)
    print("  Lobuddy 5.3 记忆系统功能测试")
    print("=" * 60)
    print()

    tests = [
        ("Settings Integrity", test_settings_integrity),
        ("Memory Write Gateway", test_memory_write_gateway),
        ("Session Search", test_session_search),
        ("Prompt Context Bundle", test_prompt_context_bundle),
        ("Memory Lint", test_memory_lint),
        ("Skill Orphan Cleanup", test_skill_orphan_cleanup),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n[FAIL] {name} FAILED: {e}")
            import traceback
            traceback.print_exc()

    print()
    print("=" * 60)
    print(f"  Results: {passed}/{len(tests)} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
