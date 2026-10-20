"""Cancellable argument-vector execution with a minimal child environment."""

from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
import shutil
import signal
from pathlib import Path

from core.safety.command_risk import CommandRiskAction
from core.safety.guardrails import SafetyGuardrails
from core.tools.tool_policy import ToolPolicy


def command_arguments(command: str, workspace: Path) -> list[str]:
    assessment = SafetyGuardrails(workspace).assess_shell_command(command, str(workspace))
    if assessment.action == CommandRiskAction.DENY:
        raise ValueError(assessment.reason)
    args = shlex.split(command)
    if not args or args[0] not in ToolPolicy.ALLOWED_COMMANDS:
        raise ValueError("命令不在允许列表中")
    supported = {
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "pwd",
        "echo",
        "mkdir",
        "touch",
        "cp",
        "mv",
        "rm",
    }
    if args[0] not in supported:
        raise ValueError("此命令尚未完成安全映射，请使用专用工具")
    safe_flags = {
        "ls": {"-l", "-a", "-la", "-al", "-h", "-lh"},
        "cat": {"-n"},
        "head": {"-n"},
        "tail": {"-n"},
        "wc": {"-l", "-w", "-c"},
        "pwd": set(),
        "echo": set(),
        "mkdir": {"-p"},
        "touch": set(),
        "cp": {"-n"},
        "mv": {"-n"},
        "rm": set(),
    }
    if any(
        arg.startswith("-") and arg != "--" and arg not in safe_flags[args[0]] for arg in args[1:]
    ):
        raise ValueError("命令选项未完成安全映射")
    executable = shutil.which(args[0], path="/usr/bin:/bin")
    if executable is None:
        raise ValueError("系统未安装该命令")
    return [executable, *args[1:]]


async def run_command(args: list[str], workspace: Path, timeout: int, limit: int) -> str:
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=workspace,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={
            "PATH": "/usr/bin:/bin",
            "LANG": "en_US.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_PAGER": "cat",
        },
        start_new_session=True,
    )
    assert process.stdout
    result = bytearray()
    truncated = False
    try:
        async with asyncio.timeout(timeout):
            while block := await process.stdout.read(4096):
                remaining = limit * 4 - len(result)
                result.extend(block[: max(0, remaining)])
                truncated |= len(block) > remaining
            await process.wait()
    finally:
        # Kill the owned group even if a child outlived its parent.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
    output = result.decode("utf-8", errors="replace")[:limit]
    return f"退出码 {process.returncode}\n{output}" + ("\n[结果已截断]" if truncated else "")
