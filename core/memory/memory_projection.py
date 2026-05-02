"""Markdown projection layer for memory items."""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from core.memory.memory_schema import MemoryItem, MemoryType

logger = logging.getLogger(__name__)


class MemoryProjection:
    """Projects SQLite memory items into markdown files for human readability and nanobot compatibility."""

    def __init__(self, data_dir: Path, workspace_path: Path) -> None:
        self.data_dir = data_dir
        self.memory_dir = data_dir / "memory"
        self.workspace_path = workspace_path

    def project_all(self, items: list[MemoryItem]) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._project_user_profile(items)
        self._project_system_profile(items)
        self._project_project_memory(items)
        self._project_to_workspace(items)

    def _project_user_profile(self, items: list[MemoryItem]) -> None:
        user_items = [i for i in items if i.memory_type == MemoryType.USER_PROFILE and i.status.value == "active"]
        if not user_items:
            return
        lines = ["## Basic Notes", ""]
        for item in user_items:
            lines.append(f"- {item.content}")
        content = "\n".join(lines) + "\n"
        self._write_atomic(self.memory_dir / "USER.md", content)

    def _project_system_profile(self, items: list[MemoryItem]) -> None:
        system_items = [i for i in items if i.memory_type == MemoryType.SYSTEM_PROFILE and i.status.value == "active"]
        if not system_items:
            return
        lines = ["## System Behavior", ""]
        for item in system_items:
            lines.append(f"- {item.content}")
        content = "\n".join(lines) + "\n"
        self._write_atomic(self.memory_dir / "SYSTEM.md", content)

    def _project_project_memory(self, items: list[MemoryItem]) -> None:
        project_items = [i for i in items if i.memory_type == MemoryType.PROJECT_MEMORY and i.status.value == "active"]
        if not project_items:
            return
        scopes: dict[str, list[str]] = {}
        for item in project_items:
            scopes.setdefault(item.scope, []).append(item.content)
        lines: list[str] = []
        for scope, contents in sorted(scopes.items()):
            lines.append(f"## {scope}")
            lines.append("")
            for c in contents:
                lines.append(f"- {c}")
            lines.append("")
        self._write_atomic(self.memory_dir / "PROJECT.md", "\n".join(lines))

    def _project_to_workspace(self, items: list[MemoryItem]) -> None:
        user_items = [i for i in items if i.memory_type == MemoryType.USER_PROFILE and i.status.value == "active"]
        if user_items:
            lines = ["## Basic Information", ""]
            for item in user_items:
                lines.append(f"- {item.content}")
            lines.extend(["", "## Preferences", ""])
            self._write_atomic(self.workspace_path / "USER.md", "\n".join(lines) + "\n")
        system_items = [i for i in items if i.memory_type == MemoryType.SYSTEM_PROFILE and i.status.value == "active"]
        if system_items:
            lines = ["## Personality", ""]
            for item in system_items:
                lines.append(f"- {item.content}")
            self._write_atomic(self.workspace_path / "SOUL.md", "\n".join(lines) + "\n")

    @staticmethod
    def _write_atomic(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".mem_proj_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                _ = f.write(content)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def _sanitize_line(text: str) -> str:
        import re

        patterns = [
            re.compile(r"sk-[a-zA-Z0-9]{20,}"),
            re.compile(r"ghp_[a-zA-Z0-9]{36}"),
            re.compile(r"xoxb-[a-zA-Z0-9-]+"),
            re.compile(r"Bearer\s+[a-zA-Z0-9._-]+"),
            re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        ]
        for pat in patterns:
            text = pat.sub("[REDACTED]", text)
        return text
