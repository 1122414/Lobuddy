"""Data models for Lobuddy."""

from datetime import datetime
from enum import Enum
from typing import ClassVar, Optional

from pydantic import BaseModel, Field

from core.models.personality import PetPersonality


class EvolutionStage(int, Enum):
    """Pet evolution stages."""

    STAGE_1 = 1  # Lv1-Lv3: 幼年形态
    STAGE_2 = 2  # Lv4-Lv7: 成长形态
    STAGE_3 = 3  # Lv8-Lv10: 完全形态


class TaskStatus(str, Enum):
    """Task execution status."""

    IDLE = "idle"
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskDifficulty(str, Enum):
    """Task difficulty levels."""

    SIMPLE = "simple"  # +5 EXP
    MEDIUM = "medium"  # +15 EXP
    COMPLEX = "complex"  # +30 EXP


class PetState(BaseModel):
    """Pet state model.

    Attributes:
        id: Unique pet identifier
        name: Pet display name
        level: Current level (1-10)
        exp: Current experience points
        evolution_stage: Current evolution stage (1-3)
        mood: Current mood description
        skin: Current skin/appearance identifier
        created_at: When pet was created
        updated_at: Last update timestamp
    """

    id: str = Field(default="default")
    name: str = Field(default="Lobuddy")
    level: int = Field(default=1, ge=1, le=10)
    exp: int = Field(default=0, ge=0)
    evolution_stage: EvolutionStage = Field(default=EvolutionStage.STAGE_1)
    mood: str = Field(default="happy")
    skin: str = Field(default="default")
    personality: PetPersonality = Field(default_factory=PetPersonality)
    _EXP_TABLE: ClassVar[tuple[int, ...]] = (
        50,    # Lv1->Lv2
        120,   # Lv2->Lv3
        220,   # Lv3->Lv4
        350,   # Lv4->Lv5
        520,   # Lv5->Lv6
        720,   # Lv6->Lv7
        950,   # Lv7->Lv8
        1220,  # Lv8->Lv9
        1550,  # Lv9->Lv10
    )

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def get_exp_for_next_level(self) -> int:
        if self.level <= 9:
            return self._EXP_TABLE[self.level - 1]
        return 9999

    def get_evolution_stage_for_level(self, level: int) -> EvolutionStage:
        return EvolutionStage(min(level // 4 + 1, 3))

    def add_exp(self, amount: int) -> bool:
        """Add EXP and check if level up occurred.

        Returns:
            True if level up occurred

        Raises:
            ValueError: If amount is negative
        """
        if amount < 0:
            raise ValueError(f"EXP amount must be non-negative, got {amount}")
        self.exp += amount
        self.updated_at = datetime.now()

        # Check level up
        level_up = False
        while self.level < 10 and self.exp >= self.get_exp_for_next_level():
            self.exp -= self.get_exp_for_next_level()
            self.level += 1
            level_up = True

            # Update evolution stage
            new_stage = self.get_evolution_stage_for_level(self.level)
            if new_stage != self.evolution_stage:
                self.evolution_stage = new_stage

        return level_up


class TaskRecord(BaseModel):
    """Task record model.

    Attributes:
        id: Unique task identifier
        input_text: User input prompt
        task_type: Task type/category
        status: Current execution status
        difficulty: Task difficulty level
        reward_exp: EXP reward for completion
        created_at: When task was created
        started_at: When task started execution
        finished_at: When task finished execution
    """

    id: str
    input_text: str
    task_type: str = Field(default="general")
    status: TaskStatus = Field(default=TaskStatus.CREATED)
    difficulty: TaskDifficulty = Field(default=TaskDifficulty.SIMPLE)
    reward_exp: int = Field(default=5, ge=0)
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)

    _VALID_TRANSITIONS: ClassVar[dict[TaskStatus, set[TaskStatus]]] = {
        TaskStatus.IDLE: {TaskStatus.CREATED, TaskStatus.QUEUED, TaskStatus.RUNNING},
        TaskStatus.CREATED: {TaskStatus.QUEUED, TaskStatus.RUNNING},
        TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.FAILED},
        TaskStatus.RUNNING: {TaskStatus.SUCCESS, TaskStatus.FAILED},
        TaskStatus.SUCCESS: set(),
        TaskStatus.FAILED: set(),
        TaskStatus.CANCELLED: set(),
    }

    def _validate_transition(self, new_status: TaskStatus) -> None:
        if new_status == self.status:
            return
        valid_next = self._VALID_TRANSITIONS.get(self.status, set())
        if new_status not in valid_next:
            raise ValueError(
                f"Invalid state transition: {self.status.value} -> {new_status.value}"
            )

    def start(self):
        """Mark task as started."""
        self._validate_transition(TaskStatus.RUNNING)
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now()

    def complete(self, success: bool):
        """Mark task as completed."""
        new_status = TaskStatus.SUCCESS if success else TaskStatus.FAILED
        self._validate_transition(new_status)
        self.status = new_status
        self.finished_at = datetime.now()


class TaskResult(BaseModel):
    """Task execution result model.

    Attributes:
        task_id: Reference to task record
        success: Whether execution succeeded
        raw_result: Full execution output
        summary: Truncated summary for display
        error_message: Error details if failed
        created_at: When result was saved
    """

    task_id: str
    success: bool
    raw_result: str = Field(default="")
    summary: str = Field(default="")
    error_message: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.now)


class PetProgressEvent(BaseModel):
    exp_gained: int = 0
    current_exp: int = 0
    required_exp: int = 0
    level_up: bool = False
    new_level: int | None = None
    new_stage: int | None = None
    personality_adjustments: dict | None = None
    unlocked_abilities: list[tuple[str, str]] = Field(default_factory=list)


class AppSettings(BaseModel):
    key: str
    value: str
    updated_at: datetime = Field(default_factory=datetime.now)
