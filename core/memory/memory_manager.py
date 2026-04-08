"""Memory manager for nanobot workspace integration."""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from app.config import Settings


class MemoryManager:
    """Manages nanobot memory file operations."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.memory_dir = settings.workspace_path / "memory"
        self.history_file = self.memory_dir / "history.jsonl"
        self._ensure_memory_dir()

    def _ensure_memory_dir(self):
        """Ensure memory directory exists."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def append_conversation(self, session_id: str, messages: List[Dict[str, str]]) -> bool:
        """Append conversation to history.jsonl."""
        try:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
                "message_count": len(messages),
                "messages": messages,
            }

            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            return True
        except Exception as e:
            print(f"Failed to write memory: {e}")
            return False

    def get_conversation_summary(self, messages: List[Dict[str, str]]) -> str:
        """Generate summary for memory storage."""
        # Extract key information from conversation
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]

        summary = {
            "topics": [],
            "user_queries": [m.get("content", "")[:100] for m in user_msgs[-3:]],
            "interaction_count": len(messages),
        }
        return json.dumps(summary, ensure_ascii=False)
