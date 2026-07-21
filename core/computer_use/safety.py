"""Safety validation for bounded computer-use plans and actions."""

from __future__ import annotations

import re

from core.computer_use.models import ComputerAction, ComputerActionType, ComputerPlan

_ALLOWED_KEYS = {
    "backspace",
    "delete",
    "down",
    "end",
    "enter",
    "esc",
    "home",
    "left",
    "page_down",
    "page_up",
    "right",
    "space",
    "tab",
    "up",
}

_ALLOWED_HOTKEYS = {
    ("alt", "tab"),
    ("ctrl", "a"),
    ("ctrl", "c"),
    ("ctrl", "f"),
    ("ctrl", "l"),
    ("ctrl", "s"),
    ("ctrl", "tab"),
    ("ctrl", "v"),
    ("ctrl", "w"),
    ("shift", "tab"),
}

_HIGH_IMPACT_PATTERN = re.compile(
    r"删除|清空|卸载|支付|付款|购买|下单|转账|发送|提交|发布|确认|授权|登录|"
    r"delete|remove|uninstall|pay|purchase|buy|transfer|send|submit|publish|"
    r"confirm|authorize|log\s?in",
    re.IGNORECASE,
)

_SENSITIVE_INTENT_PATTERN = re.compile(
    r"密码|口令|验证码|支付信息|银行卡|api[\s_-]?key|access[\s_-]?token|"
    r"password|passcode|one.time.code|credit.card|secret",
    re.IGNORECASE,
)


class ComputerUseSafety:
    """One validation Interface shared by HITL and desktop Adapter implementations."""

    @staticmethod
    def parse_allowed_actions(raw: str) -> list[ComputerActionType]:
        requested = [item.strip().lower() for item in raw.split(",") if item.strip()]
        if not requested:
            return [
                ComputerActionType.MOVE,
                ComputerActionType.CLICK,
                ComputerActionType.SCROLL,
                ComputerActionType.TYPE_TEXT,
                ComputerActionType.PRESS_KEY,
                ComputerActionType.HOTKEY,
            ]
        actions: list[ComputerActionType] = []
        for item in requested:
            try:
                action = ComputerActionType(item)
            except ValueError as exc:
                raise ValueError(f"Unsupported computer action: {item}") from exc
            if action not in actions:
                actions.append(action)
        return actions

    @staticmethod
    def validate_goal(goal: str) -> None:
        if _SENSITIVE_INTENT_PATTERN.search(goal):
            raise ValueError(
                "Computer Use does not handle passwords, verification codes, API keys, "
                "payment data, or other secrets"
            )

    @staticmethod
    def validate_action(
        action: ComputerAction,
        plan: ComputerPlan,
        screen_size: tuple[int, int],
    ) -> None:
        if action.action not in plan.allowed_actions:
            raise ValueError(f"Action '{action.action.value}' is outside the approved plan")

        width, height = screen_size
        if action.x is not None and not 0 <= action.x < width:
            raise ValueError(f"x coordinate must be within 0..{width - 1}")
        if action.y is not None and not 0 <= action.y < height:
            raise ValueError(f"y coordinate must be within 0..{height - 1}")

        key = action.key.lower().strip()
        if action.action == ComputerActionType.PRESS_KEY and key not in _ALLOWED_KEYS:
            raise ValueError(f"Key '{key}' is not in the computer-use allowlist")

        if action.action == ComputerActionType.HOTKEY:
            normalized = tuple(item.lower().strip() for item in action.hotkey)
            if normalized not in _ALLOWED_HOTKEYS:
                raise ValueError(f"Hotkey '{'+'.join(normalized)}' is not allowed")
        if (
            action.action == ComputerActionType.TYPE_TEXT
            and _SENSITIVE_INTENT_PATTERN.search(action.description)
        ):
            raise ValueError("Computer Use will not type credentials or other secrets")

    @staticmethod
    def requires_individual_confirmation(action: ComputerAction) -> bool:
        return bool(_HIGH_IMPACT_PATTERN.search(action.description))

    @staticmethod
    def authorization_preview(plan: ComputerPlan) -> str:
        actions = ", ".join(action.value for action in plan.allowed_actions)
        target = plan.target_app or "当前桌面"
        return (
            f"任务：{plan.goal}\n"
            f"目标：{target}\n"
            f"允许动作：{actions}\n"
            f"最多执行：{plan.max_actions} 个动作\n"
            "每个动作都必须绑定新鲜观察、可见目标和预期结果，并在继续前验证。\n"
            "屏幕截图与原生控件树只用于即时分析，不会保存到任务记录。"
        )
