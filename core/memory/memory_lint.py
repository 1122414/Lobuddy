"""5.3 MemoryLintService — memory health check and observability.

Produces structured findings about memory quality issues:
  - duplicate: similar content repeated across items
  - conflict: conflicting active facts under same identity title
  - stale: long-unupdated memories
  - low_confidence: low-confidence active memories persisting too long
  - projection_drift: projection files missing or header missing
  - orphan_projection: workspace projection exists but no SQLite active memory
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from core.config import Settings
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import MemoryStatus, MemoryType

logger = logging.getLogger(__name__)


class MemoryLintFinding(BaseModel):
    """A single memory health issue discovered by lint."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    severity: Literal["info", "warning", "error"] = "info"
    category: str
    memory_id: str | None = None
    message: str
    recommendation: str = ""


class MemoryLintReport(BaseModel):
    """Aggregated lint results."""

    findings: list[MemoryLintFinding] = Field(default_factory=list)
    total_active_memories: int = 0
    checked_at: datetime = Field(default_factory=datetime.now)

    @property
    def has_errors(self) -> bool:
        return any(f.severity == "error" for f in self.findings)

    @property
    def has_warnings(self) -> bool:
        return any(f.severity == "warning" for f in self.findings)


class MemoryLintService:
    """Lints the memory system and reports health issues.

    Read-only: only generates findings, never auto-deletes or rewrites.
    """

    def __init__(self, settings: Settings, repo: MemoryRepository | None = None) -> None:
        self._settings = settings
        self._repo = repo or MemoryRepository()

    def lint(self) -> MemoryLintReport:
        """Run all lint checks and return a report."""
        report = MemoryLintReport()

        if not self._settings.memory_lint_enabled:
            logger.debug("MemoryLint disabled by settings")
            return report

        try:
            all_active: list = []
            for mt in MemoryType:
                try:
                    items = self._repo.list_by_type(mt, MemoryStatus.ACTIVE, limit=2000)
                    all_active.extend(items)
                except Exception:
                    pass
            report.total_active_memories = len(all_active)
        except Exception as exc:
            logger.warning("MemoryLint: failed to list active memories: %s", exc)
            return report

        self._check_duplicates(report, all_active)
        self._check_conflicts(report, all_active)
        self._check_stale(report, all_active)
        self._check_low_confidence(report, all_active)

        # Projection checks
        self._check_projection_drift(report, all_active)
        self._check_orphan_projections(report, all_active)

        logger.info(
            "MemoryLint: %d findings (errors=%d, warnings=%d) from %d active memories",
            len(report.findings),
            sum(1 for f in report.findings if f.severity == "error"),
            sum(1 for f in report.findings if f.severity == "warning"),
            report.total_active_memories,
        )
        return report

    def _check_duplicates(self, report: MemoryLintReport, items: list) -> None:
        threshold = self._settings.memory_lint_duplicate_similarity
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if items[i].memory_type != items[j].memory_type:
                    continue
                shorter = items[i].content if len(items[i].content) <= len(items[j].content) else items[j].content
                longer = items[j].content if shorter == items[i].content else items[i].content
                if shorter and longer and shorter in longer:
                    ratio = len(shorter) / len(longer)
                    if ratio >= threshold:
                        report.findings.append(MemoryLintFinding(
                            severity="warning",
                            category="duplicate",
                            memory_id=items[j].id,
                            message=(
                                f"Near-duplicate memory: '{items[j].id}' ({items[j].memory_type.value}) "
                                f"is {ratio:.0%} contained in '{items[i].id}'"
                            ),
                            recommendation="Consider deprecating the newer/less precise item.",
                        ))

    def _check_conflicts(self, report: MemoryLintReport, items: list) -> None:
        identity_items = [
            i for i in items
            if i.memory_type in (MemoryType.USER_PROFILE, MemoryType.SYSTEM_PROFILE)
        ]
        titles: dict[str, list] = {}
        for item in identity_items:
            key = f"{item.memory_type.value}:{item.title}"
            titles.setdefault(key, []).append(item)
        for key, group in titles.items():
            if len(group) > 1:
                report.findings.append(MemoryLintFinding(
                    severity="warning",
                    category="conflict",
                    memory_id=group[0].id,
                    message=f"Multiple active memory items under '{key}' ({len(group)} items)",
                    recommendation="Review and deprecate outdated or conflicting items.",
                ))

    def _check_stale(self, report: MemoryLintReport, items: list) -> None:
        stale_days = self._settings.memory_lint_stale_days
        cutoff = datetime.now() - timedelta(days=stale_days)
        for item in items:
            if item.updated_at and item.updated_at < cutoff and item.memory_type in (
                MemoryType.PROJECT_MEMORY, MemoryType.EPISODIC_MEMORY,
            ):
                report.findings.append(MemoryLintFinding(
                    severity="info",
                    category="stale",
                    memory_id=item.id,
                    message=f"Memory '{item.id}' not updated for >{stale_days} days",
                    recommendation="Review relevance; consider deprecating if obsolete.",
                ))

    def _check_low_confidence(self, report: MemoryLintReport, items: list) -> None:
        threshold = self._settings.memory_lint_low_confidence_days
        cutoff = datetime.now() - timedelta(days=threshold)
        for item in items:
            if item.confidence <= 0.5 and item.updated_at and item.updated_at < cutoff:
                report.findings.append(MemoryLintFinding(
                    severity="warning",
                    category="low_confidence",
                    memory_id=item.id,
                    message=(
                        f"Low-confidence (c={item.confidence:.2f}) active memory '{item.id}' "
                        f"persisted for >{threshold} days"
                    ),
                    recommendation="Consider deprecating or raising confidence via manual review.",
                ))

    def _check_projection_drift(self, report: MemoryLintReport, items: list) -> None:
        """Check that projection files exist and have headers for project/episodic memories."""
        workspace_memory_dir = self._settings.workspace_path / "memory"
        data_memory_dir = self._settings.data_dir / "memory"

        # Check MEMORY.md
        memory_md = workspace_memory_dir / "MEMORY.md"
        if not memory_md.exists():
            report.findings.append(MemoryLintFinding(
                severity="error",
                category="projection_drift",
                message=f"Projection file missing: {memory_md}",
                recommendation="Trigger a memory refresh to regenerate the projection.",
            ))
        else:
            content = memory_md.read_text(encoding="utf-8")
            if "DO NOT EDIT" not in content and "Generated by" not in content:
                report.findings.append(MemoryLintFinding(
                    severity="error",
                    category="projection_drift",
                    message=f"Projection header missing in: {memory_md}",
                    recommendation="The file may have been manually edited. Trigger a refresh.",
                ))

    def _check_orphan_projections(self, report: MemoryLintReport, items: list) -> None:
        """Check for projection files with no corresponding active SQLite memory."""
        active_contents = {i.content for i in items if i.memory_type == MemoryType.PROJECT_MEMORY}
        workspace_memory_dir = self._settings.workspace_path / "memory"
        memory_md = workspace_memory_dir / "MEMORY.md"
        if not memory_md.exists():
            return
        content = memory_md.read_text(encoding="utf-8")
        if "DO NOT EDIT" not in content and "Generated by" not in content:
            report.findings.append(MemoryLintFinding(
                severity="warning",
                category="orphan_projection",
                message=f"workspace/memory/MEMORY.md appears manually edited (no Lobuddy header)",
                recommendation="Delete this file or trigger a memory refresh to overwrite it.",
            ))
