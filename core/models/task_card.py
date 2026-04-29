"""Task card data models for Lobuddy."""

from dataclasses import dataclass, field
from typing import Literal

TaskCardStatus = Literal["pending", "running", "success", "warning", "failed"]


@dataclass
class TaskStep:
    text: str
    status: TaskCardStatus


@dataclass
class TaskCardModel:
    title: str
    status: TaskCardStatus
    steps: list[TaskStep] = field(default_factory=list)
    short_result: str = ""
    details: str = ""
    exp_reward: int = 0
    task_id: str = ""
    available_actions: list[str] = field(default_factory=list)
