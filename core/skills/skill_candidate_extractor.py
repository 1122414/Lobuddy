"""Skill candidate extractor for analyzing successful tasks."""

import hashlib
import logging
import re
import uuid
from typing import Optional

from core.skills.skill_schema import CandidateSource, SkillCandidate

logger = logging.getLogger(__name__)


class SkillCandidateExtractor:
    """Extracts skill candidates from task results."""

    def __init__(self, min_tools_used: int = 2) -> None:
        self._min_tools_used = min_tools_used

    def should_extract(
        self,
        success: bool,
        tools_used: list[str],
        user_message: str = "",
    ) -> bool:
        if not success:
            return False
        if len(tools_used) >= self._min_tools_used:
            return True
        strong_signals = [
            "以后这样",
            "记住这个",
            "保存为技能",
            "create skill",
            "save as skill",
        ]
        lower = user_message.lower()
        return any(s in lower for s in strong_signals)

    def extract_candidate(
        self,
        task_input: str,
        tools_used: list[str],
        raw_output: str,
        session_id: str = "",
        task_id: str = "",
    ) -> Optional[SkillCandidate]:
        if not self.should_extract(True, tools_used, task_input):
            return None
        safe_task = self._sanitize_evidence(task_input, limit=240)
        safe_output = self._sanitize_evidence(raw_output, limit=500)
        name = self._generate_name(safe_task)
        content = self._build_skill_md(name, safe_task, tools_used, safe_output)
        explicit_request = self.has_strong_signal(task_input)
        return SkillCandidate(
            id=str(uuid.uuid4()),
            title=f"可复用流程：{name}",
            rationale=f"来自一次成功任务，使用了 {len(set(tools_used))} 种工具；等待你审核。",
            proposed_name=name,
            proposed_content=content,
            source_session_id=session_id,
            source_task_id=task_id,
            source_kind=CandidateSource.SUCCESSFUL_TASK,
            confidence=0.9 if explicit_request else 0.7,
        )

    @staticmethod
    def _generate_name(task_input: str) -> str:
        words = re.findall(r"[a-z0-9]+", task_input.lower())[:4]
        if words:
            return "-".join(words)[:50]
        digest = hashlib.sha256(task_input.encode("utf-8")).hexdigest()[:8]
        return f"learned-workflow-{digest}"

    @staticmethod
    def _build_skill_md(name: str, task_input: str, tools_used: list[str], raw_output: str) -> str:
        tool_steps = [
            f"{index}. Use `{tool}` only when its normal safety policy allows it."
            for index, tool in enumerate(dict.fromkeys(tools_used), start=1)
        ]
        lines = [
            "---",
            f"name: {name}",
            "description: Reuse this reviewed workflow for similar successful tasks.",
            "---",
            "",
            f"# {name}",
            "",
            "## When to use",
            "",
            f"Use this skill when the user asks for a task similar to: {task_input}",
            "",
            "## Workflow",
            "",
            *tool_steps,
            f"{len(tool_steps) + 1}. Verify the result against the user's stated goal.",
            "",
            "## Safety and validation",
            "",
            "- Keep normal Lobuddy path, command, URL, privacy, and approval guardrails active.",
            "- Never reuse credentials, private content, or task-specific absolute paths.",
            "- Stop and ask the user before any destructive or high-impact action.",
            "",
            "## Sanitized evidence",
            "",
            raw_output,
        ]
        return "\n".join(lines)

    @staticmethod
    def has_strong_signal(user_message: str) -> bool:
        lower = user_message.lower()
        return any(
            signal in lower
            for signal in (
                "以后这样",
                "记住这个",
                "保存为技能",
                "create skill",
                "save as skill",
            )
        )

    @staticmethod
    def _sanitize_evidence(text: str, *, limit: int) -> str:
        sanitized = str(text or "")
        patterns = (
            (r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED_API_KEY]"),
            (r"\bghp_[A-Za-z0-9]{20,}\b", "[REDACTED_TOKEN]"),
            (r"\bxoxb-[A-Za-z0-9-]+\b", "[REDACTED_TOKEN]"),
            (r"\bBearer\s+[A-Za-z0-9._-]+\b", "[REDACTED_TOKEN]"),
            (
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
                "[REDACTED_EMAIL]",
            ),
            (
                r"(?i)\b(?:password|passwd|pwd|api[_ -]?key|token|secret)" r"\s*[:=]\s*[^\s,;]+",
                "[REDACTED_CREDENTIAL]",
            ),
            (r"\b(?:\d[ -]?){13,19}\b", "[REDACTED_NUMBER]"),
            (r"(?i)\b[A-Z]:\\Users\\[^\\\s]+", "C:/Users/[USER]"),
            (r"/(?:home|Users)/[^/\s]+", "/home/[USER]"),
        )
        for pattern, replacement in patterns:
            sanitized = re.sub(pattern, replacement, sanitized)
        sanitized = " ".join(sanitized.split())
        return sanitized[:limit]
