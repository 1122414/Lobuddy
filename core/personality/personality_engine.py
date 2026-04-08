"""Personality engine - analyzes interactions and evolves personality."""

import re
from typing import Dict

from core.models.personality import PetPersonality, PersonalityDimension
from core.models.pet import TaskDifficulty, TaskRecord


class PersonalityEngine:
    """Analyzes tasks/messages and updates pet personality."""

    KEYWORD_PATTERNS = {
        PersonalityDimension.TECHNICAL_SKILL: [
            r"\b(code|program|debug|error|function|class|import|api)\b",
            r"\b(python|javascript|java|rust|go|sql|git|github)\b",
            r"\b(algorithm|database|server|backend|frontend|framework)\b",
            r"\b(bug|fix|refactor|deploy|build|compile)\b",
        ],
        PersonalityDimension.CURIOSITY: [
            r"\b(how|why|what|explain|learn|understand|teach)\b",
            r"\b(different|alternative|compare|vs|versus|difference)\b",
            r"\b(explore|discover|research|investigate|curious)\b",
        ],
        PersonalityDimension.CREATIVITY: [
            r"\b(create|design|build|make|generate|imagine)\b",
            r"\b(story|art|music|game|app|project|idea)\b",
            r"\b(improve|enhance|optimize|innovate|creative)\b",
        ],
    }

    DIFFICULTY_MULTIPLIER = {
        TaskDifficulty.SIMPLE: 0.5,
        TaskDifficulty.MEDIUM: 1.0,
        TaskDifficulty.COMPLEX: 1.5,
    }

    @classmethod
    def analyze_task(cls, task: TaskRecord, personality: PetPersonality) -> Dict[str, float]:
        """Analyze a task and return personality adjustments.

        Args:
            task: The task record to analyze
            personality: Current pet personality

        Returns:
            Dict mapping trait names to adjustment deltas
        """
        adjustments = {}
        text = task.input_text.lower()

        # Check each dimension for keyword matches
        for dimension, patterns in cls.KEYWORD_PATTERNS.items():
            score = sum(1 for p in patterns if re.search(p, text, re.I))
            if score > 0:
                difficulty_multiplier = cls.DIFFICULTY_MULTIPLIER.get(task.difficulty, 1.0)
                delta = min(2.0, score * 0.5 * difficulty_multiplier)
                adjustments[dimension.value] = delta

        # Diligence increases with task completion
        adjustments[PersonalityDimension.DILIGENCE.value] = 0.3

        return adjustments

    @classmethod
    def apply_adjustments(cls, personality: PetPersonality, adjustments: Dict[str, float]):
        """Apply personality adjustments.

        Args:
            personality: PetPersonality to modify
            adjustments: Dict of trait -> delta values
        """
        for trait, delta in adjustments.items():
            dimension = PersonalityDimension(trait)
            personality.adjust_trait(dimension, delta, "task_analysis")
