from datetime import datetime
from typing import Any, Generic, Optional, TypeVar

from core.storage.db import Database, get_database

T = TypeVar("T")


def _parse_iso(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return datetime.now()


class BaseRepository(Generic[T]):
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
