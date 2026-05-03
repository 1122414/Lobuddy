"""Skill maintenance for scheduled review and cleanup."""

import logging
from typing import Optional

from core.config import Settings
from core.skills.skill_manager import SkillManager

logger = logging.getLogger(__name__)


class SkillMaintenance:
    """Scheduled maintenance for skills."""

    def __init__(self, settings: Settings, manager: Optional[SkillManager] = None) -> None:
        self._settings = settings
        self._manager = manager

    def run_maintenance(self) -> dict[str, int]:
        report = {"reviewed": 0, "disabled": 0, "orphans_removed": 0, "errors": 0}
        if not self._manager:
            return report
        try:
            stale = self._manager.review_stale_skills()
            for skill in stale:
                refreshed = self._manager.get_skill(skill.id)
                status = refreshed.status.value if refreshed else skill.status.value
                if status == "disabled":
                    report["disabled"] += 1
                else:
                    report["reviewed"] += 1
            report["orphans_removed"] = self._manager.cleanup_orphan_workspace_files()
        except Exception as e:
            logger.error("Skill maintenance failed: %s", e)
            report["errors"] += 1
        return report
