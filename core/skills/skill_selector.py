"""Skill selector for choosing active skills for prompt injection."""

import logging
import re

from core.skills.skill_manager import SkillManager
from core.skills.skill_schema import SkillRecord, SkillStatus

logger = logging.getLogger(__name__)


class SkillSelector:
    """Selects active skills for inclusion in AI prompts."""

    def __init__(self, manager: SkillManager | None = None) -> None:
        self._manager = manager

    def select_active_skills(self, limit: int = 10) -> list[SkillRecord]:
        if not self._manager:
            return []
        return self._manager.list_skills(status=SkillStatus.ACTIVE, limit=limit)

    def build_skills_summary(self, limit: int = 10) -> str:
        skills = self.select_active_skills(limit)
        if not skills:
            return ""
        lines: list[str] = []
        for skill in skills:
            lines.append(f"- **{skill.name}**: {skill.description}")
        return "\n".join(lines)

    def select_relevant(self, query: str, limit: int = 8) -> list[SkillRecord]:
        """Small lexical ranking; descriptions first, bodies available through governed read."""

        def terms(text: str) -> set[str]:
            normalized = text.casefold()
            values = set(re.findall(r"[a-z0-9_-]+", normalized))
            for segment in re.findall(r"[\u4e00-\u9fff]+", normalized):
                values.update(segment[i : i + 2] for i in range(len(segment) - 1))
            return values

        wanted = terms(query)
        scored = [
            (len(wanted & terms(item.name + " " + item.description)), item)
            for item in self.select_active_skills(1000)
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1].name))
        return [item for score, item in scored if score > 0][:limit]
