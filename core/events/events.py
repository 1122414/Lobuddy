from dataclasses import dataclass
from pathlib import Path


@dataclass
class SubagentSpawned:
    subagent_type: str
    task_id: str
    workspace: Path


@dataclass
class SubagentCompleted:
    subagent_type: str
    task_id: str
    success: bool
    summary: str
