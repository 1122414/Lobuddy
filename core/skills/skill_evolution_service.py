"""Governed skill evolution from successful task evidence."""

from __future__ import annotations

import logging

from core.config import Settings
from core.skills.skill_candidate_extractor import SkillCandidateExtractor
from core.skills.skill_manager import SkillManager
from core.skills.skill_schema import CandidateSource, SkillCandidate
from core.skills.skill_validator import SkillValidator

logger = logging.getLogger(__name__)


class SkillEvolutionService:
    """Turns safe, successful workflows into review-only skill proposals.

    This service never activates a skill. It stores a sanitized proposal that
    the user can inspect, approve, reject, disable, or archive in Skill Lab.
    """

    _NON_LEARNABLE_TOOLS = {
        "computer_act",
        "computer_authorize",
        "exec",
        "shell",
    }

    def __init__(self, settings: Settings, manager: SkillManager) -> None:
        self._settings = settings
        self._manager = manager

    def update_settings(self, settings: Settings) -> None:
        self._settings = settings

    def consider_task(
        self,
        *,
        success: bool,
        task_input: str,
        tools_used: list[str],
        output_length: int,
        session_id: str,
        task_id: str,
        privacy_active: bool,
        has_image: bool,
    ) -> SkillCandidate | None:
        if not success or privacy_active or has_image:
            return None
        if not self._settings.skill_lab_enabled:
            return None
        if not self._settings.skill_candidate_review_enabled:
            return None

        extractor = SkillCandidateExtractor(
            min_tools_used=self._settings.skill_candidate_min_tools_used
        )
        explicit_request = extractor.has_strong_signal(task_input)
        if not self._settings.skill_auto_candidate_enabled and not explicit_request:
            return None

        safe_tools = list(dict.fromkeys(str(tool) for tool in tools_used if tool))
        if not safe_tools or self._NON_LEARNABLE_TOOLS.intersection(safe_tools):
            return None
        if not extractor.should_extract(success, safe_tools, task_input):
            return None

        candidate = extractor.extract_candidate(
            task_input=task_input,
            tools_used=safe_tools,
            raw_output=(
                "Successful outcome verified. Task-specific output was intentionally "
                "omitted from this proposal."
            ),
            session_id=session_id,
            task_id=task_id,
        )
        if candidate is None:
            return None
        candidate.source_kind = CandidateSource.SUCCESSFUL_TASK
        if self._manager.get_skill_by_name(candidate.proposed_name) is not None:
            return None
        if self._manager.find_candidate_by_name(candidate.proposed_name) is not None:
            return None

        candidate.evidence = {
            "source": "successful_task",
            "tools": safe_tools,
            "tool_count": len(safe_tools),
            "explicit_user_request": explicit_request,
            "output_chars": max(0, int(output_length)),
            "privacy_checked": True,
            "multimodal_content_stored": False,
            "activation_requires_review": True,
        }
        validator = SkillValidator()
        valid_candidate, candidate_errors = validator.validate(candidate)
        valid_static, static_errors = validator.validate_static(candidate.proposed_content)
        candidate.validation_errors = list(dict.fromkeys([*candidate_errors, *static_errors]))
        if not valid_candidate or not valid_static:
            logger.info(
                "Skill evolution proposal rejected by static validation: %s",
                candidate.validation_errors,
            )
            return None

        self._manager.create_candidate(candidate, defer_evaluation=True)
        logger.info(
            "Skill evolution proposal created: name=%s tools=%s explicit=%s",
            candidate.proposed_name,
            safe_tools,
            explicit_request,
        )
        return candidate
