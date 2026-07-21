"""Deep Interface for plan, authorization, action, checkpoint, and verification."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Awaitable, Callable

from core.computer_use.adapters import DesktopAdapter, create_desktop_adapter
from core.computer_use.models import (
    ComputerAction,
    ComputerActionResult,
    ComputerCheckpointStatus,
    ComputerObservation,
    ComputerPlan,
    ComputerPlanStatus,
    ComputerSemanticSnapshot,
    ComputerTarget,
    ComputerTargetSource,
    ComputerVerification,
    utc_now,
)
from core.computer_use.safety import ComputerUseSafety
from core.config import Settings
from core.events import ComputerUseProgress, EventBus
from core.storage.computer_use_repo import ComputerUseRepository

VisionAnalyzer = Callable[[str, str], Awaitable[str]]
logger = logging.getLogger(__name__)


class ComputerUseCoordinator:
    """One recoverable Interface over desktop Adapter, safety, and persistence."""

    def __init__(
        self,
        settings: Settings,
        session_id: str,
        vision_analyzer: VisionAnalyzer,
        *,
        adapter: DesktopAdapter | None = None,
        repository: ComputerUseRepository | None = None,
        event_bus: EventBus | None = None,
        task_id: str = "",
    ) -> None:
        self._settings = settings
        self._session_id = session_id
        self._vision_analyzer = vision_analyzer
        self._adapter = adapter or create_desktop_adapter(
            action_delay_ms=settings.computer_use_action_delay_ms
        )
        self._repository = repository or ComputerUseRepository()
        self._safety = ComputerUseSafety()
        self._high_impact_grants: set[str] = set()
        self._event_bus = event_bus
        self._task_id = task_id
        self._observations: dict[str, ComputerObservation] = {}

    @property
    def available(self) -> bool:
        return bool(
            self._settings.computer_use_enabled
            and self._settings.llm_multimodal_model
            and self._adapter.is_available()
        )

    def create_or_resume_plan(
        self,
        *,
        goal: str,
        target_app: str = "",
        allowed_actions: str = "",
        max_actions: int | None = None,
    ) -> tuple[ComputerPlan, bool]:
        if not self.available:
            raise RuntimeError(
                "Computer Use requires Windows, COMPUTER_USE_ENABLED=true, "
                "and LLM_MULTIMODAL_MODEL"
            )
        goal = goal.strip()
        if not goal:
            raise ValueError("Computer-use goal cannot be empty")
        self._safety.validate_goal(goal)
        actions = self._safety.parse_allowed_actions(allowed_actions)
        configured_max = self._settings.computer_use_max_actions_per_plan
        bounded_max = max_actions or configured_max
        bounded_max = max(1, min(configured_max, bounded_max))
        plan, resumed = self._repository.create_or_resume_plan(
            session_id=self._session_id,
            goal=goal[:1000],
            target_app=target_app.strip()[:200],
            allowed_actions=actions,
            max_actions=bounded_max,
            task_id=self._task_id,
        )
        self._publish_progress(
            plan,
            phase="planned",
            step_key="plan",
            title="规划受控电脑操作",
            detail=(
                f"恢复到第 {plan.completed_actions + 1} 步" if resumed else f"最多 {plan.max_actions} 个动作"
            ),
            status="success",
        )
        return plan, resumed

    def plan_for_authorization(self, plan_id: str) -> ComputerPlan:
        plan = self._require_owned_plan(plan_id)
        if plan.status in {ComputerPlanStatus.COMPLETED, ComputerPlanStatus.FAILED}:
            raise ValueError("Finished plans cannot be re-authorized")
        return plan

    def authorize_plan(self, plan_id: str) -> ComputerPlan:
        plan = self.plan_for_authorization(plan_id)
        valid_until = utc_now() + timedelta(
            minutes=self._settings.computer_use_authorization_minutes
        )
        authorized = self._repository.authorize(plan.id, valid_until)
        self._publish_progress(
            authorized,
            phase="authorized",
            step_key="authorize",
            title="获得本次操作授权",
            detail=f"有效期 {self._settings.computer_use_authorization_minutes} 分钟",
            status="success",
        )
        return authorized

    def authorization_preview(self, plan_id: str) -> str:
        return self._safety.authorization_preview(self.plan_for_authorization(plan_id))

    def validate_action_request(self, plan_id: str, action: ComputerAction) -> ComputerPlan:
        plan = self._require_active_plan(plan_id)
        self._safety.validate_action(action, plan, self._adapter.screen_size())
        self._validate_action_sequence(plan, action)
        return plan

    def requires_individual_confirmation(self, action: ComputerAction) -> bool:
        return (
            self._settings.computer_use_high_impact_confirmation
            and self._safety.requires_individual_confirmation(action)
        )

    def grant_high_impact_action(
        self,
        plan_id: str,
        action: ComputerAction,
    ) -> None:
        self.validate_action_request(plan_id, action)
        self._high_impact_grants.add(self._action_fingerprint(plan_id, action))

    async def observe(self, plan_id: str, goal: str = "") -> ComputerObservation:
        plan = self._require_active_plan(plan_id)
        observation_index = plan.completed_actions + 1
        self._publish_progress(
            plan,
            phase="observing",
            step_key=f"observe-{observation_index}",
            title="观察并定位当前界面",
            detail="正在读取临时画面与原生控件",
            status="running",
            step_index=observation_index,
        )
        semantic_snapshot = await asyncio.to_thread(self._inspect_semantics)
        path = await asyncio.to_thread(self._adapter.capture_screen)
        try:
            width, height = self._adapter.screen_size()
            native_payload = [
                {
                    "id": target.id,
                    "label": target.label,
                    "role": target.role,
                    "bounds": [target.x, target.y, target.width, target.height],
                }
                for target in semantic_snapshot.targets[:40]
            ]
            prompt = (
                "You are the visual observer for a user-authorized desktop task. "
                f"The screenshot is {width}x{height}. "
                f"Task goal: {goal.strip() or plan.goal}. "
                "Ground the safest next action against both the screenshot and the native "
                f"control metadata below: {json.dumps(native_payload, ensure_ascii=False)}. "
                "Never infer hidden content. x/y must be the target's top-left screen "
                "coordinates. Return strict JSON only with this shape: "
                '{"summary":"visible state","targets":[{"label":"visible label",'
                '"role":"button","x":100,"y":100,"width":80,"height":30,'
                '"confidence":0.0}]}. Include no more than 12 relevant visible targets.'
            )
            raw_analysis = str(await self._vision_analyzer(prompt, str(path)))
            analysis, vision_targets = self._parse_observation(
                raw_analysis,
                width,
                height,
            )
            targets = self._merge_targets(
                semantic_snapshot.targets,
                vision_targets,
            )
            observation = ComputerObservation(
                observation_id=str(uuid.uuid4()),
                plan_id=plan.id,
                width=width,
                height=height,
                analysis=analysis[:12000],
                foreground_app=semantic_snapshot.foreground_app,
                targets=targets[:60],
            )
            self._observations[observation.observation_id] = observation
            self._prune_observations()
            self._publish_progress(
                plan,
                phase="observed",
                step_key=f"observe-{plan.completed_actions + 1}",
                title="观察并定位当前界面",
                detail=f"融合视觉与原生控件，找到 {len(observation.targets)} 个候选目标",
                status="success",
                step_index=plan.completed_actions + 1,
            )
            return observation
        finally:
            Path(path).unlink(missing_ok=True)

    async def execute(self, plan_id: str, action: ComputerAction) -> ComputerActionResult:
        plan = self.validate_action_request(plan_id, action)
        observation = self._require_observation(plan, action.observation_id)
        target = self._resolve_target(observation, action)
        target_source = target.source if target is not None else ComputerTargetSource.VISION
        grounded_summary = (
            target.display_summary()
            if target is not None and target.label
            else (
                f"{action.target_label} · {target.role}"
                if target is not None and target.role
                else action.target_summary()
            )
        )
        if self.requires_individual_confirmation(action):
            fingerprint = self._action_fingerprint(plan.id, action)
            if fingerprint not in self._high_impact_grants:
                raise PermissionError(
                    "High-impact computer action requires a separate confirmation"
                )
            self._high_impact_grants.discard(fingerprint)
        self._observations.pop(action.observation_id, None)
        self._publish_progress(
            plan,
            phase="acting",
            step_key=f"act-{plan.completed_actions + 1}",
            title=f"执行：{grounded_summary}",
            detail=action.description or action.action.value,
            status="running",
            step_index=plan.completed_actions + 1,
        )
        try:
            message = await asyncio.to_thread(self._adapter.execute_action, action)
        except Exception as exc:
            checkpoint_id = self._repository.record_action(
                plan,
                action,
                success=False,
                result_summary=type(exc).__name__,
                target_source=target_source,
                target_summary=grounded_summary,
            )
            self._publish_progress(
                plan,
                phase="action_failed",
                step_key=f"act-{plan.completed_actions + 1}",
                title=f"执行失败：{grounded_summary}",
                detail="输入动作没有成功，必须重新观察后再试。",
                status="failed",
                step_index=plan.completed_actions + 1,
            )
            return ComputerActionResult(
                success=False,
                plan_id=plan.id,
                checkpoint_id=checkpoint_id,
                step_index=plan.completed_actions + 1,
                message=f"Action failed: {type(exc).__name__}",
                target_summary=grounded_summary,
                expected_outcome=action.expected_outcome,
            )

        checkpoint_id = self._repository.record_action(
            plan,
            action,
            success=True,
            result_summary=message,
            target_source=target_source,
            target_summary=grounded_summary,
        )
        self._publish_progress(
            plan,
            phase="acted",
            step_key=f"act-{plan.completed_actions + 1}",
            title=f"已执行：{grounded_summary}",
            detail=f"等待验证：{action.expected_outcome}",
            status="success",
            step_index=plan.completed_actions + 1,
        )
        updated = self._repository.get_plan(plan.id)
        if updated is not None and updated.completed_actions >= updated.max_actions:
            self._repository.pause(updated.id)
        return ComputerActionResult(
            success=True,
            plan_id=plan.id,
            checkpoint_id=checkpoint_id,
            step_index=plan.completed_actions + 1,
            message=message,
            target_summary=grounded_summary,
            expected_outcome=action.expected_outcome,
        )

    async def verify(
        self,
        plan_id: str,
        expected: str,
        checkpoint_id: str = "",
    ) -> ComputerVerification:
        plan = self._require_active_plan(plan_id, allow_paused_at_limit=True)
        checkpoint = (
            self._repository.latest_checkpoint_model(plan.id)
            if not checkpoint_id
            else self._repository.get_checkpoint(plan.id, checkpoint_id)
        )
        if checkpoint is None:
            raise ValueError("No action checkpoint is available to verify")
        latest_checkpoint = self._repository.latest_checkpoint_model(plan.id)
        if latest_checkpoint is None or checkpoint.id != latest_checkpoint.id:
            raise ValueError("Only the latest computer action checkpoint can be verified")
        if checkpoint.status not in {
            ComputerCheckpointStatus.ACTION_COMPLETED,
            ComputerCheckpointStatus.VERIFICATION_FAILED,
        }:
            raise ValueError("Only a completed action can be visually verified")

        stored_expected = checkpoint.expected_outcome.strip()
        requested_expected = expected.strip()
        if (
            stored_expected
            and requested_expected
            and (self._normalize_text(stored_expected) != self._normalize_text(requested_expected))
        ):
            raise ValueError(
                "Verification outcome must match the expectation recorded before the action"
            )
        effective_expected = stored_expected or requested_expected
        if not effective_expected:
            raise ValueError("A concrete expected visible outcome is required")

        self._publish_progress(
            plan,
            phase="verifying",
            step_key=f"verify-{checkpoint.step_index}",
            title="验证执行结果",
            detail=effective_expected,
            status="running",
            step_index=checkpoint.step_index,
        )

        path = await asyncio.to_thread(self._adapter.capture_screen)
        try:
            width, height = self._adapter.screen_size()
            prompt = (
                "Verify a desktop action from the current screenshot. "
                f"Screenshot size: {width}x{height}. "
                f"Expected visible outcome recorded before the action: {effective_expected}. "
                "Return strict JSON only: "
                '{"verified":true|false,"summary":"visible evidence","confidence":0.0}. '
                "Use false if evidence is ambiguous."
            )
            raw = str(await self._vision_analyzer(prompt, str(path)))
        finally:
            Path(path).unlink(missing_ok=True)

        verified, summary, confidence = self._parse_verification(raw)
        attempts = self._repository.record_verification(
            plan.id,
            checkpoint.id,
            verified=verified,
            summary=summary,
        )
        if not verified and attempts >= 2:
            self._repository.finish(plan.id, False)
        self._publish_progress(
            plan,
            phase="verified" if verified else "verification_failed",
            step_key=f"verify-{checkpoint.step_index}",
            title="结果符合预期" if verified else "结果还不确定",
            detail=(
                f"视觉置信度 {confidence:.0%}，已看到预期变化"
                if verified
                else f"视觉置信度 {confidence:.0%}，没有足够证据确认结果"
            ),
            status="success" if verified else ("failed" if attempts >= 2 else "warning"),
            step_index=checkpoint.step_index,
        )
        return ComputerVerification(
            plan_id=plan.id,
            checkpoint_id=checkpoint.id,
            verified=verified,
            summary=summary,
            expected_outcome=effective_expected,
            confidence=confidence,
        )

    def finish(self, plan_id: str, success: bool) -> ComputerPlan:
        plan = self._require_owned_plan(plan_id)
        if success:
            checkpoint = self._repository.latest_checkpoint_model(plan.id)
            if checkpoint is None or checkpoint.status != ComputerCheckpointStatus.VERIFIED:
                raise ValueError(
                    "A Computer Use plan can only complete after its latest action is verified"
                )
        finished = self._repository.finish(plan.id, success)
        self._publish_progress(
            finished,
            phase="completed" if success else "failed",
            step_key="finish",
            title="电脑操作已完成" if success else "电脑操作已安全停止",
            detail=(f"共完成并验证 {finished.completed_actions} 个动作" if success else "没有继续执行未经验证的动作"),
            status="success" if success else "failed",
            step_index=finished.completed_actions,
        )
        return finished

    def _validate_action_sequence(
        self,
        plan: ComputerPlan,
        action: ComputerAction,
    ) -> None:
        latest = self._repository.latest_checkpoint_model(plan.id)
        if latest is not None and latest.status == ComputerCheckpointStatus.ACTION_COMPLETED:
            raise PermissionError(
                "Verify the previous computer action before executing another one"
            )
        if not action.observation_id.strip():
            raise ValueError("A fresh computer_observe observation_id is required")
        if not action.target_label.strip():
            raise ValueError("A visible semantic target label is required")
        if not action.expected_outcome.strip():
            raise ValueError(
                "Record a concrete expected visible outcome before executing the action"
            )

        observation = self._require_observation(plan, action.observation_id)
        target = self._resolve_target(observation, action)
        if target is not None and target.label:
            expected_label = self._normalize_text(target.label)
            supplied_label = self._normalize_text(action.target_label)
            if expected_label not in supplied_label and supplied_label not in expected_label:
                raise ValueError("target_label does not match the selected semantic target")
        pointer_action = action.action.value in {"move", "click", "double_click"}
        if pointer_action and target is not None:
            if action.x is None or action.y is None or not target.contains(action.x, action.y):
                raise ValueError("Pointer coordinates are outside the selected semantic target")
            if action.action.value in {"click", "double_click"}:
                self._require_most_specific_target(
                    observation,
                    target,
                    action.x,
                    action.y,
                )
        if pointer_action and observation.targets and not action.target_id:
            raise ValueError(
                "Choose a target_id from computer_observe before using pointer coordinates"
            )

    def _require_observation(
        self,
        plan: ComputerPlan,
        observation_id: str,
    ) -> ComputerObservation:
        observation = self._observations.get(observation_id)
        if observation is None or observation.plan_id != plan.id:
            raise ValueError(
                "Observation is missing or belongs to another plan; observe the screen again"
            )
        age = (utc_now() - observation.observed_at).total_seconds()
        if age > self._settings.computer_use_observation_ttl_seconds:
            self._observations.pop(observation_id, None)
            raise ValueError("Desktop observation expired; observe the screen again")
        return observation

    @staticmethod
    def _resolve_target(
        observation: ComputerObservation,
        action: ComputerAction,
    ) -> ComputerTarget | None:
        if not action.target_id:
            return None
        for target in observation.targets:
            if target.id == action.target_id:
                return target
        raise ValueError("target_id was not present in the selected desktop observation")

    @staticmethod
    def _require_most_specific_target(
        observation: ComputerObservation,
        selected: ComputerTarget,
        x: int,
        y: int,
    ) -> None:
        selected_area = selected.width * selected.height
        if selected_area <= 0:
            return
        actionable_roles = {
            "button",
            "text field",
            "text editor",
            "combo box",
            "list",
            "tree",
            "tab",
            "toolbar",
        }
        has_more_specific = any(
            candidate.id != selected.id
            and candidate.role in actionable_roles
            and candidate.width * candidate.height > 0
            and candidate.width * candidate.height < selected_area
            and candidate.contains(x, y)
            for candidate in observation.targets
        )
        if has_more_specific:
            raise ValueError(
                "Choose the most specific semantic target containing the pointer coordinates"
            )

    def _inspect_semantics(self) -> ComputerSemanticSnapshot:
        inspector = getattr(self._adapter, "inspect_semantics", None)
        if not callable(inspector):
            return ComputerSemanticSnapshot()
        try:
            snapshot = inspector()
            if isinstance(snapshot, ComputerSemanticSnapshot):
                return snapshot
            return ComputerSemanticSnapshot.model_validate(snapshot)
        except Exception as exc:
            logger.debug("Native desktop semantics unavailable: %s", type(exc).__name__)
            return ComputerSemanticSnapshot()

    @staticmethod
    def _parse_observation(
        raw: str,
        width: int,
        height: int,
    ) -> tuple[str, list[ComputerTarget]]:
        candidate = raw.strip()
        fenced = re.search(r"\{.*\}", candidate, re.DOTALL)
        if fenced is None:
            return candidate[:12000], []
        try:
            data = json.loads(fenced.group(0))
        except (json.JSONDecodeError, TypeError):
            return candidate[:12000], []

        summary = str(data.get("summary", "")).strip() or candidate[:12000]
        targets: list[ComputerTarget] = []
        raw_targets = data.get("targets", [])
        if not isinstance(raw_targets, list):
            return summary, targets
        for item in raw_targets[:20]:
            if not isinstance(item, dict):
                continue
            try:
                x = max(0, min(width - 1, int(item.get("x", 0))))
                y = max(0, min(height - 1, int(item.get("y", 0))))
                target_width = max(
                    0,
                    min(width - x, int(item.get("width", 0))),
                )
                target_height = max(
                    0,
                    min(height - y, int(item.get("height", 0))),
                )
                confidence = max(
                    0.0,
                    min(1.0, float(item.get("confidence", 0.5))),
                )
                targets.append(
                    ComputerTarget(
                        id=f"vision-{len(targets) + 1}",
                        label=str(item.get("label", ""))[:200],
                        role=str(item.get("role", ""))[:80],
                        x=x,
                        y=y,
                        width=target_width,
                        height=target_height,
                        confidence=confidence,
                        source=ComputerTargetSource.VISION,
                    )
                )
            except (TypeError, ValueError):
                continue
        return summary[:12000], targets

    @classmethod
    def _merge_targets(
        cls,
        native_targets: list[ComputerTarget],
        vision_targets: list[ComputerTarget],
    ) -> list[ComputerTarget]:
        merged = list(native_targets[:40])
        for vision_target in vision_targets:
            match_index = cls._matching_target_index(merged, vision_target)
            if match_index is None:
                merged.append(vision_target)
                continue
            native_target = merged[match_index]
            merged[match_index] = native_target.model_copy(
                update={
                    "label": vision_target.label or native_target.label,
                    "role": vision_target.role or native_target.role,
                    "confidence": max(
                        native_target.confidence,
                        vision_target.confidence,
                    ),
                    "source": ComputerTargetSource.COMBINED,
                }
            )
        return merged

    @classmethod
    def _matching_target_index(
        cls,
        candidates: list[ComputerTarget],
        target: ComputerTarget,
    ) -> int | None:
        target_label = cls._normalize_text(target.label)
        target_center = target.center
        for index, candidate in enumerate(candidates):
            candidate_label = cls._normalize_text(candidate.label)
            labels_match = bool(
                target_label
                and candidate_label
                and (
                    target_label == candidate_label
                    or target_label in candidate_label
                    or candidate_label in target_label
                )
            )
            candidate_center = candidate.center
            nearby = (
                abs(candidate_center[0] - target_center[0]) <= 80
                and abs(candidate_center[1] - target_center[1]) <= 80
            )
            if labels_match and nearby:
                return index
        return None

    def _prune_observations(self) -> None:
        ttl = self._settings.computer_use_observation_ttl_seconds
        now = utc_now()
        expired = [
            observation_id
            for observation_id, observation in self._observations.items()
            if (now - observation.observed_at).total_seconds() > ttl
        ]
        for observation_id in expired:
            self._observations.pop(observation_id, None)
        while len(self._observations) > 4:
            oldest_id = min(
                self._observations,
                key=lambda item: self._observations[item].observed_at,
            )
            self._observations.pop(oldest_id, None)

    def _publish_progress(
        self,
        plan: ComputerPlan,
        *,
        phase: str,
        step_key: str,
        title: str,
        detail: str,
        status: str,
        step_index: int = 0,
    ) -> None:
        if self._event_bus is None or not self._task_id:
            return
        stage_family, depends_on = self._work_stage_context(
            phase,
            step_key,
            step_index,
            plan.completed_actions,
        )
        self._event_bus.publish(
            ComputerUseProgress(
                task_id=self._task_id,
                plan_id=plan.id,
                phase=phase,
                step_key=step_key,
                title=title[:160],
                detail=detail[:300],
                status=status,
                step_index=step_index,
                max_actions=plan.max_actions,
                stage_family=stage_family,
                depends_on=depends_on,
            )
        )

    @staticmethod
    def _work_stage_context(
        phase: str,
        step_key: str,
        step_index: int,
        completed_actions: int,
    ) -> tuple[str, tuple[str, ...]]:
        """Describe explicit Work Stage dependencies without inferring from event order."""
        if phase == "planned":
            return "computer-plan", ()
        if phase == "authorized":
            return "computer-authorize", ("plan",)
        if phase in {"observing", "observed"}:
            index = max(1, step_index)
            dependency = "authorize" if index == 1 else f"verify-{index - 1}"
            return "computer-observe", (dependency,)
        if phase in {"acting", "acted", "action_failed"}:
            index = max(1, step_index)
            return "computer-act", (f"observe-{index}",)
        if phase in {"verifying", "verified", "verification_failed"}:
            index = max(1, step_index)
            return "computer-verify", (f"act-{index}",)
        if phase in {"completed", "failed"} and step_key == "finish":
            dependency = f"verify-{completed_actions}" if completed_actions > 0 else "authorize"
            return "computer-finish", (dependency,)
        return "computer-use", ()

    def _require_owned_plan(self, plan_id: str) -> ComputerPlan:
        plan = self._repository.get_plan(plan_id)
        if plan is None or plan.session_id != self._session_id:
            raise ValueError("Computer-use plan was not found for this session")
        return plan

    @staticmethod
    def _action_fingerprint(plan_id: str, action: ComputerAction) -> str:
        payload = f"{plan_id}:{action.model_dump_json()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", "", value).casefold()

    def _require_active_plan(
        self,
        plan_id: str,
        *,
        allow_paused_at_limit: bool = False,
    ) -> ComputerPlan:
        plan = self._require_owned_plan(plan_id)
        if allow_paused_at_limit and (
            plan.status == ComputerPlanStatus.PAUSED and plan.completed_actions >= plan.max_actions
        ):
            return plan
        if not plan.authorization_is_valid():
            if plan.status == ComputerPlanStatus.ACTIVE:
                self._repository.pause(plan.id)
            raise PermissionError("Computer-use plan is not currently authorized")
        return plan

    @staticmethod
    def _parse_verification(raw: str) -> tuple[bool, str, float]:
        candidate = raw.strip()
        fenced = re.search(r"\{.*\}", candidate, re.DOTALL)
        if fenced:
            try:
                data = json.loads(fenced.group(0))
                verified = data.get("verified") is True
                summary = str(data.get("summary", "")).strip() or candidate[:500]
                confidence = max(
                    0.0,
                    min(1.0, float(data.get("confidence", 0.0))),
                )
                return verified, summary[:500], confidence
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        return (
            False,
            f"Verification response was not valid JSON: {candidate[:400]}",
            0.0,
        )
