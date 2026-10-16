"""Fail-closed initial DSH tool mapping; all filesystem effects remain in Python."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.agent.execution_budget import ExecutionBudget
from core.safety.guardrails import SafetyGuardrails
from core.safety.hitl_approval import (
    HitlApprovalProvider,
    HitlApprovalRequest,
    request_approval_with_timeout,
)
from core.tools.tool_policy import ToolPolicy


class FileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, max_length=4096)
    content: str | None = Field(default=None, max_length=100000)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    callId: str = Field(min_length=1, max_length=128)
    name: Literal["lobuddy_read_file", "lobuddy_write_file"]
    arguments: FileArguments


class GovernedTools:
    def __init__(
        self,
        workspace: Path,
        approval: HitlApprovalProvider,
        *,
        timeout: int = 120,
    ) -> None:
        self.workspace = workspace.resolve()
        self.guardrails = SafetyGuardrails(self.workspace)
        self.policy = ToolPolicy(shell_enabled=False)
        self.approval = approval
        self.timeout = timeout
        self._calls: set[tuple[str, str]] = set()
        self._budgets: dict[str, ExecutionBudget] = {}

    async def execute(
        self,
        request: ToolRequest,
        *,
        session_id: str,
        turn_id: str,
        is_active: Callable[[], bool],
    ) -> str:
        identity = (turn_id, request.callId)
        if identity in self._calls:
            raise RuntimeError("Repeated tool call rejected; result must not be replayed")
        self._calls.add(identity)
        budget = self._budgets.setdefault(turn_id, ExecutionBudget())
        if not is_active() or not self.policy.is_tool_allowed(request.name) or budget.is_exceeded():
            raise RuntimeError("Tool cancelled, disabled, or over budget")
        budget.record_tool_call(request.name)
        relative = self._relative_path(request.arguments.path)
        writing = request.name == "lobuddy_write_file"
        if writing:
            if request.arguments.content is None:
                raise ValueError("Write content required")
            approval = HitlApprovalRequest.create(
                session_id=session_id,
                tool_name=request.name,
                command=f"write_file {relative.as_posix()}",
                working_dir=str(self.workspace),
                reason="创建或覆盖文件需要确认",
                affected_paths=(str(relative),),
                risk_tags=("file_write",),
                timeout_seconds=self.timeout,
            )
            decision = await request_approval_with_timeout(self.approval, approval)
            if decision.request_id != approval.request_id or not decision.approved:
                raise RuntimeError("File write denied or approval expired")
        if not is_active():
            raise RuntimeError("Tool cancelled before execution")
        # No await between this final liveness check and the bounded file effect.
        result = self._file_effect(relative, request.arguments.content if writing else None)
        return result[: budget.max_tool_result_chars]

    def _relative_path(self, value: str) -> Path:
        reason = self.guardrails.validate_path(value)
        if reason:
            raise ValueError(reason)
        path = Path(value)
        if path.is_absolute():
            path = path.relative_to(self.workspace)
        if not path.parts or any(
            part in ("..", ".git", ".ssh", ".aws")
            or part.startswith(".env")
            or "credential" in part.lower()
            for part in path.parts
        ):
            raise ValueError("Protected or ambiguous path")
        if "\\" in value:
            raise ValueError("Use native paths for the current platform")
        return path

    def _file_effect(self, relative: Path, content: str | None) -> str:
        if os.name == "nt":
            raise RuntimeError("Native Windows file mapping is not qualified yet")
        directory = os.open(self.workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in relative.parts[:-1]:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                os.close(directory)
                directory = child
            flags = os.O_NOFOLLOW | os.O_NONBLOCK
            if content is None:
                fd = os.open(relative.name, os.O_RDONLY | flags, dir_fd=directory)
            else:
                # O_TRUNC is deliberately deferred until after regular-file validation.
                fd = os.open(
                    relative.name, os.O_WRONLY | os.O_CREAT | flags, 0o600, dir_fd=directory
                )
            with os.fdopen(fd, "rb" if content is None else "wb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("Only ordinary, non-hardlinked files are supported")
                if content is None:
                    if info.st_size > 100000:
                        raise ValueError("File exceeds read size limit")
                    data = stream.read(100001)
                    return data.decode("utf-8")
                stream.truncate(0)
                stream.write(content.encode("utf-8"))
                return "文件已写入。"
        finally:
            os.close(directory)
