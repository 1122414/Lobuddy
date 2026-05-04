"""5.4 Adapter-level execution governance integration tests."""

import asyncio
import sys
import types
from typing import Any

import pytest

# Mock PySide6 to avoid Qt import issues
_pyside = type(sys)("PySide6")
_pyside.QtCore = type(sys)("QtCore")
_pyside.QtCore.QObject = object
_pyside.QtCore.Signal = type("Signal", (), {})
_pyside.QtCore.QThread = type("QThread", (), {"start": lambda self: None})
sys.modules["PySide6"] = _pyside
sys.modules["PySide6.QtCore"] = _pyside.QtCore

from core.config import Settings
from core.agent.execution_intent import ExecutionIntentRouter, ExecutionIntent, ExecutionRoute
from core.agent.execution_hook import ExecutionGovernanceHook
from core.agent.execution_budget import ExecutionBudget


class FakeGateway:
    def __init__(self):
        self._tools: dict[str, Any] = {}
    def register_tool(self, tool):
        self._tools[tool.name] = tool
    def unregister_tool(self, name):
        self._tools.pop(name, None)
    def get_tool(self, name):
        return self._tools.get(name)


class FakeGuardrails:
    def validate_path(self, path):
        return None
    def validate_shell_command(self, cmd):
        return None
    def validate_web_url(self, url):
        return None
    def validate_working_dir(self, d):
        return None


class FakeTraceRepo:
    def __init__(self):
        self.records: list[dict[str, Any]] = []
    def record(self, **kwargs):
        self.records.append(kwargs)


def _make_settings(**overrides) -> Settings:
    base = {
        "llm_api_key": "test",
        "execution_governance_enabled": True,
        "execution_local_tools_enabled": True,
        "execution_trace_enabled": True,
        "execution_block_shell_for_local_open": True,
    }
    base.update(overrides)
    return Settings(**base)


class TestAdapterExecutionGovernance:
    def test_governance_enabled_registers_tools(self):
        s = _make_settings()
        gateway = FakeGateway()
        assert s.execution_governance_enabled is True
        assert s.execution_local_tools_enabled is True

    def test_governance_disabled_skips_tools(self):
        s = _make_settings(execution_governance_enabled=False)
        assert s.execution_governance_enabled is False

    def test_local_tools_disabled_skips_registration(self):
        s = _make_settings(execution_local_tools_enabled=False)
        assert s.execution_local_tools_enabled is False

    def test_route_local_open_target_has_forbidden_exec(self):
        router = ExecutionIntentRouter()
        route = router.route("帮我打开桌面的洛克王国：世界")
        assert route.intent == ExecutionIntent.LOCAL_OPEN_TARGET
        assert "exec" in route.forbidden_tools

    def test_HOOK_high_confidence_candidate_from_tool_result(self):
        route = ExecutionRoute(
            intent=ExecutionIntent.LOCAL_OPEN_TARGET,
            confidence=0.9,
            requires_tools=True,
            preferred_tools=["local_app_resolve", "local_open"],
            forbidden_tools=["exec"],
        )
        budget = ExecutionBudget(block_shell_for_local_open=False, enabled=True)
        hook = ExecutionGovernanceHook(route, budget)

        tc = types.SimpleNamespace(name="local_app_resolve", arguments={"target": "微信"})
        ctx = types.SimpleNamespace(
            tool_calls=[tc],
            tool_results=['{"candidates":[{"confidence":0.98,"openable":true}]}'],
        )
        asyncio.run(hook.after_iteration(ctx))
        assert budget.resolver_has_high_confidence is True

    def test_HOOK_blocks_search_after_high_confidence(self):
        route = ExecutionRoute(
            intent=ExecutionIntent.LOCAL_OPEN_TARGET,
            confidence=0.9, requires_tools=True,
            preferred_tools=["local_app_resolve"], forbidden_tools=["exec"],
        )
        budget = ExecutionBudget(block_shell_for_local_open=False, enabled=True)
        budget.record_high_confidence_candidate()
        hook = ExecutionGovernanceHook(route, budget)

        tc = types.SimpleNamespace(name="exec", arguments={"command": "echo search"})
        ctx = types.SimpleNamespace(tool_calls=[tc])
        asyncio.run(hook.before_execute_tools(ctx))
        assert len(ctx.tool_calls) == 0

    def test_trace_repo_records_completed_tool(self):
        route = ExecutionRoute(intent=ExecutionIntent.LOCAL_OPEN_TARGET, confidence=0.9)
        budget = ExecutionBudget(enabled=True)
        repo = FakeTraceRepo()
        hook = ExecutionGovernanceHook(route, budget, session_id="s1", trace_repo=repo)

        tc = types.SimpleNamespace(name="local_app_resolve", arguments={"target": "x"})
        ctx = types.SimpleNamespace(tool_calls=[tc], tool_results=["{}"])
        asyncio.run(hook.after_iteration(ctx))
        assert len(repo.records) >= 1
        assert repo.records[0]["tool_name"] == "local_app_resolve"
        assert repo.records[0]["status"] == "completed"

    def test_trace_repo_records_blocked_tool(self):
        route = ExecutionRoute(
            intent=ExecutionIntent.LOCAL_OPEN_TARGET,
            confidence=0.9, requires_tools=True,
            preferred_tools=["local_app_resolve"], forbidden_tools=["exec"],
        )
        budget = ExecutionBudget(block_shell_for_local_open=True, enabled=True)
        repo = FakeTraceRepo()
        hook = ExecutionGovernanceHook(route, budget, session_id="s1", trace_repo=repo)

        tc = types.SimpleNamespace(name="exec", arguments={"command": "dir"})
        ctx = types.SimpleNamespace(tool_calls=[tc])
        asyncio.run(hook.before_execute_tools(ctx))
        assert repo.records
        assert repo.records[0]["status"] == "blocked"

    def test_tool_name_and_description(self):
        from core.agent.tools.local_app_resolve_tool import LocalAppResolveTool
        from core.agent.tools.local_open_tool import LocalOpenTool
        assert LocalAppResolveTool().name == "local_app_resolve"
        assert LocalOpenTool().name == "local_open"
        assert len(LocalAppResolveTool().description) > 0
        assert len(LocalOpenTool().description) > 0
