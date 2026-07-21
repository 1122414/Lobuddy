"""Skill registry with built-in Lobuddy abilities."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Static descriptions for workspace skills that lack SKILL.md metadata.
# These are ClawHub-installed skills without frontmatter descriptions.
_WORKSPACE_SKILL_DESCRIPTIONS: dict[str, str] = {
    "agent-browser": (
        "Browser automation CLI for AI agents. Navigate websites, fill forms, "
        "click buttons, take screenshots, and extract data from web pages."
    ),
    "se-browser-automation": (
        "Browser automation tool for web testing and data extraction via CDP."
    ),
    "skill-creator": (
        "Create or update AgentSkills. Use when designing, structuring, or "
        "packaging skills with scripts, references, and assets."
    ),
    "skill-vetter": (
        "Security-first skill vetting for AI agents. Review skills before "
        "installation to check for red flags, permission scope, and suspicious patterns."
    ),
}


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
    """UI facade over SkillManager with built-in fallback skills."""

    def __init__(self, manager=None):
        self._skills: dict[str, SkillDefinition] = {}
        self._manager = manager
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

    def discover_workspace_skills(self, workspace_skills_dir: Path) -> int:
        count = 0
        if not workspace_skills_dir.exists() or not workspace_skills_dir.is_dir():
            return 0
        for skill_dir in workspace_skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_id = skill_dir.name
            if skill_id in self._skills:
                continue
            description = _WORKSPACE_SKILL_DESCRIPTIONS.get(skill_id, "")
            if not description:
                logger.debug("No description available for workspace skill: %s", skill_id)
                continue
            self.register(
                SkillDefinition(
                    id=skill_id,
                    name=skill_id,
                    description=description,
                    icon="\U0001f4e6",
                    category="workspace",
                )
            )
            count += 1
        if count:
            logger.info("Registered %d workspace skills from %s", count, workspace_skills_dir)
        return count

    def register(self, skill: SkillDefinition) -> None:
        """Register a skill."""
        self._skills[skill.id] = skill

    def get(self, skill_id: str) -> Optional[SkillDefinition]:
        return self._skills.get(skill_id)

    def get_all(self) -> list[SkillDefinition]:
        if self._manager:
            managed = self._manager.list_skills(limit=1000)
            for m in managed:
                if m.name not in self._skills:
                    self._skills[m.name] = SkillDefinition(
                        id=m.name,
                        name=m.name,
                        description=m.description,
                        category=m.category,
                        enabled=m.status.value == "active",
                    )
        return list(self._skills.values())

    def get_enabled(self) -> list[SkillDefinition]:
        return [s for s in self.get_all() if s.enabled]

    def get_by_category(self, category: str) -> list[SkillDefinition]:
        return [s for s in self.get_all() if s.category == category]

    def is_available(self, skill_id: str, settings) -> bool:
        skill = self.get(skill_id)
        if not skill or not skill.enabled:
            return False
        if skill.requires_model == "multimodal":
            return bool(settings.llm_multimodal_model)
        return True
