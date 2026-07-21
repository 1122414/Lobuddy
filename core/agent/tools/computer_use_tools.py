"""Nanobot tools for user-authorized, recoverable desktop interaction."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from core.computer_use.coordinator import ComputerUseCoordinator
from core.computer_use.models import ComputerAction

try:
    from nanobot.agent.tools.base import Tool, tool_parameters
    from nanobot.agent.tools.schema import (
        IntegerSchema,
        StringSchema,
        tool_parameters_schema,
    )
except Exception:

    class Tool:
        @property
        def name(self) -> str:
            return ""

        @property
        def description(self) -> str:
            return ""

        @property
        def read_only(self) -> bool:
            return False

        async def execute(self, *args: Any, **kwargs: Any) -> str:
            raise NotImplementedError

    def tool_parameters(schema: dict) -> Any:
        def decorator(cls: type) -> type:
            return cls

        return decorator

    def tool_parameters_schema(**kwargs: Any) -> dict:
        return {}

    def StringSchema(description: str) -> str:
        return ""

    def IntegerSchema(description: str) -> int:
        return 0


def _dump(data: Any) -> str:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return json.dumps(data, ensure_ascii=False)


@tool_parameters(
    tool_parameters_schema(
        goal=StringSchema("Concrete desktop task the user requested"),
        target_app=StringSchema("Expected application or window, if known"),
        allowed_actions=StringSchema(
            "Comma-separated action types: move, click, double_click, scroll, "
            "type_text, press_key, hotkey"
        ),
        max_actions=IntegerSchema("Maximum input actions for this plan"),
        required=["goal"],
    )
)
class ComputerPlanTool(Tool):
    def __init__(self, coordinator: ComputerUseCoordinator) -> None:
        self._coordinator = coordinator

    @property
    def name(self) -> str:
        return "computer_plan"

    @property
    def description(self) -> str:
        return (
            "Create or resume a bounded Computer Use plan. This MUST be the first tool "
            "for any mouse/keyboard task. Then call computer_authorize with the returned "
            "plan_id before observing or acting."
        )

    @property
    def read_only(self) -> bool:
        return False

    async def execute(
        self,
        goal: str = "",
        target_app: str = "",
        allowed_actions: str = "",
        max_actions: int = 0,
        **kwargs: Any,
    ) -> str:
        try:
            plan, resumed = self._coordinator.create_or_resume_plan(
                goal=goal,
                target_app=target_app,
                allowed_actions=allowed_actions,
                max_actions=max_actions or None,
            )
            return _dump(
                {
                    "plan_id": plan.id,
                    "status": plan.status.value,
                    "resumed": resumed,
                    "completed_actions": plan.completed_actions,
                    "max_actions": plan.max_actions,
                    "next": "computer_authorize",
                }
            )
        except Exception as exc:
            return _dump({"error": str(exc), "created": False})


@tool_parameters(
    tool_parameters_schema(
        plan_id=StringSchema("Plan ID returned by computer_plan"),
        required=["plan_id"],
    )
)
class ComputerAuthorizeTool(Tool):
    def __init__(self, coordinator: ComputerUseCoordinator) -> None:
        self._coordinator = coordinator

    @property
    def name(self) -> str:
        return "computer_authorize"

    @property
    def description(self) -> str:
        return (
            "Request explicit user approval for a Computer Use plan. Lobuddy opens an "
            "approval dialog before this tool executes. Never call computer_observe or "
            "computer_act until this returns status=active."
        )

    @property
    def read_only(self) -> bool:
        return False

    async def execute(self, plan_id: str = "", **kwargs: Any) -> str:
        try:
            plan = self._coordinator.plan_for_authorization(plan_id)
            return _dump(
                {
                    "plan_id": plan.id,
                    "status": plan.status.value,
                    "authorized_until": (
                        plan.authorized_until.isoformat()
                        if plan.authorized_until is not None
                        else None
                    ),
                }
            )
        except Exception as exc:
            return _dump({"plan_id": plan_id, "error": str(exc)})


@tool_parameters(
    tool_parameters_schema(
        plan_id=StringSchema("Active, approved Computer Use plan ID"),
        goal=StringSchema("What to locate or understand in the current screen"),
        required=["plan_id"],
    )
)
class ComputerObserveTool(Tool):
    def __init__(self, coordinator: ComputerUseCoordinator) -> None:
        self._coordinator = coordinator

    @property
    def name(self) -> str:
        return "computer_observe"

    @property
    def description(self) -> str:
        return (
            "Capture the current primary screen and receive temporary multimodal analysis. "
            "The screenshot is deleted immediately after analysis. Requires an active "
            "approved plan. Observe before every uncertain action."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, plan_id: str = "", goal: str = "", **kwargs: Any) -> str:
        try:
            return _dump(await self._coordinator.observe(plan_id, goal))
        except Exception as exc:
            return _dump({"plan_id": plan_id, "error": str(exc)})


@tool_parameters(
    tool_parameters_schema(
        plan_id=StringSchema("Active, approved Computer Use plan ID"),
        action=StringSchema(
            "One action: move, click, double_click, scroll, type_text, press_key, hotkey"
        ),
        description=StringSchema(
            "Visible purpose of this one action; explicitly mention send/delete/pay/submit actions"
        ),
        observation_id=StringSchema("Fresh observation_id returned by computer_observe"),
        target_id=StringSchema("Target ID returned by computer_observe, when available"),
        target_label=StringSchema("Visible label or purpose of the selected target"),
        target_role=StringSchema("Visible role such as button, text field, tab, or page"),
        expected_outcome=StringSchema(
            "Concrete visible outcome that must be verified after this action"
        ),
        x=IntegerSchema("Primary-screen x coordinate for pointer actions"),
        y=IntegerSchema("Primary-screen y coordinate for pointer actions"),
        scroll_delta=IntegerSchema("Vertical scroll amount from -20 to 20"),
        text=StringSchema("Text to type; never provide passwords, API keys, or secrets"),
        key=StringSchema("Allowlisted key for press_key"),
        hotkey=StringSchema("Comma-separated allowlisted hotkey, for example ctrl,a"),
        required=[
            "plan_id",
            "action",
            "description",
            "observation_id",
            "target_label",
            "expected_outcome",
        ],
    )
)
class ComputerActTool(Tool):
    def __init__(self, coordinator: ComputerUseCoordinator) -> None:
        self._coordinator = coordinator

    @property
    def name(self) -> str:
        return "computer_act"

    @property
    def description(self) -> str:
        return (
            "Execute exactly ONE bounded mouse or keyboard action inside an approved plan. "
            "Bind it to a fresh observation_id, a visible semantic target, and the expected "
            "visible outcome. Pointer actions must use a returned target_id when targets are "
            "available. The runtime blocks a second action until verification. Never type secrets."
        )

    @property
    def read_only(self) -> bool:
        return False

    async def execute(
        self,
        plan_id: str = "",
        action: str = "",
        description: str = "",
        observation_id: str = "",
        target_id: str = "",
        target_label: str = "",
        target_role: str = "",
        expected_outcome: str = "",
        x: int | None = None,
        y: int | None = None,
        scroll_delta: int = 0,
        text: str = "",
        key: str = "",
        hotkey: str = "",
        **kwargs: Any,
    ) -> str:
        try:
            model = ComputerAction(
                action=action,
                description=description,
                observation_id=observation_id,
                target_id=target_id,
                target_label=target_label,
                target_role=target_role,
                expected_outcome=expected_outcome,
                x=x,
                y=y,
                scroll_delta=scroll_delta,
                text=text,
                key=key,
                hotkey=[item.strip() for item in hotkey.split(",") if item.strip()],
            )
            return _dump(await self._coordinator.execute(plan_id, model))
        except (ValidationError, ValueError, PermissionError, RuntimeError) as exc:
            return _dump({"plan_id": plan_id, "success": False, "error": str(exc)})


@tool_parameters(
    tool_parameters_schema(
        plan_id=StringSchema("Active Computer Use plan ID"),
        expected=StringSchema("Concrete visual outcome expected after the last action"),
        checkpoint_id=StringSchema("Optional checkpoint ID returned by computer_act"),
        required=["plan_id", "expected"],
    )
)
class ComputerVerifyTool(Tool):
    def __init__(self, coordinator: ComputerUseCoordinator) -> None:
        self._coordinator = coordinator

    @property
    def name(self) -> str:
        return "computer_verify"

    @property
    def description(self) -> str:
        return (
            "Capture and visually verify the outcome of the last computer_act. "
            "A false or ambiguous result must trigger re-observation or plan adaptation, "
            "not an unsupported success claim."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        plan_id: str = "",
        expected: str = "",
        checkpoint_id: str = "",
        **kwargs: Any,
    ) -> str:
        try:
            return _dump(
                await self._coordinator.verify(
                    plan_id,
                    expected,
                    checkpoint_id=checkpoint_id,
                )
            )
        except Exception as exc:
            return _dump({"plan_id": plan_id, "verified": False, "error": str(exc)})


@tool_parameters(
    tool_parameters_schema(
        plan_id=StringSchema("Computer Use plan ID"),
        status=StringSchema("completed or failed"),
        summary=StringSchema("Short verified outcome; do not include secrets"),
        required=["plan_id", "status", "summary"],
    )
)
class ComputerFinishTool(Tool):
    def __init__(self, coordinator: ComputerUseCoordinator) -> None:
        self._coordinator = coordinator

    @property
    def name(self) -> str:
        return "computer_finish"

    @property
    def description(self) -> str:
        return (
            "Close a Computer Use plan after verification or an unrecoverable failure. "
            "Use completed only when the visible outcome has been verified."
        )

    @property
    def read_only(self) -> bool:
        return False

    async def execute(
        self,
        plan_id: str = "",
        status: str = "",
        summary: str = "",
        **kwargs: Any,
    ) -> str:
        if status not in {"completed", "failed"}:
            return _dump({"plan_id": plan_id, "error": "status must be completed or failed"})
        try:
            plan = self._coordinator.finish(plan_id, status == "completed")
            return _dump(
                {
                    "plan_id": plan.id,
                    "status": plan.status.value,
                    "summary": summary[:500],
                }
            )
        except Exception as exc:
            return _dump({"plan_id": plan_id, "error": str(exc)})


def build_computer_use_tools(
    coordinator: ComputerUseCoordinator,
) -> list[Tool]:
    return [
        ComputerPlanTool(coordinator),
        ComputerAuthorizeTool(coordinator),
        ComputerObserveTool(coordinator),
        ComputerActTool(coordinator),
        ComputerVerifyTool(coordinator),
        ComputerFinishTool(coordinator),
    ]
