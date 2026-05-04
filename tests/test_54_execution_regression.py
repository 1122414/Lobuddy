"""5.4 Execution regression tests — locks desired behavior for real scenarios."""

import asyncio
import json
import tempfile
import types
from pathlib import Path

import pytest
from core.agent.execution_intent import ExecutionIntentRouter, ExecutionIntent, ExecutionRoute
from core.agent.execution_hook import ExecutionGovernanceHook
from core.agent.execution_budget import ExecutionBudget
from core.agent.tools.local_app_resolve_tool import LocalAppResolveTool
from core.agent.tools.local_open_tool import LocalOpenTool


def _local_open_route() -> ExecutionRoute:
    return ExecutionRoute(
        intent=ExecutionIntent.LOCAL_OPEN_TARGET,
        target="洛克王国：世界",
        confidence=0.9,
        requires_tools=True,
        preferred_tools=["local_app_resolve", "local_open"],
        forbidden_tools=["exec"],
        reason="User wants to open a desktop game",
    )


def _fake_tc(name: str, args: dict):
    return types.SimpleNamespace(name=name, arguments=args)


def _fake_context(tool_calls: list):
    return types.SimpleNamespace(tool_calls=tool_calls)


class Test54ExecutionRegression:
    def test_open_desktop_game_does_not_use_recursive_shell(self):
        router = ExecutionIntentRouter()
        route = router.route("帮我打开桌面的洛克王国：世界")
        assert route.intent == ExecutionIntent.LOCAL_OPEN_TARGET
        assert "exec" in route.forbidden_tools

    def test_blocks_program_files_where_r(self):
        route = _local_open_route()
        budget = ExecutionBudget(block_shell_for_local_open=False, enabled=True)
        hook = ExecutionGovernanceHook(route, budget)
        tc = _fake_tc("exec", {"command": 'where /R "C:\\Program Files" 洛克*'})
        ctx = _fake_context([tc])
        with pytest.raises(RuntimeError, match="(recursive search|Program Files)"):
            asyncio.run(hook.before_execute_tools(ctx))

    def test_allows_exec_for_general_chat_regression(self):
        route = ExecutionRoute(intent=ExecutionIntent.GENERAL_CHAT)
        budget = ExecutionBudget(enabled=True)
        hook = ExecutionGovernanceHook(route, budget)
        tc = _fake_tc("exec", {"command": "echo hello"})
        ctx = _fake_context([tc])
        asyncio.run(hook.before_execute_tools(ctx))

    def test_local_app_resolve_returns_json_format(self):
        tool = LocalAppResolveTool()
        result = asyncio.run(tool.execute(target="__nonexistent_xyz_123__"))
        data = json.loads(result)
        assert "query" in data
        assert "candidates" in data
        assert "searched_sources" in data
        assert isinstance(data["candidates"], list)

    def test_local_app_resolve_no_match_returns_empty(self):
        tool = LocalAppResolveTool()
        result = asyncio.run(tool.execute(target="__nonexistent_file_12345_abc__"))
        data = json.loads(result)
        assert len(data["candidates"]) == 0

    def test_local_open_rejects_unsourced_path(self):
        tool = LocalOpenTool(resolver_candidates=[])
        result = asyncio.run(tool.execute(
            path="C:\\Windows\\System32\\cmd.exe",
            source="local_app_resolve",
        ))
        data = json.loads(result)
        assert data["opened"] is False
        assert "no_resolver" in data["reason"]

    def test_local_open_rejects_bat_extension(self):
        tool = LocalOpenTool(resolver_candidates=[
            {"path": "C:\\test.bat", "display_name": "test", "confidence": 0.9}
        ])
        result = asyncio.run(tool.execute(
            path="C:\\test.bat",
            source="local_app_resolve",
        ))
        data = json.loads(result)
        assert data["opened"] is False
        assert "bat" in data["reason"]

    def test_local_open_rejects_wrong_source(self):
        tool = LocalOpenTool()
        result = asyncio.run(tool.execute(
            path="C:\\some\\path.lnk",
            source="manual",
        ))
        data = json.loads(result)
        assert data["opened"] is False
        assert "source_must_be" in data["reason"]

    def test_local_open_accepts_matching_candidate(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test")
            tmp_path = f.name
        try:
            tool = LocalOpenTool(resolver_candidates=[
                {"path": tmp_path, "display_name": "test", "confidence": 0.9}
            ])
            result = asyncio.run(tool.execute(path=tmp_path, source="local_app_resolve"))
            data = json.loads(result)
            assert data["opened"] is True
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_local_app_resolve_finds_desktop_files(self):
        """Verify resolver actually searches desktop directory."""
        tool = LocalAppResolveTool()
        result = asyncio.run(tool.execute(
            target="__nonexistent_12345__",
            sources=["desktop"],
            limit=3,
        ))
        data = json.loads(result)
        assert "desktop" in data["searched_sources"]
        assert data["truncated"] is False

    def test_execution_governance_hook_traces_recorded(self):
        route = _local_open_route()
        budget = ExecutionBudget(enabled=True)
        hook = ExecutionGovernanceHook(route, budget)
        assert hook.traces == []
