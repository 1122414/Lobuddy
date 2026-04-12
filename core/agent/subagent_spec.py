from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubagentSpec:
    model: str
    base_url: str | None = None
    api_key: str | None = None
    system_prompt: str | None = None
    max_iterations: int = 5
    temperature: float | None = None
    extra_config: dict[str, Any] = field(default_factory=dict)
