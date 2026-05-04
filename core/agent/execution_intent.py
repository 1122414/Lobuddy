"""5.4 Execution intent router — maps user prompts to structured execution intents."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field


class ExecutionIntent(StrEnum):
    """Valid execution intents for task-level governance."""

    GENERAL_CHAT = "general_chat"
    LOCAL_OPEN_TARGET = "local_open_target"
    LOCAL_FIND_FILE = "local_find_file"
    LOCAL_SYSTEM_ACTION = "local_system_action"
    MEMORY_QUESTION = "memory_question"


class ExecutionRoute(BaseModel):
    """Structured routing result with tool preferences and constraints."""

    intent: ExecutionIntent = ExecutionIntent.GENERAL_CHAT
    target: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_tools: bool = False
    preferred_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    reason: str = ""

    @property
    def is_local_action(self) -> bool:
        """True when this is a local execution intent (open, find, system action)."""
        return self.intent in {
            ExecutionIntent.LOCAL_OPEN_TARGET,
            ExecutionIntent.LOCAL_FIND_FILE,
            ExecutionIntent.LOCAL_SYSTEM_ACTION,
        }


class ExecutionIntentRouter:
    """Keyword-based intent router. No AI call — fast, deterministic, auditable.

    Designed for extensibility: add patterns to _PATTERNS without touching router logic.
    """

    _PATTERNS: ClassVar[list[tuple[str, ExecutionIntent, list[str], list[str], str]]] = [
        (
            r"(打开|启动|运行|帮我开|开一下|帮我打开|帮我启动|帮我运行)"
            r".{0,8}(桌面|快捷方式|应用|游戏|程序|软件|文件)",
            ExecutionIntent.LOCAL_OPEN_TARGET,
            ["local_app_resolve", "local_open"],
            ["exec"],
            "User wants to open a desktop application or shortcut",
        ),
        (
            r"(?:^|\s)(打开|启动|运行)\S",
            ExecutionIntent.LOCAL_OPEN_TARGET,
            ["local_app_resolve", "local_open"],
            ["exec"],
            "User wants to open an application",
        ),
        (
            r"(在哪|找一下|搜索文件|帮我找|查找|找找|寻找|有没有.*文件)"
            r".{0,30}(文件|文档|图片|照片|视频|在哪里)",
            ExecutionIntent.LOCAL_FIND_FILE,
            [],
            ["exec"],
            "User wants to find a file on the local machine",
        ),
        (
            r"(?:^|\s)(找一下|帮我找|搜索)\S",
            ExecutionIntent.LOCAL_FIND_FILE,
            [],
            ["exec"],
            "User wants to search for something locally",
        ),
        (
            r"(在哪|找一下|搜索文件|帮我找|查找|找找|寻找|有没有.*文件)"
            r".{0,8}(文件|文档|图片|照片|视频)",
            ExecutionIntent.LOCAL_FIND_FILE,
            [],
            ["exec"],
            "User wants to find a file on the local machine",
        ),
        (
            r"(关机|重启|注销|锁屏|睡眠|休眠|音量|亮度|蓝牙|WiFi|wifi|网络)",
            ExecutionIntent.LOCAL_SYSTEM_ACTION,
            [],
            [],
            "User wants to perform a system-level action",
        ),
        (
            r"(我喜欢|我是谁|我之前说过|记得我吗|我的名字|我的偏好|我.*喜欢|我.*不喜欢)",
            ExecutionIntent.MEMORY_QUESTION,
            [],
            [],
            "User is asking about stored memory or identity",
        ),
    ]

    # Minimum confidence threshold for enabling execution governance.
    # If no pattern matches or confidence is below this, route is GENERAL_CHAT.
    MIN_GOVERNANCE_CONFIDENCE: float = 0.75

    def route(self, prompt: str) -> ExecutionRoute:
        """Route a user prompt to the most likely execution intent.

        Matches against keyword patterns and extracts a target string
        when the intent is LOCAL_OPEN_TARGET or LOCAL_FIND_FILE.
        """
        if not prompt or not prompt.strip():
            return ExecutionRoute(
                intent=ExecutionIntent.GENERAL_CHAT,
                confidence=0.0,
                reason="Empty prompt",
            )

        best: ExecutionRoute | None = None

        for pattern, intent, preferred_tools, forbidden_tools, reason in self._PATTERNS:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if not match:
                continue

            target = self._extract_target(prompt, match)
            confidence = self._compute_confidence(prompt, match)
            route = ExecutionRoute(
                intent=intent,
                target=target,
                confidence=confidence,
                requires_tools=len(preferred_tools) > 0,
                preferred_tools=list(preferred_tools),
                forbidden_tools=list(forbidden_tools),
                reason=reason,
            )

            if best is None or confidence > best.confidence:
                best = route

        if best is None:
            return ExecutionRoute(
                intent=ExecutionIntent.GENERAL_CHAT,
                confidence=0.0,
                reason="No execution pattern matched",
            )

        return best

    def should_govern(self, route: ExecutionRoute) -> bool:
        """True when governance should be enforced for this route."""
        return (
            route.is_local_action
            and route.confidence >= self.MIN_GOVERNANCE_CONFIDENCE
            and route.requires_tools
        )

    @staticmethod
    def _extract_target(prompt: str, match: re.Match[str]) -> str:
        """Extract the target name from the prompt and match context."""
        quoted = re.search(r"[「『\"'](.+?)[」』\"']", prompt)
        if quoted:
            return quoted.group(1)

        after = prompt[match.end():].strip()
        if after:
            cleaned = re.sub(r"[。！？，、\s]+$", "", after)
            return cleaned[:100]

        return ""

    @staticmethod
    def _compute_confidence(prompt: str, match: re.Match[str]) -> float:
        """Compute a confidence score based on match coverage in the prompt."""
        match_len = match.end() - match.start()
        prompt_len = max(len(prompt.strip()), 1)
        base = min(0.85, match_len / prompt_len + 0.5)

        # Boost if explicit desktop/start-menu context
        if re.search(r"桌面|开始菜单|桌面快捷方式", prompt):
            base = min(0.95, base + 0.15)

        # Penalize if mixed with general chat signals
        if re.search(r"讲个笑话|天气|新闻|帮我写|翻译|解释", prompt):
            base = min(0.6, base - 0.3)

        return round(base, 2)
