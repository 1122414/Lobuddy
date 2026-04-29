"""User profile manager — file I/O, parsing, patching, and prompt injection."""

import logging
import os
import re
import tempfile
from pathlib import Path

from core.memory.user_profile_schema import (
    PatchAction,
    ProfilePatch,
    ProfilePatchItem,
    ProfileSection,
    UserProfile,
)

logger = logging.getLogger(__name__)

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"xoxb-[a-zA-Z0-9-]+"),
    re.compile(r"Bearer\s+[a-zA-Z0-9._-]+"),
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
]

_SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$")

_DEFAULT_SECTIONS: dict[ProfileSection, list[str]] = {
    s: [] for s in ProfileSection
}


def _sanitize_line(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def _parse_markdown(text: str) -> dict[ProfileSection, list[str]]:
    sections: dict[ProfileSection, list[str]] = {}
    current: ProfileSection | None = None
    valid_names = {s.value for s in ProfileSection}

    for line in text.splitlines():
        m = _SECTION_HEADER_RE.match(line)
        if m:
            name = m.group(1).strip()
            if name in valid_names:
                current = ProfileSection(name)
                if current not in sections:
                    sections[current] = []
            else:
                current = None
            continue
        if current is not None:
            stripped = line.strip()
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                if item:
                    sections[current].append(item)

    return sections


def _render_markdown(profile: UserProfile) -> str:
    lines: list[str] = []
    for section in ProfileSection:
        items = profile.sections.get(section, [])
        lines.append(f"## {section.value}")
        lines.append("")
        if items:
            for item in items:
                lines.append(f"- {item}")
        else:
            lines.append("")
        lines.append("")
    return "\n".join(lines)


class UserProfileManager:
    def __init__(self, profile_path: Path) -> None:
        self._path: Path = profile_path

    def ensure_profile_file(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            default = build_default_profile()
            self._write_atomic(_render_markdown(default))
            logger.info("Created default USER.md at %s", self._path)

    def load_profile(self) -> UserProfile:
        if not self._path.exists():
            return build_default_profile()
        text = self._path.read_text(encoding="utf-8")
        sections = _parse_markdown(text)
        return UserProfile(sections=sections)

    def save_profile(self, profile: UserProfile) -> None:
        self._write_atomic(_render_markdown(profile))

    def apply_patch(
        self,
        patch: ProfilePatch,
        *,
        require_high_confidence: bool = True,
        min_confidence: float = 0.75,
    ) -> tuple[UserProfile, list[ProfilePatchItem]]:
        profile = self.load_profile()
        rejected: list[ProfilePatchItem] = []

        for item in patch.items:
            if item.action == PatchAction.UNCERTAIN:
                rejected.append(item)
                continue
            if require_high_confidence and item.confidence < min_confidence:
                rejected.append(item)
                continue
            sanitized = _sanitize_line(item.content)
            if sanitized != item.content:
                logger.warning(
                    "Sanitized secret in patch item for section %s",
                    item.section.value,
                )
                item = item.model_copy(update={"content": sanitized})
            section_items = profile.sections.setdefault(item.section, [])
            if item.action == PatchAction.ADD:
                if sanitized not in section_items:
                    section_items.append(sanitized)
            elif item.action == PatchAction.UPDATE:
                if section_items:
                    section_items[-1] = sanitized
                else:
                    section_items.append(sanitized)
            elif item.action == PatchAction.REMOVE:
                profile.sections[item.section] = [
                    x for x in section_items if x != sanitized
                ]

        self.save_profile(profile)
        return profile, rejected

    def compact_profile_for_prompt(self, max_chars: int = 2000) -> str:
        profile = self.load_profile()
        rendered = _render_markdown(profile)
        if len(rendered) <= max_chars:
            return rendered
        lines = rendered.splitlines(keepends=True)
        result: list[str] = []
        total = 0
        for line in lines:
            if total + len(line) > max_chars:
                break
            result.append(line)
            total += len(line)
        return "".join(result).rstrip()

    def get_profile_sections(self) -> dict[ProfileSection, list[str]]:
        profile = self.load_profile()
        return dict(profile.sections)

    def _write_atomic(self, content: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=".user_md_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                _ = f.write(content)
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def build_default_profile() -> UserProfile:
    return UserProfile(sections=dict(_DEFAULT_SECTIONS))
