"""Stable task difficulty and EXP policy shared by both desktop engines."""

from core.models.pet import TaskDifficulty


def determine_task_difficulty(input_text: str) -> tuple[TaskDifficulty, int]:
    """Auto-determine task difficulty based on input characteristics.

    Returns:
        Tuple of (difficulty, reward_exp)
    """
    text = input_text.strip().lower()
    length = len(text)

    complex_keywords = [
        "代码",
        "code",
        "程序",
        "program",
        "脚本",
        "script",
        "分析",
        "analyze",
        "分析",
        "analysis",
        "优化",
        "optimize",
        "重构",
        "refactor",
        "设计",
        "design",
        "架构",
        "architecture",
        "实现",
        "implement",
        "开发",
        "develop",
        "比较",
        "compare",
        "对比",
        "versus",
        "vs",
        "解释",
        "explain",
        "详细",
        "detail",
    ]
    medium_keywords = [
        "搜索",
        "search",
        "查找",
        "find",
        "总结",
        "summarize",
        "概括",
        "summary",
        "转换",
        "convert",
        "翻译",
        "translate",
        "修复",
        "fix",
        "调试",
        "debug",
        "创建",
        "create",
        "生成",
        "generate",
        "写",
        "write",
        "撰写",
        "compose",
    ]

    complex_score = sum(1 for kw in complex_keywords if kw in text)
    medium_score = sum(1 for kw in medium_keywords if kw in text)

    if length > 200 or complex_score >= 2 or (complex_score >= 1 and length > 100):
        return TaskDifficulty.COMPLEX, 30
    elif length > 80 or medium_score >= 2 or complex_score == 1 or medium_score >= 1:
        return TaskDifficulty.MEDIUM, 15
    else:
        return TaskDifficulty.SIMPLE, 5
