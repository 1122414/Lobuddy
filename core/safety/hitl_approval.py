"""HITL (Human In The Loop) approval protocol for dangerous command confirmation.

Defines the data structures and async protocol for requesting human approval
before executing dangerous shell commands. The actual UI implementation lives
in ui/hitl_approval_provider.py — this module is Qt-free and importable in tests.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True)
class HitlApprovalRequest:
    request_id: str
    session_id: str
    tool_name: str
    command: str
    working_dir: str
    reason: str
    affected_paths: tuple[str, ...]
    risk_tags: tuple[str, ...]
    created_at: datetime
    timeout_seconds: int

    @classmethod
    def create(
        cls,
        session_id: str,
        tool_name: str,
        command: str,
        working_dir: str = "",
        reason: str = "",
        affected_paths: tuple[str, ...] = (),
        risk_tags: tuple[str, ...] = (),
        timeout_seconds: int = 120,
    ) -> "HitlApprovalRequest":
        return cls(
            request_id=str(uuid.uuid4()),
            session_id=session_id,
            tool_name=tool_name,
            command=command,
            working_dir=working_dir,
            reason=reason,
            affected_paths=affected_paths,
            risk_tags=risk_tags,
            created_at=datetime.now(timezone.utc),
            timeout_seconds=timeout_seconds,
        )


@dataclass(frozen=True)
class HitlApprovalDecision:
    request_id: str
    approved: bool
    decided_at: datetime
    reason: str = ""

    @classmethod
    def approved_now(cls, request_id: str, reason: str = "") -> "HitlApprovalDecision":
        return cls(request_id=request_id, approved=True, decided_at=datetime.now(timezone.utc), reason=reason)

    @classmethod
    def rejected_now(cls, request_id: str, reason: str = "") -> "HitlApprovalDecision":
        return cls(request_id=request_id, approved=False, decided_at=datetime.now(timezone.utc), reason=reason)


class HitlApprovalProvider(Protocol):
    async def request_approval(self, request: HitlApprovalRequest) -> HitlApprovalDecision: ...


class DenyAllHitlApprovalProvider:
    """Default provider: denies all HITL requests when no UI is available.

    Used in CLI/health mode or when QtHitlApprovalProvider is not yet wired.
    """

    async def request_approval(self, request: HitlApprovalRequest) -> HitlApprovalDecision:
        return HitlApprovalDecision.rejected_now(
            request.request_id, reason="HITL approval provider is not available"
        )


async def request_approval_with_timeout(
    provider: HitlApprovalProvider,
    request: HitlApprovalRequest,
) -> HitlApprovalDecision:
    try:
        return await asyncio.wait_for(
            provider.request_approval(request),
            timeout=request.timeout_seconds,
        )
    except asyncio.TimeoutError:
        return HitlApprovalDecision.rejected_now(
            request.request_id, reason=f"HITL approval timed out after {request.timeout_seconds}s"
        )
    except Exception:
        return HitlApprovalDecision.rejected_now(
            request.request_id, reason="HITL approval provider error"
        )
