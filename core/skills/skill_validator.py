"""Skill validator for checking candidate quality and safety."""

import logging
import re
from typing import Optional

from core.skills.skill_schema import SkillCandidate

logger = logging.getLogger(__name__)

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"xoxb-[a-zA-Z0-9-]+"),
    re.compile(r"Bearer\s+[a-zA-Z0-9._-]+"),
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
]

_DANGEROUS_COMMANDS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(rm\s+-rf|del\s+/f|format\s+|mkfs|dd\s+if=|shutdown|reboot|poweroff)\b", re.IGNORECASE
    ),
    re.compile(r"\b(curl\s+.*\|\s*sh|wget\s+.*\|\s*sh)\b", re.IGNORECASE),
    re.compile(r"\b(eval\s*\(|exec\s*\(|os\.system|subprocess\.call)\b", re.IGNORECASE),
    re.compile(r"\b(import\s+os\s*;\s*os\.system|import\s+subprocess)\b", re.IGNORECASE),
]

_MAX_SKILL_LINES = 500


class SkillValidator:
    """Validates skill candidates before approval."""

    def validate(self, candidate: SkillCandidate) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not candidate.proposed_name or len(candidate.proposed_name) > 50:
            errors.append("Invalid skill name (1-50 chars required)")
        if not candidate.proposed_content or len(candidate.proposed_content) < 50:
            errors.append("Skill content too short (min 50 chars)")
        lines = candidate.proposed_content.splitlines()
        if len(lines) > _MAX_SKILL_LINES:
            errors.append(f"Skill content too long ({len(lines)} lines, max {_MAX_SKILL_LINES})")
        if self._contains_secrets(candidate.proposed_content):
            errors.append("Skill content contains sensitive information")
        if self._contains_dangerous_commands(candidate.proposed_content):
            errors.append("Content contains dangerous commands")
        if candidate.confidence < 0.5:
            errors.append("Confidence too low (< 0.5)")
        return len(errors) == 0, errors

    def validate_static(self, content: str) -> tuple[bool, list[str]]:
        """Static validation for skill content (P2-D3).

        Checks:
        - Has SKILL.md format (frontmatter)
        - Has clear trigger rules
        - Does not contain dangerous commands
        - Does not contain secrets
        """
        errors: list[str] = []
        if not content or len(content) < 50:
            errors.append("Skill content too short (min 50 chars)")

        lines = content.splitlines()
        if len(lines) > _MAX_SKILL_LINES:
            errors.append(f"Skill content too long ({len(lines)} lines, max {_MAX_SKILL_LINES})")

        if not self._has_frontmatter(content):
            errors.append("Missing SKILL.md frontmatter (--- name: ... ---)")

        if not self._has_trigger_rules(content):
            errors.append(
                "No clear trigger rules found (expected: trigger, when, use, or description)"
            )

        if self._contains_dangerous_commands(content):
            errors.append("Content contains dangerous commands")

        if self._contains_secrets(content):
            errors.append("Content contains sensitive information")

        return len(errors) == 0, errors

    def check_duplicate(
        self,
        candidate: SkillCandidate,
        existing_names: list[str],
    ) -> Optional[str]:
        candidate_name = candidate.proposed_name.lower()
        for name in existing_names:
            if name.lower() == candidate_name:
                return name
        return None

    @staticmethod
    def _has_frontmatter(content: str) -> bool:
        """Check if content has YAML frontmatter."""
        return content.startswith("---") and "\n---" in content

    @staticmethod
    def _has_trigger_rules(content: str) -> bool:
        """Check if content has clear trigger rules."""
        # Split content to separate frontmatter from body
        parts = content.split("---", 2)
        body = parts[-1] if len(parts) > 1 else content
        body_lower = body.lower()
        trigger_patterns = [
            r"\bwhen\s+to\s+use\b",
            r"\bwhen\s+(?:the\s+)?user\b",
            r"\buse\s+this\b",
            r"##\s*(trigger|when to use|usage)",
        ]
        return any(re.search(p, body_lower) for p in trigger_patterns)

    @staticmethod
    def _contains_dangerous_commands(text: str) -> bool:
        """Check if text contains dangerous shell/commands."""
        for pat in _DANGEROUS_COMMANDS:
            if pat.search(text):
                return True
        return False

    @staticmethod
    def _contains_secrets(text: str) -> bool:
        for pat in _SECRET_PATTERNS:
            if pat.search(text):
                return True
        return False
