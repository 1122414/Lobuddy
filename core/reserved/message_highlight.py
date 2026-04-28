"""Message highlight / bookmark store - reserved interface for future feature.

Current phase: stub only. Do NOT implement full-text search, tagging,
or cloud sync.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Highlight:
    id: str
    session_id: str
    message_id: str
    content: str
    created_at: datetime = field(default_factory=datetime.now)


class MessageHighlightStore:
    def __init__(self):
        self._highlights: list[Highlight] = []

    def add_highlight(self, session_id: str, message_id: str, content: str) -> Highlight:
        import uuid
        h = Highlight(id=str(uuid.uuid4()), session_id=session_id,
                      message_id=message_id, content=content)
        self._highlights.append(h)
        return h

    def get_highlights(self, session_id: str = None) -> list[Highlight]:
        if session_id:
            return [h for h in self._highlights if h.session_id == session_id]
        return list(self._highlights)

    def remove_highlight(self, highlight_id: str):
        self._highlights = [h for h in self._highlights if h.id != highlight_id]
