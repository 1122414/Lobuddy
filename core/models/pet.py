"""Data models for Lobuddy."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def get_exp_for_next_level(self) -> int:
        """Calculate EXP required for next level."""
        exp_table = {
            1: 50,  # Lv1->Lv2
            2: 120,  # Lv2->Lv3
            3: 220,  # Lv3->Lv4
            4: 350,  # Lv4->Lv5
            5: 520,  # Lv5->Lv6
            6: 720,  # Lv6->Lv7
            7: 950,  # Lv7->Lv8
            8: 1220,  # Lv8->Lv9
            9: 1550,  # Lv9->Lv10
        }
        return exp_table.get(self.level, 9999)

    def get_evolution_stage_for_level(self, level: int) -> EvolutionStage:
        """Get evolution stage for given level."""
        if level <= 3:
            return EvolutionStage.STAGE_1
        elif level <= 7:
            return EvolutionStage.STAGE_2
        else:
            return EvolutionStage.STAGE_3

    def add_exp(self, amount: int) -> bool:
        """Add EXP and check if level up occurred.

        Returns:
            True if level up occurred
        """
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

    def start(self):
        """Mark task as started."""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now()

    def complete(self, success: bool):
        """Mark task as completed."""
        self.status = TaskStatus.SUCCESS if success else TaskStatus.FAILED
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


class AppSettings(BaseModel):
    """Application settings stored in database.

    Attributes:
        key: Setting key
        value: Setting value (JSON string)
        updated_at: Last update timestamp
    """

    key: str
    value: str
    updated_at: datetime = Field(default_factory=datetime.now)
