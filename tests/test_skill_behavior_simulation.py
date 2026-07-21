"""Deterministic, side-effect-free Skill Behavior Simulation regressions."""

from __future__ import annotations

from core.skills.skill_behavior_simulation import (
    DenyUnknownSkillToolSimulationAdapter,
    SkillBehaviorEvaluator,
)
from core.skills.skill_schema import (
    BehaviorSimulationStatus,
    CandidateSource,
    SimulatedToolOutcome,
    SkillCandidate,
    SkillToolSimulationReceipt,
)


def _candidate(
    *,
    tools: list[str] | None = None,
    workflow: str = "",
    automatic: bool = True,
) -> SkillCandidate:
    selected_tools = tools or ["read_file", "write_file"]
    content = (
        "---\n"
        "name: behavior-proof\n"
        "description: Simulate a reviewed workflow\n"
        "---\n\n"
        "# Behavior proof\n\n"
        "## When to use\n\n"
        "Use this skill when the user asks for a reviewed workflow.\n\n"
        "## Workflow\n\n"
        + (
            workflow
            or (
                "1. Use `read_file` to inspect approved inputs.\n"
                "2. Use `write_file` to save the reviewed result.\n"
                "3. Verify the result against the request.\n"
            )
        )
        + "\n## Safety\n\n"
        "Stop and ask the user when a tool is refused or needs approval.\n"
    )
    return SkillCandidate(
        id="behavior-proof",
        title="Behavior proof",
        rationale="Test candidate",
        proposed_name="behavior-proof",
        proposed_content=content,
        source_kind=(CandidateSource.SUCCESSFUL_TASK if automatic else CandidateSource.MANUAL),
        evidence={"tools": selected_tools, "privacy_checked": True},
    )


def test_known_tool_plan_replays_permitted_and_refusal_scenarios() -> None:
    evaluator = SkillBehaviorEvaluator()

    first = evaluator.evaluate(_candidate())
    second = evaluator.evaluate(_candidate())

    simulation = first.simulation
    assert simulation.status == BehaviorSimulationStatus.PASSED
    assert simulation.scenario_count == 2
    assert simulation.simulated_tools == ["read_file", "write_file"]
    assert simulation.refused_tools == ["write_file"]
    assert simulation.has_terminal_verification is True
    assert simulation.has_refusal_policy is True
    assert simulation.filesystem_accessed is False
    assert simulation.network_accessed is False
    assert simulation.commands_executed is False
    assert len(simulation.fingerprint) == 64
    assert simulation.fingerprint == second.simulation.fingerprint
    assert {receipt.outcome for receipt in simulation.receipts} == {
        SimulatedToolOutcome.PERMITTED,
        SimulatedToolOutcome.REFUSED,
    }


def test_missing_tool_and_terminal_verification_fail_closed() -> None:
    evidence = SkillBehaviorEvaluator().evaluate(
        _candidate(
            tools=["read_file", "write_file"],
            workflow="1. Use `read_file` to inspect approved inputs.\n",
        )
    )

    assert evidence.simulation.status == BehaviorSimulationStatus.FAILED
    assert evidence.simulation.missing_tools == ["write_file"]
    assert evidence.simulation.has_terminal_verification is False
    assert "声明工具未出现在有序流程" in evidence.simulation.summary


def test_unknown_and_high_risk_tools_are_never_simulated_as_permitted() -> None:
    unknown = SkillBehaviorEvaluator().evaluate(
        _candidate(
            tools=["custom_lookup"],
            workflow=("1. Use `custom_lookup` for the request.\n" "2. Verify the result.\n"),
        )
    )
    high_risk = SkillBehaviorEvaluator().evaluate(
        _candidate(
            tools=["shell"],
            workflow=("1. Use `shell` for the request.\n" "2. Verify the result.\n"),
        )
    )

    assert unknown.simulation.status == BehaviorSimulationStatus.FAILED
    assert unknown.permissions.unknown_tools == ["custom_lookup"]
    assert unknown.simulation.receipts[0].outcome == SimulatedToolOutcome.REFUSED
    assert high_risk.simulation.status == BehaviorSimulationStatus.FAILED
    assert high_risk.permissions.risk_level == "high"
    assert high_risk.simulation.receipts[0].outcome == SimulatedToolOutcome.REFUSED


class _CustomReadSimulationAdapter:
    @staticmethod
    def supports(tool_name: str) -> bool:
        return tool_name == "custom_lookup"

    @staticmethod
    def capability(_tool_name: str) -> tuple[str, str, bool]:
        return "读取测试目录", "low", False

    @staticmethod
    def simulate(
        tool_name: str,
        *,
        scenario: str,
        step_index: int,
    ) -> SkillToolSimulationReceipt:
        return SkillToolSimulationReceipt(
            scenario=scenario,
            step_index=step_index,
            tool_name=tool_name,
            outcome=SimulatedToolOutcome.PERMITTED,
            capability="读取测试目录",
            detail="测试 Adapter 合成回执",
        )


def test_adapter_seam_accepts_a_content_free_test_implementation() -> None:
    evaluator = SkillBehaviorEvaluator(
        adapters=(
            _CustomReadSimulationAdapter(),
            DenyUnknownSkillToolSimulationAdapter(),
        )
    )

    evidence = evaluator.evaluate(
        _candidate(
            tools=["custom_lookup"],
            workflow=("1. Use `custom_lookup` for the request.\n" "2. Verify the result.\n"),
            automatic=False,
        )
    )

    assert evidence.simulation.status == BehaviorSimulationStatus.PASSED
    assert evidence.permissions.unknown_tools == []
    assert evidence.permissions.capabilities == ["读取测试目录"]
