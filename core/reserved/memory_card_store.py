"""Memory card store - reserved interface for future memory card feature.

Current phase: stub only. Do NOT implement automatic memory extraction,
vector databases, or confidence scoring.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class MemoryCard:
    id: str
    text: str
    source: str = "manual"
    created_at: datetime = field(default_factory=datetime.now)


class MemoryCardStore:
    def __init__(self):
        self._cards: list[MemoryCard] = []

    def list_cards(self) -> list[MemoryCard]:
        return list(self._cards)

    def add_card(self, text: str, source: str = "manual") -> MemoryCard:
        import uuid
        card = MemoryCard(id=str(uuid.uuid4()), text=text, source=source)
        self._cards.append(card)
        return card

    def delete_card(self, card_id: str):
        self._cards = [c for c in self._cards if c.id != card_id]

    def clear(self):
        self._cards.clear()
