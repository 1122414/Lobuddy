"""Side-effect-free behavior simulation for skill candidate tool plans."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Protocol

from core.skills.skill_schema import (
    BehaviorSimulationStatus,
    CandidateSource,
    SimulatedToolOutcome,
    SkillBehaviorEvidence,
    SkillBehaviorSimulation,
    SkillCandidate,
    SkillPermissionProfile,
    SkillToolSimulationReceipt,
)


_WORKFLOW_SECTION = re.compile(r"(?ims)^##\s+Workflow\s*$\s*(.*?)(?=^##\s+|\Z)")
_WORKFLOW_STEP = re.compile(r"(?m)^\s*(\d+)[.)]\s+(.+?)\s*$")
_CODE_REFERENCE = re.compile(r"`([a-z][a-z0-9_-]{1,79})`")
_VERIFY_MARKERS = (
    "verify",
    "validate",
    "check the result",
    "confirm the result",
    "验证",
    "校验",
    "核对",
    "确认结果",
)
_REFUSAL_MARKERS = (
    "stop",
    "ask the user",
    "confirm",
    "approval",
    "停止",
    "询问用户",
    "请求确认",
    "批准",
)


class SkillToolSimulationAdapter(Protocol):
    """Classify and synthesize receipts for one declared tool."""

    def supports(self, tool_name: str) -> bool:
        ...

    def capability(self, tool_name: str) -> tuple[str, str, bool]:
        """Return capability label, risk level, and confirmation requirement."""
        ...

    def simulate(
        self,
        tool_name: str,
        *,
        scenario: str,
        step_index: int,
    ) -> SkillToolSimulationReceipt:
        ...


class GovernedSkillToolSimulationAdapter:
    """Synthetic Adapter for known tools; it never invokes their implementations."""

    READ_TOOLS = {
        "read_file",
        "list_dir",
        "list_directory",
        "search_files",
        "grep",
        "find",
    }
    WRITE_TOOLS = {
        "write_file",
        "edit_file",
        "apply_patch",
        "create_file",
    }
    NETWORK_TOOLS = {
        "web_search",
        "web_fetch",
        "browser",
        "browser_open",
    }
    HIGH_RISK_TOOLS = {
        "computer_act",
        "computer_authorize",
        "exec",
        "shell",
        "run_command",
        "powershell",
    }

    @classmethod
    def known_tools(cls) -> set[str]:
        return cls.READ_TOOLS | cls.WRITE_TOOLS | cls.NETWORK_TOOLS | cls.HIGH_RISK_TOOLS

    def supports(self, tool_name: str) -> bool:
        return tool_name.lower() in self.known_tools()

    def capability(self, tool_name: str) -> tuple[str, str, bool]:
        normalized = tool_name.lower()
        if normalized in self.HIGH_RISK_TOOLS:
            return "系统命令或电脑控制", "high", True
        if normalized in self.WRITE_TOOLS:
            return "修改工作区", "medium", True
        if normalized in self.NETWORK_TOOLS:
            return "访问网络", "medium", True
        return "读取工作区", "low", False

    def simulate(
        self,
        tool_name: str,
        *,
        scenario: str,
        step_index: int,
    ) -> SkillToolSimulationReceipt:
        capability, risk_level, requires_confirmation = self.capability(tool_name)
        refused = risk_level == "high" or scenario == "synthetic_refusal"
        return SkillToolSimulationReceipt(
            scenario=scenario,
            step_index=step_index,
            tool_name=tool_name,
            outcome=(SimulatedToolOutcome.REFUSED if refused else SimulatedToolOutcome.PERMITTED),
            capability=capability,
            requires_confirmation=requires_confirmation,
            detail=("合成拒绝回执；未调用真实工具" if refused else "合成允许回执；未调用真实工具"),
        )


class DenyUnknownSkillToolSimulationAdapter:
    """Fail-closed Adapter for tools outside the governed simulation catalog."""

    @staticmethod
    def supports(_tool_name: str) -> bool:
        return True

    @staticmethod
    def capability(_tool_name: str) -> tuple[str, str, bool]:
        return "未分类能力", "high", True

    def simulate(
        self,
        tool_name: str,
        *,
        scenario: str,
        step_index: int,
    ) -> SkillToolSimulationReceipt:
        return SkillToolSimulationReceipt(
            scenario=scenario,
            step_index=step_index,
            tool_name=tool_name,
            outcome=SimulatedToolOutcome.REFUSED,
            capability="未分类能力",
            requires_confirmation=True,
            detail="未知工具合成拒绝；未调用真实工具",
        )


class SkillBehaviorEvaluator:
    """Produce permission and behavior evidence through one compact interface."""

    def __init__(
        self,
        adapters: tuple[SkillToolSimulationAdapter, ...] | None = None,
    ) -> None:
        provided = adapters or (GovernedSkillToolSimulationAdapter(),)
        if any(isinstance(adapter, DenyUnknownSkillToolSimulationAdapter) for adapter in provided):
            self._adapters = provided
        else:
            self._adapters = (
                *provided,
                DenyUnknownSkillToolSimulationAdapter(),
            )

    def evaluate(self, candidate: SkillCandidate) -> SkillBehaviorEvidence:
        tools = self._permission_tools(candidate)
        permissions = self._permission_profile(tools)
        workflow_steps = self._workflow_steps(candidate.proposed_content)
        step_tools = self._step_tools(workflow_steps, tools)
        simulated_tools = list(dict.fromkeys(tool for _index, tool in step_tools))
        missing_tools = [tool for tool in tools if tool not in simulated_tools]
        undeclared_tools = self._undeclared_tools(
            workflow_steps,
            tools,
        )
        last_tool_step = max(
            (index for index, _tool in step_tools),
            default=0,
        )
        has_terminal_verification = self._has_terminal_verification(
            workflow_steps,
            last_tool_step,
        )
        has_side_effect_tool = any(self._contract(tool)[1] in {"medium", "high"} for tool in tools)
        has_refusal_policy = self._has_refusal_policy(candidate.proposed_content)

        receipts: list[SkillToolSimulationReceipt] = []
        for step_index, tool in step_tools:
            receipts.append(
                self._adapter(tool).simulate(
                    tool,
                    scenario="declared_path",
                    step_index=step_index,
                )
            )
        refusal_tool = next(
            (
                (step_index, tool)
                for step_index, tool in step_tools
                if self._contract(tool)[1] in {"medium", "high"}
            ),
            None,
        )
        if refusal_tool is not None:
            step_index, tool = refusal_tool
            receipts.append(
                self._adapter(tool).simulate(
                    tool,
                    scenario="synthetic_refusal",
                    step_index=step_index,
                )
            )

        declared_refusals = [
            receipt.tool_name
            for receipt in receipts
            if (
                receipt.scenario == "declared_path"
                and receipt.outcome == SimulatedToolOutcome.REFUSED
            )
        ]
        all_refused_tools = list(
            dict.fromkeys(
                receipt.tool_name
                for receipt in receipts
                if receipt.outcome == SimulatedToolOutcome.REFUSED
            )
        )
        failures: list[str] = []
        if missing_tools:
            failures.append("声明工具未出现在有序流程：" + "、".join(missing_tools))
        if undeclared_tools:
            failures.append("流程引用未声明工具：" + "、".join(undeclared_tools))
        if declared_refusals:
            failures.append("声明路径包含被拒绝工具：" + "、".join(declared_refusals))
        if tools and not has_terminal_verification:
            failures.append("工具步骤之后缺少终止验证")
        if (
            candidate.source_kind == CandidateSource.SUCCESSFUL_TASK
            and has_side_effect_tool
            and not has_refusal_policy
        ):
            failures.append("自动进化流程缺少拒绝或人工确认策略")

        status = BehaviorSimulationStatus.FAILED if failures else BehaviorSimulationStatus.PASSED
        scenario_count = 1 + int(refusal_tool is not None)
        simulation = SkillBehaviorSimulation(
            status=status,
            scenario_count=scenario_count,
            workflow_step_count=len(workflow_steps),
            declared_tools=tools,
            simulated_tools=simulated_tools,
            refused_tools=all_refused_tools,
            missing_tools=missing_tools,
            undeclared_tools=undeclared_tools,
            has_terminal_verification=has_terminal_verification,
            has_refusal_policy=has_refusal_policy,
            summary=(f"通过 {scenario_count} 个合成场景；真实副作用 0" if not failures else "；".join(failures)),
            receipts=receipts,
        )
        simulation.fingerprint = self._fingerprint(simulation)
        return SkillBehaviorEvidence(
            permissions=permissions,
            simulation=simulation,
        )

    def _permission_tools(self, candidate: SkillCandidate) -> list[str]:
        raw_tools = candidate.evidence.get("tools", [])
        tools = (
            list(
                dict.fromkeys(str(tool).strip().lower() for tool in raw_tools if str(tool).strip())
            )
            if isinstance(raw_tools, (list, tuple, set))
            else []
        )
        lower_content = candidate.proposed_content.lower()
        for tool in GovernedSkillToolSimulationAdapter.known_tools():
            if tool in lower_content and tool not in tools:
                tools.append(tool)
        for reference in _CODE_REFERENCE.findall(self._workflow_body(candidate.proposed_content)):
            if "_" in reference and reference not in tools:
                tools.append(reference)
        return tools

    def _permission_profile(self, tools: list[str]) -> SkillPermissionProfile:
        capabilities: list[str] = []
        unknown: list[str] = []
        risk_level = "low"
        for tool in tools:
            capability, tool_risk, _confirmation = self._contract(tool)
            if capability not in capabilities:
                capabilities.append(capability)
            if isinstance(
                self._adapter(tool),
                DenyUnknownSkillToolSimulationAdapter,
            ):
                unknown.append(tool)
            if tool_risk == "high":
                risk_level = "high"
            elif tool_risk == "medium" and risk_level == "low":
                risk_level = "medium"
        if not capabilities:
            capabilities.append("仅使用对话推理")
        return SkillPermissionProfile(
            tools=tools,
            capabilities=capabilities,
            risk_level=risk_level,
            unknown_tools=unknown,
            requires_confirmation=risk_level in {"medium", "high"},
        )

    def _adapter(self, tool_name: str) -> SkillToolSimulationAdapter:
        return next(adapter for adapter in self._adapters if adapter.supports(tool_name))

    def _contract(self, tool_name: str) -> tuple[str, str, bool]:
        return self._adapter(tool_name).capability(tool_name)

    @staticmethod
    def _workflow_body(content: str) -> str:
        matched = _WORKFLOW_SECTION.search(content)
        return matched.group(1) if matched else ""

    @classmethod
    def _workflow_steps(cls, content: str) -> list[tuple[int, str]]:
        return [
            (int(index), text.strip())
            for index, text in _WORKFLOW_STEP.findall(cls._workflow_body(content))
        ]

    @staticmethod
    def _step_tools(
        workflow_steps: list[tuple[int, str]],
        tools: list[str],
    ) -> list[tuple[int, str]]:
        found: list[tuple[int, str]] = []
        for index, text in workflow_steps:
            lower = text.lower()
            for tool in tools:
                if re.search(
                    rf"(?<![a-z0-9_-]){re.escape(tool.lower())}(?![a-z0-9_-])",
                    lower,
                ):
                    found.append((index, tool))
        return found

    @staticmethod
    def _undeclared_tools(
        workflow_steps: list[tuple[int, str]],
        tools: list[str],
    ) -> list[str]:
        declared = set(tools)
        references = (
            reference
            for _index, text in workflow_steps
            for reference in _CODE_REFERENCE.findall(text)
        )
        return list(
            dict.fromkeys(
                reference
                for reference in references
                if (
                    reference not in declared
                    and (
                        "_" in reference
                        or reference in GovernedSkillToolSimulationAdapter.known_tools()
                    )
                )
            )
        )

    @staticmethod
    def _has_terminal_verification(
        workflow_steps: list[tuple[int, str]],
        last_tool_step: int,
    ) -> bool:
        if last_tool_step <= 0:
            return True
        return any(
            index > last_tool_step and any(marker in text.lower() for marker in _VERIFY_MARKERS)
            for index, text in workflow_steps
        )

    @staticmethod
    def _has_refusal_policy(content: str) -> bool:
        lower = content.lower()
        return any(marker in lower for marker in _REFUSAL_MARKERS)

    @staticmethod
    def _fingerprint(simulation: SkillBehaviorSimulation) -> str:
        payload = {
            "status": simulation.status.value,
            "scenario_count": simulation.scenario_count,
            "declared_tools": simulation.declared_tools,
            "simulated_tools": simulation.simulated_tools,
            "missing_tools": simulation.missing_tools,
            "undeclared_tools": simulation.undeclared_tools,
            "terminal_verification": simulation.has_terminal_verification,
            "refusal_policy": simulation.has_refusal_policy,
            "receipts": [
                {
                    "scenario": receipt.scenario,
                    "step_index": receipt.step_index,
                    "tool_name": receipt.tool_name,
                    "outcome": receipt.outcome.value,
                }
                for receipt in simulation.receipts
            ],
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
