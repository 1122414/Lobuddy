"""Fail-closed initial DSH tool mapping; all filesystem effects remain in Python."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import stat
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field

from core.agent.dsh.commands import command_arguments, run_command
from core.agent.dsh.practical import DigestArguments, OrganizeArguments, PracticalTools
from core.agent.dsh.web import fetch_page
from core.agent.execution_budget import ExecutionBudget
from core.agent.execution_intent import ExecutionIntentRouter
from core.config import Settings
from core.memory.memory_schema import MemoryPatch, MemoryPatchAction, MemoryPatchItem, MemoryType
from core.memory.session_search import SessionSearchScope
from core.safety.guardrails import SafetyGuardrails
from core.safety.hitl_approval import (
    HitlApprovalProvider,
    HitlApprovalRequest,
    request_approval_with_timeout,
)
from core.service.relationship_protocol import RelationProposal
from core.services.local_open import LocalOpenService, open_native
from core.tools.tool_policy import ToolPolicy

if TYPE_CHECKING:
    from core.service.knowledge import KnowledgeService
    from core.service.protocol import TurnState


class FileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, max_length=4096)
    content: str | None = Field(default=None, max_length=100000)


class WebArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str = Field(min_length=1, max_length=4096)


class CommandArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command: str = Field(min_length=1, max_length=4000)


class SearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=200)
    scope: Literal["current_session", "all_sessions"] = "current_session"


class SkillArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    skill_id: str = Field(min_length=1, max_length=128)


class MemoryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    memory_type: Literal["user_profile", "project_memory", "episodic_memory", "procedural_memory"]
    title: str = Field(max_length=100)
    content: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    callId: str = Field(min_length=1, max_length=128)
    name: Literal[
        "lobuddy_organize",
        "lobuddy_digest",
        "lobuddy_read_file",
        "lobuddy_write_file",
        "lobuddy_session_search",
        "lobuddy_memory_propose",
        "lobuddy_skill_read",
        "lobuddy_local_resolve",
        "lobuddy_local_open",
        "lobuddy_exec",
        "lobuddy_web_fetch",
        "lobuddy_web_search",
    ]
    arguments: (
        OrganizeArguments
        | DigestArguments
        | FileArguments
        | SearchArguments
        | MemoryArguments
        | SkillArguments
        | CommandArguments
        | WebArguments
    )


class GovernedTools:
    def __init__(
        self,
        workspace: Path,
        approval: HitlApprovalProvider,
        *,
        timeout: int = 120,
        knowledge: KnowledgeService | None = None,
        state: TurnState | None = None,
        settings: Settings | None = None,
        record_skill: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.record_skill = record_skill
        self.knowledge = knowledge
        self.state = state
        self.used: list[str] = []
        self.practical: PracticalTools | None = None
        self.workspace = workspace.resolve()
        self.guardrails = SafetyGuardrails(self.workspace)
        self.policy = ToolPolicy(shell_enabled=bool(settings and settings.shell_enabled))
        self.local = LocalOpenService(self.workspace)
        self.approval = approval
        self.timeout = settings.hitl_approval_timeout_seconds if settings else timeout
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
        settings = self.settings
        budget = self._budgets.setdefault(
            turn_id,
            ExecutionBudget(
                max_tool_calls_per_task=(
                    settings.execution_max_tool_calls_per_task if settings else 6
                ),
                max_local_lookup_calls=settings.execution_max_local_lookup_calls if settings else 2,
                max_shell_calls_per_task=(
                    settings.execution_max_shell_calls_per_task if settings else 2
                ),
                max_tool_result_chars=(
                    settings.execution_max_tool_result_chars if settings else 3000
                ),
            ),
        )
        if not is_active() or not self.policy.is_tool_allowed(request.name) or budget.is_exceeded():
            raise RuntimeError("Tool cancelled, disabled, or over budget")
        if (
            request.name in ("lobuddy_local_resolve", "lobuddy_local_open")
            and settings
            and not settings.execution_local_tools_enabled
        ):
            raise RuntimeError("Local tools are disabled")
        if request.name == "lobuddy_local_resolve" and budget.is_resolver_exceeded():
            raise RuntimeError("Local lookup budget exceeded")
        if request.name == "lobuddy_local_open" and request.name in self.used:
            raise RuntimeError("Only one local open is allowed per turn")
        if request.name == "lobuddy_exec":
            if not self.policy.is_tool_allowed("exec") or budget.is_shell_exceeded():
                raise RuntimeError("Shell is disabled or over budget")
            if (
                self.state
                and "exec" in ExecutionIntentRouter().route(self.state.input_text).forbidden_tools
            ):
                raise RuntimeError("Use the local lookup/open tools for this request")
            budget.record_tool_call("exec")
            self.used.append(request.name)
            if not isinstance(request.arguments, CommandArguments):
                raise ValueError("Invalid command arguments")
            args = command_arguments(request.arguments.command, self.workspace)
            for index, argument in enumerate(args[1:], start=1):
                if argument.startswith("-") or Path(args[0]).name == "echo":
                    continue
                if args[index - 1] == "-n" and argument.isdecimal():
                    continue
                if argument == "." and Path(args[0]).name in {"ls", "pwd"}:
                    continue
                relative = self._relative_path(argument)
                cursor = self.workspace
                for part in relative.parts:
                    cursor /= part
                    if cursor.is_symlink():
                        raise ValueError("Command paths cannot traverse symbolic links")
            approval = HitlApprovalRequest.create(
                session_id=session_id,
                tool_name=request.name,
                command=shlex.join(args),
                working_dir=str(self.workspace),
                reason="确认在工作区运行此本地命令",
                affected_paths=(),
                risk_tags=("command_execution",),
                timeout_seconds=self.timeout,
            )
            decision = await request_approval_with_timeout(self.approval, approval)
            if (
                decision.request_id != approval.request_id
                or not decision.approved
                or not is_active()
            ):
                raise RuntimeError("Command denied or cancelled")
            return await run_command(
                args,
                self.workspace,
                self.settings.task_timeout if self.settings else 120,
                budget.max_tool_result_chars,
            )
        budget.record_tool_call(
            "local_app_resolve" if request.name == "lobuddy_local_resolve" else request.name
        )
        self.used.append(request.name)
        if request.name in ("lobuddy_organize", "lobuddy_digest"):
            if self.practical is None:
                self.practical = PracticalTools(self)
            if request.name == "lobuddy_organize" and isinstance(
                request.arguments, OrganizeArguments
            ):
                return await self.practical.organize(request.arguments, is_active)
            if request.name == "lobuddy_digest" and isinstance(request.arguments, DigestArguments):
                return await self.practical.digest(request.arguments, is_active)
            raise ValueError("Invalid scenario arguments")
        if request.name in ("lobuddy_web_fetch", "lobuddy_web_search"):
            if request.name == "lobuddy_web_fetch" and isinstance(request.arguments, WebArguments):
                url = request.arguments.url
            elif request.name == "lobuddy_web_search" and isinstance(
                request.arguments, SearchArguments
            ):
                url = "https://www.bing.com/search?format=rss&" + urlencode(
                    {"q": request.arguments.query}
                )
            else:
                raise ValueError("Invalid web arguments")
            cancelled = Event()
            try:
                return await asyncio.to_thread(
                    fetch_page, url, self.guardrails, budget.max_tool_result_chars, cancelled
                )
            finally:
                cancelled.set()
        if request.name == "lobuddy_local_resolve":
            if not isinstance(request.arguments, SearchArguments):
                raise ValueError("Invalid lookup arguments")
            return json.dumps(self.local.resolve(request.arguments.query), ensure_ascii=False)[
                : budget.max_tool_result_chars
            ]
        if request.name == "lobuddy_local_open":
            if not isinstance(request.arguments, FileArguments):
                raise ValueError("Invalid local open arguments")
            path = self.local.validate(request.arguments.path)
            approval = HitlApprovalRequest.create(
                session_id=session_id,
                tool_name=request.name,
                command=f"打开 {path}",
                working_dir=str(self.workspace),
                reason="确认使用系统默认应用打开此候选",
                affected_paths=(str(path),),
                risk_tags=("local_open",),
                timeout_seconds=self.timeout,
            )
            decision = await request_approval_with_timeout(self.approval, approval)
            if (
                decision.request_id != approval.request_id
                or not decision.approved
                or not is_active()
            ):
                raise RuntimeError("Local open denied or cancelled")
            await open_native(self.local.validate(str(path)))
            return "已交给系统打开。"
        if request.name in (
            "lobuddy_session_search",
            "lobuddy_memory_propose",
            "lobuddy_skill_read",
        ):
            value = await self._knowledge_effect(request, session_id, is_active)
            return value[: budget.max_tool_result_chars]
        if not isinstance(request.arguments, FileArguments):
            raise ValueError("Invalid file arguments")  # noqa: TRY004 - wire validation
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

    async def _knowledge_effect(
        self,
        request: ToolRequest,
        session_id: str,
        is_active: Callable[[], bool],
    ) -> str:
        if self.knowledge is None or self.state is None:
            raise RuntimeError("Knowledge service is unavailable")
        if request.name == "lobuddy_skill_read":
            if not isinstance(request.arguments, SkillArguments):
                raise ValueError("Invalid skill arguments")
            skill = self.knowledge.skills.get_skill(request.arguments.skill_id)
            if (
                skill is None
                or skill.status.value != "active"
                or (
                    skill.expires_at
                    and skill.expires_at <= datetime.now(tz=skill.expires_at.tzinfo)
                )
            ):
                raise ValueError("技能已停用或不存在")
            content = self.knowledge.skills.get_content(skill.id)
            if self.record_skill:
                self.record_skill(skill.id)
            return content
        if request.name == "lobuddy_session_search":
            if not isinstance(request.arguments, SearchArguments):
                raise ValueError("Invalid search arguments")
            if not self.knowledge.settings.memory_session_search_enabled:
                raise RuntimeError("History search is disabled")
            return self.knowledge.search.search(
                request.arguments.query,
                current_session_id=session_id,
                scope=SessionSearchScope(request.arguments.scope),
            ).model_dump_json()
        if not isinstance(request.arguments, MemoryArguments):
            raise ValueError("Invalid memory arguments")  # noqa: TRY004 - wire validation
        arguments = request.arguments
        if arguments.memory_type == "user_profile" and is_active():
            from core.service.learning_protocol import LearningPolicy

            policy = LearningPolicy.model_validate_json(
                self.knowledge.relationship.store.get_setting("learning_policy") or "{}"
            )
            if policy.enabled:
                admitted = self.knowledge.relationship.admit(
                    RelationProposal(
                        kind="preference",
                        key=arguments.title or "明确偏好",
                        content=arguments.content,
                        source_ids=[self.state.turn_id],
                        quote=self.state.input_text,
                    ),
                    session_id,
                    automatic_only=True,
                )
                if admitted and admitted.status == "active":
                    return admitted.model_dump_json()
        approval = HitlApprovalRequest.create(
            session_id=session_id,
            tool_name=request.name,
            command=f"记住：{arguments.title}\n{arguments.content}",
            working_dir=str(self.workspace),
            reason="确认将这条信息保存到长期记忆",
            affected_paths=(),
            risk_tags=("memory_write",),
            timeout_seconds=self.timeout,
        )
        decision = await request_approval_with_timeout(self.approval, approval)
        if decision.request_id != approval.request_id or not decision.approved or not is_active():
            raise RuntimeError("Memory write denied or cancelled")
        return await self.knowledge.propose(
            MemoryPatch(
                items=[
                    MemoryPatchItem(
                        memory_type=MemoryType(arguments.memory_type),
                        action=MemoryPatchAction.ADD,
                        title=arguments.title,
                        content=arguments.content,
                        confidence=arguments.confidence,
                        importance=0.8,
                    )
                ]
            ),
            self.state,
        )

    def _relative_path(self, value: str) -> Path:
        reason = self.guardrails.validate_path(value)
        if reason:
            raise ValueError(reason)
        path = Path(value)
        if path.is_absolute():
            path = path.relative_to(self.workspace)
        resolved = (self.workspace / path).resolve()
        application = Path(__file__).resolve().parents[3]
        protected = [
            application / part
            for part in ("core", "app", "bridge", "desktop", "shared", "scripts", "tests")
        ]
        if self.settings:
            protected.append(self.settings.data_dir.resolve())
        if any(resolved.is_relative_to(root) for root in protected):
            raise ValueError("应用核心、评测与私有数据不可经工具读写")
        if not path.parts or any(
            part.casefold() in ("..", ".git", ".ssh", ".aws")
            or part.casefold().startswith(".env")
            or "credential" in part.lower()
            for part in path.parts
        ):
            raise ValueError("Protected or ambiguous path")
        if path.parts[0].casefold() in (
            "skills",
            "memory",
            "user.md",
            "soul.md",
            "system.md",
            "agents.md",
        ):
            raise ValueError("Managed knowledge must use the knowledge service")
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
