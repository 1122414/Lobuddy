"""History compression service for nanobot sessions."""

import logging
from typing import Any

from core.config import Settings
from core.runtime.token_meter import TokenMeter
from core.agent.nanobot_gateway import NanobotGateway

logger = logging.getLogger("lobuddy.history_compressor")


class HistoryCompressor:
    """Compresses conversation history when it exceeds thresholds."""

    def __init__(self, settings: Settings, token_meter: TokenMeter):
        self.settings = settings
        self.token_meter = token_meter

    async def compress_if_needed(self, gateway: NanobotGateway, session_key: str) -> None:
        """Compress oldest messages when history exceeds threshold."""
        session = gateway.get_or_create_session(session_key)
        messages = session.messages
        max_turns = self.settings.history_max_turns
        compress_threshold = self.settings.history_compress_threshold

        if len(messages) <= max_turns and not self.token_meter.should_trigger_rolling_summary(
            session_key
        ):
            return

        to_compress_count = min(compress_threshold, len(messages) // 2)
        to_compress = messages[:to_compress_count]
        remaining = messages[to_compress_count:]

        logger.info(
            f"Compressing {to_compress_count} messages for session {session_key} "
            f"(total: {len(messages)} -> {len(remaining) + 1})"
        )

        history_text = self._format_messages_for_summary(to_compress)
        summary_prompt = (
            f"{self.settings.history_compress_prompt}\n\nConversation to summarize:\n{history_text}"
        )

        try:
            from nanobot.bus.events import InboundMessage

            msg = InboundMessage(
                channel="cli",
                sender_id="user",
                chat_id="direct",
                content=summary_prompt,
            )
            response = await gateway.process_message(msg, f"{session_key}:compress")
            summary = response.content if response else "[Earlier conversation]"

            summary_msg = {"role": "assistant", "content": f"[Earlier context]: {summary}"}
            session.messages = [summary_msg] + remaining
            gateway.save_session(session)

            logger.debug(f"Compression complete, new message count: {len(session.messages)}")

        except Exception as e:
            logger.warning(f"History compression failed: {e}, falling back to truncation")
            session.messages = remaining
            gateway.save_session(session)

    @staticmethod
    def _format_messages_for_summary(messages: list) -> str:
        """Format messages for compression prompt."""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 500:
                content = content[:500] + "..."
            elif isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if len(text) > 500:
                            text = text[:500] + "..."
                        text_parts.append(text)
                content = " ".join(text_parts) if text_parts else "[multimodal content]"
            if isinstance(content, str):
                content = content.replace("<<<CONTENT>>>", "")
                content = content.replace("<<<END_CONTENT>>>", "")
            lines.append(f"{role}: <<<CONTENT>>>{content}<<<END_CONTENT>>>")
        return "\n".join(lines)
