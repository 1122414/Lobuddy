"""Bounded native candidate lookup and opening, without an agent-framework dependency."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from core.safety.guardrails import SafetyGuardrails

DOCUMENTS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
}


async def open_native(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    if sys.platform != "darwin":
        raise RuntimeError("当前平台尚未完成本地打开验收")
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/open",
        str(path),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env={key: value for key, value in os.environ.items() if key in {"HOME", "PATH", "LANG"}},
    )
    try:
        await asyncio.wait_for(process.wait(), 10)
        if process.returncode:
            raise RuntimeError("系统未能打开所选项目")
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


@dataclass(frozen=True)
class Candidate:
    path: Path
    fingerprint: tuple[int, int, int]
    source: str


class LocalOpenService:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.candidates: dict[str, Candidate] = {}

    def sources(self) -> list[tuple[str, Path]]:
        roots = [("工作区", self.workspace), ("桌面", Path.home() / "Desktop")]
        if sys.platform == "darwin":
            roots += [
                ("应用程序", Path("/Applications")),
                ("系统应用", Path("/System/Applications")),
                ("个人应用", Path.home() / "Applications"),
            ]
        return roots

    @staticmethod
    def fingerprint(path: Path) -> tuple[int, int, int]:
        info = path.lstat()
        return info.st_dev, info.st_ino, info.st_mtime_ns

    def resolve(self, query: str) -> list[dict[str, str]]:
        self.candidates.clear()
        if not query.strip():
            raise ValueError("请输入要查找的应用或文件名称")
        for source, root in self.sources():
            if root.is_symlink() or not root.is_dir():
                continue
            guardrails = SafetyGuardrails(root.resolve())
            try:
                entries = root.iterdir()
                for index, path in enumerate(entries):
                    if index >= 200:
                        break
                    if query.casefold() not in path.stem.casefold() or path.is_symlink():
                        continue
                    is_app = sys.platform == "darwin" and path.suffix == ".app" and path.is_dir()
                    if not is_app and (path.suffix.lower() not in DOCUMENTS or not path.is_file()):
                        continue
                    if path.name.startswith(".") or guardrails.validate_path(str(path)):
                        continue
                    resolved = path.resolve()
                    candidate = Candidate(resolved, self.fingerprint(resolved), source)
                    self.candidates[str(resolved)] = candidate
                    if len(self.candidates) >= 10:
                        return self.describe()
            except OSError:
                continue
        return self.describe()

    def describe(self) -> list[dict[str, str]]:
        return [
            {"path": str(item.path), "name": item.path.stem, "source": item.source}
            for item in self.candidates.values()
        ]

    def validate(self, path: str) -> Path:
        candidate = self.candidates.get(path)
        if candidate is None or candidate.path.is_symlink():
            raise ValueError("只能打开本轮查找得到的候选")
        if self.fingerprint(candidate.path) != candidate.fingerprint:
            raise ValueError("候选已变化，请重新查找并确认")
        return candidate.path
