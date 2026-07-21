"""Skill selector for choosing active skills for prompt injection."""

import logging
from typing import Optional

from core.skills.skill_manager import SkillManager
from core.skills.skill_schema import SkillRecord, SkillStatus

logger = logging.getLogger(__name__)


class SkillSelector:
    """Selects active skills for inclusion in AI prompts."""

    def __init__(self, manager: Optional[SkillManager] = None) -> None:
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
