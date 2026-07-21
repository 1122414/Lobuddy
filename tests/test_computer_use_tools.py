"""Contract tests for nanobot Computer Use tools."""

import asyncio
import json
from types import SimpleNamespace

from core.agent.tools.computer_use_tools import build_computer_use_tools
from core.computer_use.models import (
    ComputerActionResult,
    ComputerObservation,
    ComputerPlanStatus,
    ComputerTarget,
    ComputerVerification,
    utc_now,
)


class _Coordinator:
    def __init__(self):
        self.calls = []
        self.plan = SimpleNamespace(
            id="plan-1",
            status=ComputerPlanStatus.PENDING_APPROVAL,
            authorized_until=None,
            completed_actions=0,
            max_actions=5,
        )

    def create_or_resume_plan(self, **kwargs):
        self.calls.append(("plan", kwargs))
        return self.plan, False

    def plan_for_authorization(self, plan_id):
        self.calls.append(("authorize", plan_id))
        self.plan.status = ComputerPlanStatus.ACTIVE
        self.plan.authorized_until = utc_now()
        return self.plan

    async def observe(self, plan_id, goal):
        self.calls.append(("observe", plan_id, goal))
        return ComputerObservation(
            observation_id="observation-1",
            plan_id=plan_id,
            width=1920,
            height=1080,
            analysis="Save button at (100, 200)",
            targets=[
                ComputerTarget(
                    id="target-save",
                    label="保存",
                    role="button",
                    x=80,
                    y=180,
                    width=80,
                    height=40,
                    confidence=0.95,
                )
            ],
        )

    async def execute(self, plan_id, action):
        self.calls.append(("act", plan_id, action))
        return ComputerActionResult(
            success=True,
            plan_id=plan_id,
            checkpoint_id="checkpoint-1",
            step_index=1,
            message="executed",
        )

    async def verify(self, plan_id, expected, checkpoint_id=""):
        self.calls.append(("verify", plan_id, expected, checkpoint_id))
        return ComputerVerification(
            plan_id=plan_id,
            checkpoint_id=checkpoint_id,
            verified=True,
            summary="Save confirmation is visible",
        )

    def finish(self, plan_id, success):
        self.calls.append(("finish", plan_id, success))
        self.plan.status = (
            ComputerPlanStatus.COMPLETED if success else ComputerPlanStatus.FAILED
        )
        return self.plan


class TestComputerUseTools:
    def test_toolset_exposes_full_recoverable_sequence(self):
        tools = build_computer_use_tools(_Coordinator())

        assert [tool.name for tool in tools] == [
            "computer_plan",
            "computer_authorize",
            "computer_observe",
            "computer_act",
            "computer_verify",
            "computer_finish",
        ]
        assert len({tool.name for tool in tools}) == 6
        assert all(tool.parameters for tool in tools)

    def test_plan_observe_act_verify_finish_contract(self):
        coordinator = _Coordinator()
        tools = {tool.name: tool for tool in build_computer_use_tools(coordinator)}

        plan = json.loads(
            asyncio.run(
                tools["computer_plan"].execute(
                    goal="点击保存",
                    target_app="设置",
                    allowed_actions="click",
                    max_actions=5,
                )
            )
        )
        authorization = json.loads(
            asyncio.run(
                tools["computer_authorize"].execute(plan_id=plan["plan_id"])
            )
        )
        observation = json.loads(
            asyncio.run(
                tools["computer_observe"].execute(
                    plan_id=plan["plan_id"],
                    goal="定位保存按钮",
                )
            )
        )
        action = json.loads(
            asyncio.run(
                tools["computer_act"].execute(
                    plan_id=plan["plan_id"],
                    action="click",
                    description="点击保存",
                    observation_id=observation["observation_id"],
                    target_id=observation["targets"][0]["id"],
                    target_label=observation["targets"][0]["label"],
                    target_role=observation["targets"][0]["role"],
                    expected_outcome="保存成功提示可见",
                    x=100,
                    y=200,
                )
            )
        )
        verification = json.loads(
            asyncio.run(
                tools["computer_verify"].execute(
                    plan_id=plan["plan_id"],
                    expected="保存成功提示可见",
                    checkpoint_id=action["checkpoint_id"],
                )
            )
        )
        finished = json.loads(
            asyncio.run(
                tools["computer_finish"].execute(
                    plan_id=plan["plan_id"],
                    status="completed",
                    summary="已验证保存成功",
                )
            )
        )

        assert authorization["status"] == "active"
        assert observation["analysis"].startswith("Save button")
        assert action["success"] is True
        assert verification["verified"] is True
        assert finished["status"] == "completed"
