"""5.4 LocalAppResolveTool — structured desktop/start menu candidate lookup."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, ClassVar

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, IntegerSchema, ArraySchema, tool_parameters_schema, ObjectSchema

logger = logging.getLogger("lobuddy.local_app_resolve")

_SEARCHABLE_EXTENSIONS: tuple[str, ...] = (".lnk", ".url", ".exe")

_START_MENU_USER = (
    Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    / "Microsoft" / "Windows" / "Start Menu" / "Programs"
)
_START_MENU_GLOBAL = Path("C:/ProgramData/Microsoft/Windows/Start Menu/Programs")


def _normalize(name: str) -> str:
    lowered = name.lower()
    lowered = lowered.replace("：", ":")
    lowered = lowered.replace("：", ":")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def _match_score(file_stem_norm: str, query_norm: str) -> float:
    if file_stem_norm == query_norm:
        return 0.98
    colonless = query_norm.replace(":", "")
    if file_stem_norm == colonless:
        return 0.95
    if file_stem_norm.startswith(query_norm) or file_stem_norm.startswith(colonless):
        return 0.85
    if query_norm in file_stem_norm or colonless in file_stem_norm:
        return 0.70
    return 0.0


def _is_unsafe_ext(ext: str) -> bool:
    return ext in (".bat", ".cmd", ".ps1", ".vbs", ".wsf")


def _kind_from_ext(ext: str) -> str:
    if ext == ".lnk":
        return "shortcut"
    if ext == ".url":
        return "url"
    if ext == ".exe":
        return "executable"
    if ext in {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md"}:
        return "document"
    return "file"


@tool_parameters(
    tool_parameters_schema(
        target=StringSchema("Name of the application or shortcut to find"),
        sources=ArraySchema(
            StringSchema("source name"),
            description="Sources to search: desktop, onedrive_desktop, start_menu_user, start_menu_global",
        ),
        limit=IntegerSchema("Max candidates (1-10, default 5)"),
        required=["target"],
    )
)
class LocalAppResolveTool(Tool):
    """Search desktop and start menu for application shortcuts/executables.

    Does NOT search Program Files, AppData, or any recursive directory.
    Returns structured JSON with match confidence, openability, and source.
    """

    MAX_FILES_PER_SOURCE: ClassVar[int] = 200
    MAX_START_MENU_DEPTH: ClassVar[int] = 3

    def __init__(self) -> None:
        self._last_candidates: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "local_app_resolve"

    @property
    def description(self) -> str:
        return (
            "Search Desktop and Start Menu for an application shortcut or executable "
            "by name. Returns structured JSON with candidates ranked by match "
            "confidence. Use this BEFORE exec for any local file/app search. "
            "Does NOT search Program Files, AppData, or full disk."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        target: str = "",
        sources: list[str] | None = None,
        limit: int = 5,
        **kwargs: Any,
    ) -> str:
        if not target or not target.strip():
            return json.dumps({
                "query": "",
                "candidates": [],
                "searched_sources": [],
                "truncated": False,
            }, ensure_ascii=False)

        target = target.strip()
        sources = sources or ["desktop", "onedrive_desktop", "start_menu_user", "start_menu_global"]
        limit = max(1, min(10, limit))
        source_dirs = self._resolve_sources(sources)

        candidates: list[dict[str, Any]] = []
        searched: list[str] = []
        truncated = False

        for source_name, source_path in source_dirs:
            if not source_path or not source_path.is_dir():
                continue
            searched.append(source_name)
            source_candidates = self._search_directory(source_name, source_path, target, limit)
            candidates.extend(source_candidates)
            if len(candidates) >= limit:
                candidates = candidates[:limit]
                break

        if not candidates:
            searched = [s for s, _ in source_dirs if s in searched]
            return json.dumps({
                "query": target,
                "candidates": [],
                "searched_sources": searched,
                "truncated": False,
            }, ensure_ascii=False)

        candidates.sort(key=lambda c: c["confidence"], reverse=True)
        candidates = candidates[:limit]
        truncated = len(candidates) > limit

        self._last_candidates = candidates

        return json.dumps({
            "query": target,
            "candidates": candidates,
            "searched_sources": searched,
            "truncated": truncated,
        }, ensure_ascii=False)

    @property
    def last_candidates(self) -> list[dict[str, Any]]:
        return self._last_candidates

    def _resolve_sources(self, sources: list[str]) -> list[tuple[str, Path | None]]:
        mapping: dict[str, Path] = {
            "desktop": Path.home() / "Desktop",
            "onedrive_desktop": Path.home() / "OneDrive" / "Desktop",
            "start_menu_user": _START_MENU_USER,
            "start_menu_global": _START_MENU_GLOBAL,
        }
        return [(s, mapping.get(s)) for s in sources if s in mapping]

    def _search_directory(
        self, source_name: str, source_path: Path, target: str, limit: int
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        query_norm = _normalize(target)
        max_depth = self.MAX_START_MENU_DEPTH if source_name.startswith("start_menu") else 1

        self._walk(source_path, source_name, query_norm, candidates, limit, depth=0, max_depth=max_depth)
        return candidates

    def _walk(
        self,
        directory: Path,
        source_name: str,
        query_norm: str,
        candidates: list[dict[str, Any]],
        limit: int,
        depth: int = 0,
        max_depth: int = 3,
    ) -> None:
        if depth > max_depth or len(candidates) >= limit:
            return

        try:
            entries = sorted(
                [e for e in directory.iterdir() if not e.name.startswith(".")],
                key=lambda e: e.name,
            )[:self.MAX_FILES_PER_SOURCE]
        except (OSError, PermissionError):
            return

        for entry in entries:
            if len(candidates) >= limit:
                return
            if entry.is_dir() and source_name.startswith("start_menu"):
                self._walk(entry, source_name, query_norm, candidates, limit, depth + 1, max_depth)
                continue
            if not entry.is_file():
                continue
            ext = entry.suffix.lower()
            if ext not in _SEARCHABLE_EXTENSIONS and ext not in {".bat", ".cmd", ".ps1"}:
                continue

            stem = entry.name
            if ext:
                stem = entry.name[: -len(ext)]
            stem_norm = _normalize(stem)
            score = _match_score(stem_norm, query_norm)
            if score <= 0:
                continue

            candidates.append({
                "display_name": stem,
                "path": str(entry.resolve()),
                "kind": _kind_from_ext(ext),
                "source": source_name,
                "confidence": round(score, 2),
                "openable": not _is_unsafe_ext(ext),
                "reason": f"normalized match (score={score:.2f})",
            })
