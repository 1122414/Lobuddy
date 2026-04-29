"""Skill registry with built-in Lobuddy abilities."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SkillDefinition:
    """Definition of a single skill."""

    id: str
    name: str
    description: str
    icon: str = "\U0001f527"
    category: str = "general"
    examples: list[str] = field(default_factory=list)
    enabled: bool = True
    requires_model: Optional[str] = None  # e.g., "multimodal"


class SkillRegistry:
    """Registry of available skills."""

    def __init__(self):
        self._skills: dict[str, SkillDefinition] = {}
        self._register_builtin_skills()

    def _register_builtin_skills(self) -> None:
        """Register built-in Lobuddy skills."""
        self.register(
            SkillDefinition(
                id="chat",
                name="聊天对话",
                description="与AI进行自然语言对话，获取信息、建议或闲聊",
                icon="\U0001f4ac",
                category="core",
                examples=[
                    "今天天气怎么样？",
                    "给我讲个有趣的故事",
                    "帮我解释一下量子计算",
                ],
            )
        )

        self.register(
            SkillDefinition(
                id="code",
                name="代码助手",
                description="帮助你编写、审查和理解代码",
                icon="\U0001f4bb",
                category="core",
                examples=[
                    "帮我写一个Python快速排序",
                    "这段代码有什么bug？",
                    "如何优化这个函数的性能？",
                ],
            )
        )

        self.register(
            SkillDefinition(
                id="image",
                name="图片分析",
                description="上传图片，AI会分析图片内容并回答问题",
                icon="\U0001f5bc\ufe0f",
                category="multimodal",
                examples=[
                    "这张图片里有什么？",
                    "帮我识别图中的文字",
                    "描述一下这张照片的场景",
                ],
                requires_model="multimodal",
            )
        )

        self.register(
            SkillDefinition(
                id="task",
                name="任务执行",
                description="让AI帮你执行文件操作、搜索等任务",
                icon="⚡",
                category="core",
                examples=[
                    "帮我搜索项目中的所有TODO",
                    "整理一下这个文件夹",
                    "检查一下代码的语法错误",
                ],
            )
        )

        self.register(
            SkillDefinition(
                id="pet",
                name="宠物互动",
                description="与桌面宠物互动，查看状态和成长",
                icon="\U0001f431",
                category="companion",
                examples=[
                    "你现在几级了？",
                    "看看你的属性",
                    "今天心情怎么样？",
                ],
            )
        )

        self.register(
            SkillDefinition(
                id="focus",
                name="专注模式",
                description="开始一个番茄钟专注时段",
                icon="\U0001f3af",
                category="productivity",
                examples=[
                    "开始专注25分钟",
                    "帮我设置一个番茄钟",
                    "我要专注工作了",
                ],
            )
        )

    def register(self, skill: SkillDefinition) -> None:
        """Register a skill."""
        self._skills[skill.id] = skill

    def get(self, skill_id: str) -> Optional[SkillDefinition]:
        """Get a skill by ID."""
        return self._skills.get(skill_id)

    def get_all(self) -> list[SkillDefinition]:
        """Get all registered skills."""
        return list(self._skills.values())

    def get_enabled(self) -> list[SkillDefinition]:
        """Get all enabled skills."""
        return [s for s in self._skills.values() if s.enabled]

    def get_by_category(self, category: str) -> list[SkillDefinition]:
        """Get skills by category."""
        return [s for s in self._skills.values() if s.category == category]

    def is_available(self, skill_id: str, settings) -> bool:
        """Check if a skill is available given current settings."""
        skill = self.get(skill_id)
        if not skill or not skill.enabled:
            return False

        # Check model requirements
        if skill.requires_model == "multimodal":
            return bool(settings.llm_multimodal_model)

        return True
