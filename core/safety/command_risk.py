"""Command risk assessment model for HITL (Human In The Loop) safety decisions.

This module defines the three-state command risk classification system used by
ToolPolicy and SafetyGuardrails to determine whether a shell command should be:
- ALLOW: Safe command, proceed without interruption
- HITL_REQUIRED: Dangerous but potentially legitimate — requires human confirmation
- DENY: Permanently blocked, never shown to the user for confirmation
"""

from dataclasses import dataclass, field
from enum import Enum


class CommandRiskAction(str, Enum):
    """Three-state command safety classification."""

    ALLOW = "allow"
    HITL_REQUIRED = "hitl_required"
    DENY = "deny"


@dataclass(frozen=True)
class CommandRiskAssessment:
    """Immutable result of command risk evaluation.

    Carries the decision and sufficient context for downstream systems
    (guardrails, tool tracker, UI) to act on the assessment without
    re-parsing the command.

    Does NOT hold any UI objects, futures, or execution state.
    """

    action: CommandRiskAction
    command: str
    normalized_command: str  # command after stripping quotes and .exe suffix
    command_name: str  # base command name only (e.g., "rm", "powershell")
    reason: str  # human-readable explanation of the decision
    affected_paths: tuple[str, ...] = ()
    risk_tags: tuple[str, ...] = ()


class HumanApprovalDenied(RuntimeError):
    """Raised when HITL approval is denied, timed out, or unavailable."""
    pass
