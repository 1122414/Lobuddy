"""Memory maintenance for scheduled cleanup and consolidation."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from core.config import Settings
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import MemoryItem, MemoryStatus, MemoryType

logger = logging.getLogger(__name__)


class MemoryMaintenance:
    """Scheduled maintenance for memory items."""

    def __init__(self, settings: Settings, repo: Optional[MemoryRepository] = None) -> None:
        self._settings = settings
        self._repo = repo or MemoryRepository()

    def run_maintenance(self) -> dict[str, int]:
        report = {"deprecated": 0, "merged": 0, "errors": 0}
        try:
            report["deprecated"] = self._deprecate_expired()
            report["merged"] = self._merge_duplicates()
        except Exception as e:
            logger.error("Memory maintenance failed: %s", e)
            report["errors"] += 1
        return report

    def _deprecate_expired(self) -> int:
        items = self._repo.list_by_type(MemoryType.USER_PROFILE, MemoryStatus.ACTIVE, limit=1000)
        items.extend(self._repo.list_by_type(MemoryType.SYSTEM_PROFILE, MemoryStatus.ACTIVE, limit=1000))
        items.extend(self._repo.list_by_type(MemoryType.PROJECT_MEMORY, MemoryStatus.ACTIVE, limit=1000))
        count = 0
        for item in items:
            if item.is_expired():
                self._repo.update_status(item.id, MemoryStatus.DEPRECATED)
                count += 1
        return count

    def _merge_duplicates(self) -> int:
        return 0
