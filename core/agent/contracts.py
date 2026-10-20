"""Engine-independent contract for legacy task orchestration."""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel


class AgentResult(BaseModel):
    success: bool
    raw_output: str
    summary: str
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime
    tools_used: list[str] | None = None


class TaskAgent(Protocol):
    def build_session_key(self, session_id: str) -> str: ...

    async def run_task(
        self,
        prompt: str,
        session_key: str,
        *,
        pet_state: dict | None = None,
        image_path: str | None = None,
    ) -> AgentResult: ...
