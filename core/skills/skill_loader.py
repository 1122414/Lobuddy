"""Skill loader for reading workspace and built-in SKILL.md files."""

import logging
import re
from pathlib import Path

from core.skills.skill_schema import SkillRecord, SkillStatus

logger = logging.getLogger(__name__)


class SkillLoader:
    """Loads SKILL.md files from workspace and converts to SkillRecords."""

    def __init__(self, workspace_skills_dir: Path) -> None:
        self._workspace_skills = workspace_skills_dir

    def discover_skills(self) -> list[SkillRecord]:
        records: list[SkillRecord] = []
        if not self._workspace_skills.exists():
            return records
        for skill_dir in self._workspace_skills.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            meta = self._parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            record = SkillRecord(
                id=skill_dir.name,
                name=meta.get("name", skill_dir.name),
                path=str(skill_file),
                description=meta.get("description", ""),
                category=meta.get("category", "general"),
                status=SkillStatus.ACTIVE,
                source="import",
            )
            records.append(record)
        return records

    def load_content(self, skill_path: str) -> str:
        path = Path(skill_path)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _parse_frontmatter(content: str) -> dict[str, str]:
        meta: dict[str, str] = {}
        if not content.startswith("---"):
            return meta
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return meta
        for line in match.group(1).split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip().strip('"\'')
        return meta
