"""Personality system for pet evolution."""

from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field


class PersonalityDimension(str, Enum):
    """Personality trait dimensions."""

    FRIENDLINESS = "friendliness"
    CURIOSITY = "curiosity"
    TECHNICAL_SKILL = "technical_skill"
    CREATIVITY = "creativity"
    DILIGENCE = "diligence"


class PetPersonality(BaseModel):
    """Personality traits tracked across interactions.

    Attributes:
        friendliness: Warmth and social engagement (0-100)
        curiosity: Interest in new tasks/topics (0-100)
        technical_skill: Coding/technical capability (0-100)
        creativity: Problem-solving creativity (0-100)
        diligence: Task completion persistence (0-100)
        interaction_counts: Track interactions by type
    """

    friendliness: float = Field(default=50.0, ge=0.0, le=100.0)
    curiosity: float = Field(default=50.0, ge=0.0, le=100.0)
    technical_skill: float = Field(default=50.0, ge=0.0, le=100.0)
    creativity: float = Field(default=50.0, ge=0.0, le=100.0)
    diligence: float = Field(default=50.0, ge=0.0, le=100.0)

    interaction_counts: Dict[str, int] = Field(default_factory=dict)

    def adjust_trait(self, dimension: PersonalityDimension, delta: float, reason: str):
        """Adjust a personality trait.

        Args:
            dimension: Which trait to adjust
            delta: Amount to change (positive or negative)
            reason: Why the adjustment happened
        """
        current = getattr(self, dimension.value)
        new_value = max(0.0, min(100.0, current + delta))
        setattr(self, dimension.value, new_value)

        key = f"{dimension.value}:{reason}"
        self.interaction_counts[key] = self.interaction_counts.get(key, 0) + 1

    def get_dominant_traits(self, n: int = 2) -> List[tuple]:
        """Get top N dominant personality traits.

        Args:
            n: Number of traits to return

        Returns:
            List of (dimension, value) tuples sorted by value desc
        """
        traits = [
            (PersonalityDimension.FRIENDLINESS, self.friendliness),
            (PersonalityDimension.CURIOSITY, self.curiosity),
            (PersonalityDimension.TECHNICAL_SKILL, self.technical_skill),
            (PersonalityDimension.CREATIVITY, self.creativity),
            (PersonalityDimension.DILIGENCE, self.diligence),
        ]
        return sorted(traits, key=lambda x: x[1], reverse=True)[:n]
