"""Repository for HITL approval audit logging."""

import hashlib
import json
import logging
from datetime import datetime, timezone

from core.storage.db import get_database

logger = logging.getLogger("lobuddy.hitl_audit")


class HitlApprovalRepository:
    def _sanitize_command_preview(self, command: str, max_chars: int = 500) -> str:
        import re

        sanitized = re.sub(r"\b(sk-[a-zA-Z0-9]{20,})\b", "[REDACTED_API_KEY]", command)
        sanitized = re.sub(
            r"\b(bearer\s+[a-zA-Z0-9_-]{20,})\b", "[REDACTED_TOKEN]", sanitized, flags=re.IGNORECASE
        )
        sanitized = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL]", sanitized)
        return sanitized[:max_chars]

    def log_decision(
        self,
        session_id: str,
        tool_name: str,
        command: str,
        working_dir: str,
        affected_paths: tuple[str, ...],
        risk_tags: tuple[str, ...],
        reason: str,
        approved: bool,
        decision_reason: str,
    ) -> None:
        db = get_database()
        try:
            command_hash = hashlib.sha256(command.encode("utf-8", errors="replace")).hexdigest()
            command_preview = self._sanitize_command_preview(command)
            paths_json = json.dumps(list(affected_paths)[:10], ensure_ascii=False)
            tags_json = json.dumps(list(risk_tags), ensure_ascii=False)
            decision = "approved" if approved else "rejected"
            now = datetime.now(timezone.utc).isoformat()

            with db.get_connection() as conn:
                conn.execute(
                    """INSERT INTO hitl_approval_log
                       (id, session_id, tool_name, command_hash, command_preview,
                        working_dir, affected_paths_json, risk_tags_json, reason,
                        decision, decision_reason, created_at, decided_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"{session_id}:{command_hash[:16]}",
                        session_id,
                        tool_name,
                        command_hash,
                        command_preview,
                        working_dir[:200] if working_dir else "",
                        paths_json,
                        tags_json,
                        reason[:500],
                        decision,
                        decision_reason[:500] if decision_reason else "",
                        now,
                        now,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.debug("Failed to write HITL audit log: %s", e)
