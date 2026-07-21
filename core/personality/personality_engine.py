"""Personality engine - analyzes interactions and evolves personality."""

import re
from typing import Dict

from core.models.personality import PetPersonality, PersonalityDimension
from core.models.pet import TaskDifficulty, TaskRecord


class PersonalityEngine:
    """Analyzes tasks/messages and updates pet personality."""

    KEYWORD_PATTERNS = {
        PersonalityDimension.FRIENDLINESS: [
            r"\b(chat|talk|support|encourage|together|thank|companion)\b",
            r"(陪我|聊聊|沟通|安慰|鼓励|一起|谢谢|感谢|交流|陪伴)",
        ],
        PersonalityDimension.TECHNICAL_SKILL: [
            r"\b(code|program|debug|error|function|class|import|api)\b",
            r"\b(python|javascript|java|rust|go|sql|git|github)\b",
            r"\b(algorithm|database|server|backend|frontend|framework)\b",
            r"\b(bug|fix|refactor|deploy|build|compile)\b",
            r"(代码|编程|调试|错误|函数|接口|算法|数据库|服务端|前端|框架|缺陷|修复|重构|部署|构建|编译)",
        ],
        PersonalityDimension.CURIOSITY: [
            r"\b(how|why|what|explain|learn|understand|teach)\b",
            r"\b(different|alternative|compare|vs|versus|difference)\b",
            r"\b(explore|discover|research|investigate|curious)\b",
            r"(怎么|为什么|什么|解释|学习|理解|教我|比较|对比|区别|探索|研究|调查)",
        ],
        PersonalityDimension.CREATIVITY: [
            r"\b(create|design|build|make|generate|imagine)\b",
            r"\b(story|art|music|game|app|project|idea)\b",
            r"\b(improve|enhance|optimize|innovate|creative)\b",
            r"(创建|设计|制作|生成|想象|故事|艺术|音乐|游戏|应用|项目|想法|改进|增强|优化|创新|创意)",
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
