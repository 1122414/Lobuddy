"""5.4 ExecutionGovernanceHook tests — validates hook silently blocks calls."""

import asyncio
import types

import pytest
from core.agent.execution_intent import ExecutionIntent, ExecutionRoute
from core.agent.execution_budget import ExecutionBudget
from core.agent.execution_hook import ExecutionGovernanceHook


def _local_open_route() -> ExecutionRoute:
    return ExecutionRoute(
        intent=ExecutionIntent.LOCAL_OPEN_TARGET,
        target="微信", confidence=0.9, requires_tools=True,
        preferred_tools=["local_app_resolve", "local_open"],
        forbidden_tools=["exec"],
        reason="User wants to open an app",
    )


def _generic_chat_route() -> ExecutionRoute:
    return ExecutionRoute(intent=ExecutionIntent.GENERAL_CHAT, confidence=0.0,
                          reason="No execution pattern matched")


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
    def test_blocks_exec_silently_local_open_target(self):
        hook = _make_hook(_local_open_route(), block_shell=True)
        tc = _fake_tc("exec", {"command": "dir Desktop"})
        ctx = _fake_context([tc])
        asyncio.run(hook.before_execute_tools(ctx))
        assert len(ctx.tool_calls) == 0

    def test_blocks_where_r_silently(self):
        hook = _make_hook(_local_open_route(), block_shell=False)
        tc = _fake_tc("exec", {"command": 'where /R "C:\\Desk" 洛克*'})
        ctx = _fake_context([tc])
        asyncio.run(hook.before_execute_tools(ctx))
        assert len(ctx.tool_calls) == 0

    def test_blocks_dir_s_silently(self):
        hook = _make_hook(_local_open_route(), block_shell=False)
        tc = _fake_tc("exec", {"command": 'dir /s /b "C:\\Users"'})
        ctx = _fake_context([tc])
        asyncio.run(hook.before_execute_tools(ctx))
        assert len(ctx.tool_calls) == 0

    def test_blocks_get_childitem_silently(self):
        hook = _make_hook(_local_open_route(), block_shell=False)
        tc = _fake_tc("exec", {"command": "Get-ChildItem -Recurse C:\\"})
        ctx = _fake_context([tc])
        asyncio.run(hook.before_execute_tools(ctx))
        assert len(ctx.tool_calls) == 0

    def test_blocks_program_files_silently(self):
        hook = _make_hook(_local_open_route(), block_shell=False)
        tc = _fake_tc("exec", {"command": 'explorer "C:\\Program Files"'})
        ctx = _fake_context([tc])
        asyncio.run(hook.before_execute_tools(ctx))
        assert len(ctx.tool_calls) == 0

    def test_blocks_appdata_silently(self):
        hook = _make_hook(_local_open_route(), block_shell=False)
        tc = _fake_tc("exec", {"command": 'dir "%APPDATA%\\foo"'})
        ctx = _fake_context([tc])
        asyncio.run(hook.before_execute_tools(ctx))
        assert len(ctx.tool_calls) == 0

    def test_allows_exec_for_general_chat(self):
        hook = _make_hook(_generic_chat_route(), block_shell=True)
        tc = _fake_tc("exec", {"command": "echo hello"})
        ctx = _fake_context([tc])
        asyncio.run(hook.before_execute_tools(ctx))
        assert len(ctx.tool_calls) == 1

    def test_allows_safe_tool_for_local_open(self):
        hook = _make_hook(_local_open_route(), block_shell=True)
        tc = _fake_tc("local_app_resolve", {"target": "微信"})
        ctx = _fake_context([tc])
        asyncio.run(hook.before_execute_tools(ctx))
        assert len(ctx.tool_calls) == 1

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
        assert asyncio.iscoroutine(result)
