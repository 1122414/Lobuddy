"""User profile service - orchestrates profile updates and injection."""

import json
import logging
import re
from typing import Optional

from core.config import Settings
from core.memory.user_profile_manager import UserProfileManager
from core.memory.user_profile_schema import ProfilePatch, ProfilePatchItem
from core.memory.user_profile_triggers import (
    has_strong_signal,
    should_update_on_message_count,
)
from core.memory.user_profile_prompts import (
    PROFILE_INJECTION_HEADER,
    PROFILE_UPDATE_PROMPT,
)

logger = logging.getLogger(__name__)


class UserProfileService:
    """Orchestrates user profile updates and prompt injection."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._manager = UserProfileManager(settings.memory_profile_file)
        self._user_message_count: int = 0

        if settings.memory_profile_enabled:
            self._manager.ensure_profile_file()

    def record_user_message(self) -> None:
        """Increment user message counter."""
        self._user_message_count += 1

    def should_update_profile(self, last_user_message: str) -> bool:
        """Check if profile should be updated based on triggers."""
        if not self._settings.memory_profile_enabled:
            return False

        # Check message count trigger
        if should_update_on_message_count(
            self._user_message_count,
            self._settings.memory_profile_update_every_n_user_messages,
        ):
            return True

        # Check strong signal trigger
        if (
            self._settings.memory_profile_update_on_strong_signal
            and has_strong_signal(last_user_message)
        ):
            return True

        return False

    def get_profile_context(self) -> Optional[str]:
        """Get compact profile context for injection into prompts."""
        if not self._settings.memory_profile_enabled:
            return None
        if not self._settings.memory_profile_inject_enabled:
            return None

        compact = self._manager.compact_profile_for_prompt(
            self._settings.memory_profile_max_inject_chars
        )

        if not compact or compact.isspace():
            return None

        return PROFILE_INJECTION_HEADER + compact

    def build_update_prompt(self, recent_messages: list[dict[str, str]]) -> str:
        """Build prompt for AI to analyze conversation and extract profile info."""
        current_profile = self._manager.compact_profile_for_prompt(
            self._settings.memory_profile_max_inject_chars
        )

        conversation_text = "\n".join(
            f"{msg['role']}: {msg['content']}" for msg in recent_messages
        )

        return PROFILE_UPDATE_PROMPT.format(
            conversation=conversation_text,
            current_profile=current_profile,
        )

    def apply_ai_response(self, ai_response: str) -> tuple[bool, str]:
        """Parse AI response and apply profile patch.

        Returns:
            Tuple of (success, message). If success is True, message describes
            what was updated. If False, message describes the error.
        """
        try:
            json_str = self._extract_json(ai_response)
            if not json_str:
                return False, "No JSON found in response"

            data = json.loads(json_str)

            # Handle both single item and list
            if isinstance(data, dict):
                items = [data]
            elif isinstance(data, list):
                items = data
            else:
                return False, "Invalid JSON format"

            # Limit items
            items = items[: self._settings.memory_profile_max_patch_items]

            # Build patch
            patch_items = []
            for item in items:
                try:
                    patch_item = ProfilePatchItem(**item)
                    patch_items.append(patch_item)
                except Exception as e:
                    logger.warning(f"Skipping invalid patch item: {e}")
                    continue

            if not patch_items:
                return False, "No valid patch items"

            patch = ProfilePatch(items=patch_items)
            _profile, rejected = self._manager.apply_patch(
                patch,
                require_high_confidence=self._settings.memory_profile_require_high_confidence,
                min_confidence=self._settings.memory_profile_min_confidence,
            )

            updated_count = len(patch_items) - len(rejected)
            if updated_count == 0:
                return False, f"All {len(rejected)} items rejected"

            msg = f"Updated {updated_count} items"
            if rejected:
                msg += f", rejected {len(rejected)} items"
            return True, msg

        except json.JSONDecodeError as e:
            return False, f"Invalid JSON: {e}"
        except Exception as e:
            logger.error(f"Failed to apply AI response: {e}")
            return False, f"Error: {e}"

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        """Extract JSON from text, handling markdown code blocks."""
        # Try to find JSON in code block
        json_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_block:
            return json_block.group(1).strip()

        # Try to find raw JSON array
        start = text.find("[")
        if start != -1:
            end = text.rfind("]")
            if end > start:
                return text[start : end + 1]

        # Try to find raw JSON object
        start = text.find("{")
        if start != -1:
            end = text.rfind("}")
            if end > start:
                return text[start : end + 1]

        return None

    def reset_message_count(self) -> None:
        """Reset user message counter (e.g., on session end)."""
        self._user_message_count = 0
