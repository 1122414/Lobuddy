"""Deterministic, non-executing evaluation gate for skill candidates."""

from __future__ import annotations

import hashlib
import re
import tempfile
import uuid
from pathlib import Path

from core.config import Settings
from core.skills.skill_behavior_simulation import SkillBehaviorEvaluator
from core.skills.skill_schema import (
    BehaviorSimulationStatus,
    EvaluationCheck,
    EvaluationCheckStatus,
    EvaluationStatus,
    ProvenanceStatus,
    SkillCandidate,
    SkillBehaviorSimulation,
    SkillCandidateProvenance,
    SkillEvaluationReport,
    SkillPermissionProfile,
)
from core.skills.skill_validator import SkillValidator


_VALID_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FRONTMATTER_NAME = re.compile(r"(?m)^name:\s*([a-z0-9]+(?:-[a-z0-9]+)*)\s*$")
_TRIGGER_RULE = re.compile(
    r"(?im)(^##\s*(?:trigger|when to use|usage)\b|"
    r"\bwhen\s+(?:the\s+)?user\b|\buse\s+this\s+skill\b)"
)
_WORKFLOW_STEP = re.compile(r"(?m)^\s*\d+[.)]\s+\S+")


class SkillEvaluationService:
    """Evaluate a proposal in an isolated package without executing it.

    The service writes only a temporary ``SKILL.md`` projection, then performs
    deterministic structure, trigger, workflow, privacy, and permission checks.
    It never imports candidate code, opens a network connection, or runs a
    command described by the candidate.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._validator = SkillValidator()

    def evaluate(
        self,
        candidate: SkillCandidate,
        *,
        provenance: SkillCandidateProvenance,
    ) -> SkillEvaluationReport:
        content_hash = self.content_hash(candidate.proposed_content)
        checks = [
            self._check_static(candidate),
            self._check_identity(candidate),
            self._check_trigger(candidate),
            self._check_workflow(candidate),
            self._check_privacy(candidate),
            self._check_provenance(provenance),
        ]
        behavior_evidence = SkillBehaviorEvaluator().evaluate(candidate)
        permissions = behavior_evidence.permissions
        checks.append(self._check_behavior(behavior_evidence.simulation))
        checks.append(self._check_permissions(permissions))
        checks.append(self._check_isolated_projection(candidate, content_hash))

        score = round(
            sum(check.points for check in checks)
            / max(1, sum(check.max_points for check in checks))
            * 100
        )
        has_blocking_failure = any(
            check.blocking and check.status == EvaluationCheckStatus.FAILED for check in checks
        )
        minimum = self._settings.skill_evaluation_min_score
        if has_blocking_failure:
            status = EvaluationStatus.FAILED
            summary = "隔离评测未通过：存在阻断性安全、结构或行为问题"
        elif score >= minimum:
            status = EvaluationStatus.PASSED
            summary = "隔离包与行为模拟通过，可进入人工审批"
        else:
            status = EvaluationStatus.NEEDS_REVIEW
            summary = "评测证据不足，需要修改提案后重新评测"

        return SkillEvaluationReport(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            candidate_revision=candidate.revision,
            content_hash=content_hash,
            status=status,
            score=score,
            minimum_score=minimum,
            summary=summary,
            checks=checks,
            permissions=permissions,
            provenance=provenance,
            behavior=behavior_evidence.simulation,
        )

    @staticmethod
    def content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _check_static(self, candidate: SkillCandidate) -> EvaluationCheck:
        valid_candidate, candidate_errors = self._validator.validate(candidate)
        valid_static, static_errors = self._validator.validate_static(candidate.proposed_content)
        errors = list(dict.fromkeys([*candidate_errors, *static_errors]))
        passed = valid_candidate and valid_static
        return self._check(
            "static",
            "结构与静态安全",
            passed,
            "通过 SKILL.md 结构、长度、危险命令与敏感信息检查" if passed else "；".join(errors),
            22,
            blocking=True,
        )

    @staticmethod
    def _check_identity(candidate: SkillCandidate) -> EvaluationCheck:
        matched = _FRONTMATTER_NAME.search(candidate.proposed_content)
        frontmatter_name = matched.group(1) if matched else ""
        passed = bool(
            _VALID_SKILL_NAME.fullmatch(candidate.proposed_name)
            and frontmatter_name == candidate.proposed_name
        )
        return SkillEvaluationService._check(
            "identity",
            "名称与包身份",
            passed,
            "提案名与 frontmatter 名称一致" if passed else "名称必须为小写连字符格式，且与 frontmatter 完全一致",
            14,
            blocking=True,
        )

    @staticmethod
    def _check_trigger(candidate: SkillCandidate) -> EvaluationCheck:
        passed = bool(_TRIGGER_RULE.search(candidate.proposed_content))
        return SkillEvaluationService._check(
            "trigger",
            "触发条件",
            passed,
            "包含可识别的用户意图触发条件" if passed else "缺少明确的 When to use / Trigger 规则",
            14,
            blocking=True,
        )

    @staticmethod
    def _check_workflow(candidate: SkillCandidate) -> EvaluationCheck:
        step_count = len(_WORKFLOW_STEP.findall(candidate.proposed_content))
        passed = step_count >= 2
        return SkillEvaluationService._check(
            "workflow",
            "流程可操作性",
            passed,
            f"识别到 {step_count} 个有序步骤" if passed else "至少需要两个明确、有序的操作步骤",
            15,
            blocking=True,
        )

    def _check_privacy(self, candidate: SkillCandidate) -> EvaluationCheck:
        valid, errors = self._validator.validate(candidate)
        sensitive = any("sensitive" in error.lower() for error in errors)
        if sensitive or not valid and any("secret" in error.lower() for error in errors):
            return self._check(
                "privacy",
                "隐私与来源",
                False,
                "提案仍包含凭据、邮箱或其他敏感内容",
                15,
                blocking=True,
            )
        privacy_checked = candidate.evidence.get("privacy_checked") is True
        if privacy_checked:
            return self._check(
                "privacy",
                "隐私与来源",
                True,
                "来源已脱敏，未保存原始输出或多模态内容",
                15,
                blocking=True,
            )
        return EvaluationCheck(
            key="privacy",
            title="隐私与来源",
            status=EvaluationCheckStatus.WARNING,
            detail="未发现敏感内容，但缺少自动生成链路的来源证明",
            points=9,
            max_points=15,
            blocking=False,
        )

    @staticmethod
    def _check_provenance(
        provenance: SkillCandidateProvenance,
    ) -> EvaluationCheck:
        if provenance.status == ProvenanceStatus.UNVERIFIED:
            return SkillEvaluationService._check(
                "provenance",
                "来源任务证明",
                False,
                provenance.detail,
                10,
                blocking=True,
            )
        if provenance.status == ProvenanceStatus.VERIFIED:
            return SkillEvaluationService._check(
                "provenance",
                "来源任务证明",
                True,
                (f"已核验 Task Run 与 {len(provenance.observed_tools)} " "种已完成工具轨迹"),
                10,
                blocking=True,
            )
        return SkillEvaluationService._check(
            "provenance",
            "来源任务证明",
            True,
            provenance.detail,
            10,
            blocking=True,
        )

    @staticmethod
    def _check_behavior(
        behavior: SkillBehaviorSimulation,
    ) -> EvaluationCheck:
        passed = behavior.status == BehaviorSimulationStatus.PASSED
        return SkillEvaluationService._check(
            "behavior_simulation",
            "受限行为模拟",
            passed,
            behavior.summary,
            15,
            blocking=True,
        )

    @staticmethod
    def _check_permissions(
        permissions: SkillPermissionProfile,
    ) -> EvaluationCheck:
        if permissions.risk_level == "high":
            return SkillEvaluationService._check(
                "permissions",
                "权限差异",
                False,
                "候选请求系统命令或电脑控制能力，自动进化链路不允许",
                15,
                blocking=True,
            )
        if permissions.unknown_tools:
            return EvaluationCheck(
                key="permissions",
                title="权限差异",
                status=EvaluationCheckStatus.WARNING,
                detail="存在未分类工具：" + "、".join(permissions.unknown_tools),
                points=8,
                max_points=15,
                blocking=False,
            )
        return SkillEvaluationService._check(
            "permissions",
            "权限差异",
            True,
            " · ".join(permissions.capabilities),
            15,
            blocking=True,
        )

    def _check_isolated_projection(
        self,
        candidate: SkillCandidate,
        expected_hash: str,
    ) -> EvaluationCheck:
        evaluation_root = (self._settings.data_dir / "skill-evaluations").resolve()
        evaluation_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(
                prefix="candidate-",
                dir=evaluation_root,
            ) as temp_dir:
                sandbox = Path(temp_dir).resolve()
                if sandbox.parent != evaluation_root:
                    raise RuntimeError("Evaluation directory escaped its root")
                skill_file = sandbox / "SKILL.md"
                skill_file.write_text(
                    candidate.proposed_content,
                    encoding="utf-8",
                )
                actual_hash = self.content_hash(skill_file.read_text(encoding="utf-8"))
                if actual_hash != expected_hash:
                    raise RuntimeError("Projected content hash changed")
                if {path.name for path in sandbox.iterdir()} != {"SKILL.md"}:
                    raise RuntimeError("Unexpected files appeared in evaluation")
        except (OSError, RuntimeError) as exc:
            return self._check(
                "isolated_projection",
                "隔离包投影",
                False,
                str(exc),
                5,
                blocking=True,
            )
        return self._check(
            "isolated_projection",
            "隔离包投影",
            True,
            "只写入临时 SKILL.md；未导入、未执行、未联网",
            5,
            blocking=True,
        )

    @staticmethod
    def _check(
        key: str,
        title: str,
        passed: bool,
        detail: str,
        points: int,
        *,
        blocking: bool,
    ) -> EvaluationCheck:
        return EvaluationCheck(
            key=key,
            title=title,
            status=(EvaluationCheckStatus.PASSED if passed else EvaluationCheckStatus.FAILED),
            detail=detail,
            points=points if passed else 0,
            max_points=points,
            blocking=blocking,
        )
