"""5.4 ExecutionGovernanceHook tests — validates hook blocks inappropriate calls."""

import asyncio
import types

import pytest
from core.agent.execution_intent import ExecutionIntent, ExecutionRoute
from core.agent.execution_budget import ExecutionBudget
from core.agent.execution_hook import ExecutionGovernanceHook


def _local_open_route() -> ExecutionRoute:
    return ExecutionRoute(
        intent=ExecutionIntent.LOCAL_OPEN_TARGET,
        target="微信",
        confidence=0.9,
        requires_tools=True,
        preferred_tools=["local_app_resolve", "local_open"],
        forbidden_tools=["exec"],
        reason="User wants to open an app",
    )


def _generic_chat_route() -> ExecutionRoute:
    return ExecutionRoute(
        intent=ExecutionIntent.GENERAL_CHAT,
        confidence=0.0,
        reason="No execution pattern matched",
    )


def _make_hook(route: ExecutionRoute, **kwargs) -> ExecutionGovernanceHook:
    budget = ExecutionBudget(
        max_tool_calls_per_task=kwargs.pop("max_tool_calls", 6),
        max_local_lookup_calls=kwargs.pop("max_local_lookup", 2),
        max_shell_calls_per_task=kwargs.pop("max_shell", 2),
        block_shell_for_local_open=kwargs.pop("block_shell", True),
        max_tool_result_chars=kwargs.pop("max_result_chars", 3000),
        enabled=kwargs.pop("enabled", True),
    )
    return ExecutionGovernanceHook(route, budget)


def _fake_tc(name: str, args: dict):
    return types.SimpleNamespace(name=name, arguments=args)


def _fake_context(tool_calls: list):
    return types.SimpleNamespace(tool_calls=tool_calls)


class TestExecutionGovernanceHook:
    def test_blocks_exec_for_local_open_target(self):
        hook = _make_hook(_local_open_route(), block_shell=True)
        tc = _fake_tc("exec", {"command": "dir Desktop"})
        ctx = _fake_context([tc])
        with pytest.raises(RuntimeError, match="exec tool is blocked"):
            asyncio.run(hook.before_execute_tools(ctx))

    def test_blocks_where_r_recursive_search(self):
        hook = _make_hook(_local_open_route(), block_shell=False)
        tc = _fake_tc("exec", {"command": 'where /R "C:\\Desk" 洛克*'})
        ctx = _fake_context([tc])
        with pytest.raises(RuntimeError, match="recursive search"):
            asyncio.run(hook.before_execute_tools(ctx))

    def test_blocks_dir_s_recursive_search(self):
        hook = _make_hook(_local_open_route(), block_shell=False)
        tc = _fake_tc("exec", {"command": 'dir /s /b "C:\\Users"'})
        ctx = _fake_context([tc])
        with pytest.raises(RuntimeError, match="recursive search"):
            asyncio.run(hook.before_execute_tools(ctx))

    def test_blocks_get_childitem_recurse(self):
        hook = _make_hook(_local_open_route(), block_shell=False)
        tc = _fake_tc("exec", {"command": "Get-ChildItem -Recurse C:\\"})
        ctx = _fake_context([tc])
        with pytest.raises(RuntimeError, match="recursive search"):
            asyncio.run(hook.before_execute_tools(ctx))

    def test_blocks_program_files_in_command(self):
        hook = _make_hook(_local_open_route(), block_shell=False)
        tc = _fake_tc("exec", {"command": 'explorer "C:\\Program Files"'})
        ctx = _fake_context([tc])
        with pytest.raises(RuntimeError, match="Program Files"):
            asyncio.run(hook.before_execute_tools(ctx))

    def test_blocks_appdata_in_command(self):
        hook = _make_hook(_local_open_route(), block_shell=False)
        tc = _fake_tc("exec", {"command": 'dir "%APPDATA%\\foo"'})
        ctx = _fake_context([tc])
        with pytest.raises(RuntimeError, match="AppData"):
            asyncio.run(hook.before_execute_tools(ctx))

    def test_allows_exec_for_general_chat(self):
        hook = _make_hook(_generic_chat_route(), block_shell=True)
        tc = _fake_tc("exec", {"command": "echo hello"})
        ctx = _fake_context([tc])
        asyncio.run(hook.before_execute_tools(ctx))

    def test_budget_exceeded_raises(self):
        hook = _make_hook(_local_open_route(), max_tool_calls=0, block_shell=False)
        tc = _fake_tc("local_app_resolve", {"target": "x"})
        ctx = _fake_context([tc])
        with pytest.raises(RuntimeError, match="budget exceeded"):
            asyncio.run(hook.before_execute_tools(ctx))

    def test_wants_streaming_returns_false(self):
        hook = _make_hook(_local_open_route())
        assert hook.wants_streaming() is False

    def test_finalize_content_passthrough(self):
        hook = _make_hook(_local_open_route())
        result = hook.finalize_content(None, "hello")
        assert result == "hello"

    def test_noop_for_unknown_attr(self):
        hook = _make_hook(_local_open_route())
        result = hook.some_unknown_method()
        assert asyncio.iscoroutine(result) or result is not None

    def test_resolver_high_confidence_blocks_further_search(self):
        hook = _make_hook(_local_open_route(), block_shell=False)
        hook._budget.record_high_confidence_candidate()
        tc = _fake_tc("exec", {"command": "echo still searching"})
        ctx = _fake_context([tc])
        with pytest.raises(RuntimeError, match="high-confidence"):
            asyncio.run(hook.before_execute_tools(ctx))
