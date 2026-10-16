"""Bounded file-copy and extractive research scenarios using existing governance."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from core.agent.dsh.web import fetch_page
from core.service.outcomes import Outcome, OutcomeRepository

if TYPE_CHECKING:
    from core.agent.dsh.tools import GovernedTools


class OrganizeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, max_length=4096)
    output: str = Field(min_length=1, max_length=4096)
    preview_id: str = Field(default="", max_length=128)


class DigestArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sources: list[str] = Field(min_length=1, max_length=6)


@contextmanager
def directory(workspace: Path, relative: Path, create: bool = False) -> Iterator[int]:
    fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def read_file(workspace: Path, path: Path, limit: int = 5_000_000) -> bytes:
    with directory(workspace, path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
                raise ValueError("只支持大小限制内的普通非硬链接文件")
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise ValueError("文件超过大小限制")
            return data


class PracticalTools:
    def __init__(self, owner: GovernedTools) -> None:
        self.owner = owner
        if not owner.knowledge or not owner.state:
            raise RuntimeError("任务验收服务不可用")
        self.state = owner.state
        self.repo = OutcomeRepository(owner.knowledge.db)
        self.previews: dict[str, tuple[str, str, list[dict[str, str]]]] = {}

    def preview(self, args: OrganizeArguments) -> str:
        source, output = self.owner._relative_path(args.source), self.owner._relative_path(
            args.output
        )
        if output == source or output.is_relative_to(source):
            raise ValueError("输出目录必须在输入目录之外")
        entries: list[dict[str, str]] = []
        total = 0
        with directory(self.owner.workspace, source) as fd:
            names = os.listdir(fd)
            if not names or len(names) > 100:
                raise ValueError("首版支持非空目录，至多100个直接文件；子目录需单独指定")
            for name in sorted(names):
                path = self.owner._relative_path(str(source / name))
                data = read_file(self.owner.workspace, path)
                total += len(data)
                if total > 32_000_000:
                    raise ValueError("批次超过32MB")
                ext = path.suffix.lower().lstrip(".")
                category = ext if re.fullmatch(r"[a-z0-9]{1,12}", ext) else "other"
                target = self.owner._relative_path(str(output / category / name))
                entries.append(
                    {
                        "source": str(path),
                        "target": str(target),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
        identity = str(uuid.uuid4())
        self.previews[identity] = (str(source), str(output), entries)
        self.repo.save(
            Outcome(
                turn_id=self.state.turn_id,
                scenario="organize",
                criteria=["逐文件副本数量与 SHA-256 一致", "保留原文件且不覆盖"],
                reason="已生成预览，尚未执行",
            )
        )
        return json.dumps(
            {
                "preview_id": identity,
                "count": len(entries),
                "copies": entries[:3],
                "more": max(0, len(entries) - 3),
                "scope": "仅本层文件，按扩展名分类",
            },
            ensure_ascii=False,
        )

    async def organize(self, args: OrganizeArguments, active: Callable[[], bool]) -> str:
        if not args.preview_id:
            return self.preview(args)
        preview = self.previews.get(args.preview_id)
        if not preview or preview[:2] != (
            str(self.owner._relative_path(args.source)),
            str(self.owner._relative_path(args.output)),
        ):
            raise ValueError("预览不存在或目录已改变，请重新预览")
        entries = preview[2]
        from core.safety.hitl_approval import HitlApprovalRequest, request_approval_with_timeout

        approval = HitlApprovalRequest.create(
            session_id=self.state.session_id,
            tool_name="lobuddy_organize",
            command=json.dumps(entries, ensure_ascii=False),
            working_dir=str(self.owner.workspace),
            reason="按此清单创建分类副本，保留原文件且不覆盖",
            affected_paths=tuple(e["target"] for e in entries),
            risk_tags=("file_copy",),
            timeout_seconds=self.owner.timeout,
        )
        decision = await request_approval_with_timeout(self.owner.approval, approval)
        if decision.request_id != approval.request_id or not decision.approved or not active():
            raise RuntimeError("整理未获批准或已取消")
        # Persist before writes; crashes and late duplicate requests never replay effects.
        self.repo.claim_effect(args.preview_id, self.state.turn_id, json.dumps(entries))
        copied: list[dict[str, JsonValue]] = []
        try:
            for entry in entries:
                if not active():
                    raise RuntimeError("整理已取消")
                data = read_file(self.owner.workspace, Path(entry["source"]))
                if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise ValueError("源文件自预览后已改变")
                target = Path(entry["target"])
                with directory(self.owner.workspace, target.parent, create=True) as fd:
                    output = os.open(
                        target.name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=fd,
                    )
                    with os.fdopen(output, "wb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                if (
                    hashlib.sha256(read_file(self.owner.workspace, target)).hexdigest()
                    != entry["sha256"]
                ):
                    raise ValueError("副本校验失败")
                if (
                    hashlib.sha256(
                        read_file(self.owner.workspace, Path(entry["source"]))
                    ).hexdigest()
                    != entry["sha256"]
                ):
                    raise ValueError("复制过程中源文件发生改变")
                copied.append(dict(entry))
        except (OSError, ValueError, RuntimeError) as error:
            self.repo.finish_effect(args.preview_id, "unknown")
            self.repo.save(
                Outcome(
                    turn_id=self.state.turn_id,
                    verdict="failed",
                    scenario="organize",
                    criteria=["全部副本与原文件哈希一致", "不覆盖"],
                    evidence=[dict(entry) for entry in copied]
                    + [
                        {
                            "check": "copy_integrity",
                            "passed": False,
                            "copied_count": len(copied),
                            "failure_class": type(error).__name__,
                        }
                    ],
                    reason="整理未完整通过；保留已产生副本，不自动重放",
                )
            )
            raise
        self.repo.finish_effect(args.preview_id, "completed")
        outcome = Outcome(
            turn_id=self.state.turn_id,
            verdict="verified",
            scenario="organize",
            criteria=["副本数量等于预览数量", "原文件与副本 SHA-256 一致", "独占创建不覆盖"],
            evidence=[dict(entry) for entry in copied],
            reason=f"已验证 {len(copied)} 份分类副本",
        )
        self.repo.save(outcome)
        return outcome.model_dump_json()

    async def digest(self, args: DigestArguments, active: Callable[[], bool]) -> str:
        import asyncio

        evidence: list[dict[str, JsonValue]] = []
        sections: dict[str, list[dict[str, str]]] = {"summary": [], "decisions": [], "todos": []}
        for index, source in enumerate(args.sources):
            if not active():
                raise RuntimeError("资料归纳已取消")
            try:
                if source.startswith(("https://", "http://")):
                    cancel = Event()
                    try:
                        text = await asyncio.to_thread(
                            fetch_page, source, self.owner.guardrails, 12000, cancel
                        )
                    finally:
                        cancel.set()
                else:
                    path = self.owner._relative_path(source)
                    text = read_file(self.owner.workspace, path, 100000).decode("utf-8")
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                if not lines:
                    raise ValueError("空来源")
                ref = f"S{index + 1}"
                evidence.append(
                    {
                        "source": source,
                        "ref": ref,
                        "sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "available": True,
                    }
                )
                sections["summary"].append({"source": ref, "quote": "\n".join(lines[:2])[:800]})
                for key, pattern in (
                    ("decisions", r"决定|决议|确定|decision"),
                    ("todos", r"待办|TODO|下一步|需要完成"),
                ):
                    for line in lines:
                        if re.search(pattern, line, re.IGNORECASE) and len(sections[key]) < 20:
                            sections[key].append({"source": ref, "quote": line[:800]})
            except (OSError, ValueError, RuntimeError, UnicodeError):
                evidence.append({"source": source, "available": False})
        complete = all(item["available"] for item in evidence)
        outcome = Outcome(
            turn_id=self.state.turn_id,
            verdict="verified" if complete else "unknown",
            scenario="digest",
            criteria=["所有输入来源可读取", "每个摘录有来源编号且来自原文"],
            evidence=evidence,
            reason=(
                "来源摘录校验通过；这是摘录式归纳，不保证语义完整性"
                if complete
                else "部分来源缺失，未补全推测"
            ),
        )
        self.repo.save(outcome)
        return json.dumps(
            {
                "outcome": outcome.model_dump(mode="json"),
                "sections": sections,
                "mode": "原文摘录；无明确决定/待办时保持空列表",
            },
            ensure_ascii=False,
        )
