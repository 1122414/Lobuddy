"""Tests for recoverable, user-authorized Computer Use."""

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from PIL import Image

from core.computer_use.adapters import WindowsDesktopAdapter
from core.computer_use.coordinator import ComputerUseCoordinator
from core.computer_use.models import (
    ComputerAction,
    ComputerActionType,
    ComputerPlanStatus,
    ComputerSemanticSnapshot,
    ComputerTarget,
    ComputerTargetSource,
    utc_now,
)
from core.computer_use.safety import ComputerUseSafety
from core.config import Settings
from core.events import ComputerUseProgress, EventBus
from core.storage.computer_use_repo import ComputerUseRepository
from core.storage.db import Database
from core.storage.execution_trace_repository import ExecutionTraceRepository


class _DesktopAdapter:
    def __init__(self, tmp_path: Path) -> None:
        self._tmp_path = tmp_path
        self.actions: list[ComputerAction] = []
        self.captures: list[Path] = []

    def is_available(self) -> bool:
        return True

    def screen_size(self) -> tuple[int, int]:
        return (800, 600)

    def capture_screen(self) -> Path:
        path = self._tmp_path / f"screen-{len(self.captures)}.png"
        Image.new("RGB", (800, 600), "white").save(path)
        self.captures.append(path)
        return path

    def inspect_semantics(self) -> ComputerSemanticSnapshot:
        return ComputerSemanticSnapshot(
            foreground_app="测试设置",
            targets=[
                ComputerTarget(
                    id="native-workspace",
                    label="当前工作区",
                    role="window",
                    x=0,
                    y=0,
                    width=800,
                    height=600,
                    confidence=0.9,
                    source=ComputerTargetSource.NATIVE_CONTROL,
                )
            ],
        )

    def execute_action(self, action: ComputerAction) -> str:
        self.actions.append(action)
        return "fake_action_executed"


class _Vision:
    def __init__(
        self,
        responses: list[str] | None = None,
        observation_response: str = "",
    ) -> None:
        self.responses = iter(responses or ['{"verified": true, "summary": "visible"}'])
        self.observation_response = observation_response or ('{"summary":"测试窗口可见","targets":[]}')
        self.paths: list[Path] = []
        self.prompts: list[str] = []

    async def __call__(self, prompt: str, path: str) -> str:
        self.prompts.append(prompt)
        self.paths.append(Path(path))
        if "visual observer" in prompt:
            return self.observation_response
        return next(self.responses)


def _runtime(
    tmp_path: Path,
    *,
    max_actions: int = 12,
    vision_responses: list[str] | None = None,
    observation_response: str = "",
    observation_ttl_seconds: int = 45,
    event_bus: EventBus | None = None,
    task_id: str = "",
):
    settings = Settings(
        llm_api_key="test",
        llm_multimodal_model="vision-test",
        computer_use_enabled=True,
        computer_use_max_actions_per_plan=max_actions,
        computer_use_observation_ttl_seconds=observation_ttl_seconds,
        data_dir=tmp_path / "data",
    )
    repository = ComputerUseRepository(Database(settings))
    adapter = _DesktopAdapter(tmp_path)
    vision = _Vision(vision_responses, observation_response)
    coordinator = ComputerUseCoordinator(
        settings,
        "session-1",
        vision,
        adapter=adapter,
        repository=repository,
        event_bus=event_bus,
        task_id=task_id,
    )
    return coordinator, repository, adapter, vision


def _observed_action(
    runtime: ComputerUseCoordinator,
    plan_id: str,
    *,
    action: ComputerActionType,
    expected: str,
    description: str,
    x: int | None = None,
    y: int | None = None,
    text: str = "",
) -> ComputerAction:
    observation = asyncio.run(runtime.observe(plan_id))
    target = observation.targets[0]
    return ComputerAction(
        action=action,
        observation_id=observation.observation_id,
        target_id=target.id,
        target_label=target.label,
        target_role=target.role,
        expected_outcome=expected,
        description=description,
        x=x,
        y=y,
        text=text,
    )


class TestComputerUseCoordinator:
    def test_plan_requires_authorization_before_observation(self, tmp_path: Path):
        runtime, _, _, _ = _runtime(tmp_path)
        plan, resumed = runtime.create_or_resume_plan(goal="打开设置并查看主题")

        assert resumed is False
        assert plan.status == ComputerPlanStatus.PENDING_APPROVAL
        with pytest.raises(PermissionError):
            asyncio.run(runtime.observe(plan.id))

    def test_observation_is_deleted_after_multimodal_analysis(self, tmp_path: Path):
        runtime, _, adapter, vision = _runtime(
            tmp_path,
            observation_response=(
                '{"summary":"设置窗口可见，主题按钮在 (420, 220)",'
                '"targets":[{"label":"主题按钮","role":"button","x":400,"y":205,'
                '"width":40,"height":30,"confidence":0.96}]}'
            ),
        )
        plan, _ = runtime.create_or_resume_plan(goal="查看主题")
        runtime.authorize_plan(plan.id)

        observation = asyncio.run(runtime.observe(plan.id))

        assert observation.width == 800
        assert "(420, 220)" in observation.analysis
        assert observation.foreground_app == "测试设置"
        assert any(target.label == "主题按钮" for target in observation.targets)
        assert vision.paths == adapter.captures
        assert all(not path.exists() for path in adapter.captures)

    def test_action_checkpoint_redacts_typed_text(self, tmp_path: Path):
        runtime, repository, adapter, _ = _runtime(tmp_path)
        plan, _ = runtime.create_or_resume_plan(
            goal="填写昵称",
            allowed_actions="type_text",
        )
        runtime.authorize_plan(plan.id)
        action = _observed_action(
            runtime,
            plan.id,
            action=ComputerActionType.TYPE_TEXT,
            text="private nickname",
            description="填写昵称字段",
            expected="昵称字段显示已填写状态",
        )

        result = asyncio.run(runtime.execute(plan.id, action))
        checkpoints = repository.list_checkpoints(plan.id)

        assert result.success is True
        assert adapter.actions == [action]
        assert "private nickname" not in str(checkpoints)
        assert "text_length=16" in checkpoints[0]["action_summary"]
        assert "填写昵称字段" not in checkpoints[0]["action_summary"]
        assert checkpoints[0]["observation_id"] == action.observation_id
        assert checkpoints[0]["target_summary"] == "当前工作区 · window"
        assert checkpoints[0]["expected_outcome"] == "昵称字段显示已填写状态"

    def test_action_limit_pauses_plan_but_allows_final_verification(self, tmp_path: Path):
        runtime, repository, _, _ = _runtime(tmp_path, max_actions=1)
        plan, _ = runtime.create_or_resume_plan(
            goal="点击按钮",
            allowed_actions="click",
        )
        runtime.authorize_plan(plan.id)
        action = _observed_action(
            runtime,
            plan.id,
            action=ComputerActionType.CLICK,
            x=200,
            y=100,
            description="点击主题按钮",
            expected="主题面板已经打开",
        )
        result = asyncio.run(runtime.execute(plan.id, action))

        assert repository.get_plan(plan.id).status == ComputerPlanStatus.PAUSED
        verification = asyncio.run(
            runtime.verify(
                plan.id,
                "主题面板已经打开",
                checkpoint_id=result.checkpoint_id,
            )
        )
        assert verification.verified is True

    def test_invalid_visual_verification_is_fail_closed(self, tmp_path: Path):
        runtime, _, _, _ = _runtime(
            tmp_path,
            vision_responses=["The screen probably looks correct"],
        )
        plan, _ = runtime.create_or_resume_plan(
            goal="点击按钮",
            allowed_actions="click",
        )
        runtime.authorize_plan(plan.id)
        action = _observed_action(
            runtime,
            plan.id,
            action=ComputerActionType.CLICK,
            x=20,
            y=30,
            description="点击按钮",
            expected="面板打开",
        )
        result = asyncio.run(runtime.execute(plan.id, action))

        verification = asyncio.run(
            runtime.verify(plan.id, "面板打开", checkpoint_id=result.checkpoint_id)
        )

        assert verification.verified is False
        assert "not valid JSON" in verification.summary

    def test_high_impact_action_needs_one_time_grant(self, tmp_path: Path):
        runtime, _, adapter, _ = _runtime(tmp_path)
        plan, _ = runtime.create_or_resume_plan(
            goal="发送消息",
            allowed_actions="click",
        )
        runtime.authorize_plan(plan.id)
        action = _observed_action(
            runtime,
            plan.id,
            action=ComputerActionType.CLICK,
            x=300,
            y=200,
            description="点击发送按钮",
            expected="消息出现在已发送区域",
        )

        with pytest.raises(PermissionError, match="separate confirmation"):
            asyncio.run(runtime.execute(plan.id, action))
        runtime.grant_high_impact_action(plan.id, action)
        assert asyncio.run(runtime.execute(plan.id, action)).success is True
        assert asyncio.run(
            runtime.verify(
                plan.id,
                "消息出现在已发送区域",
            )
        ).verified
        second_action = _observed_action(
            runtime,
            plan.id,
            action=ComputerActionType.CLICK,
            x=300,
            y=200,
            description="点击发送按钮",
            expected="另一条消息出现在已发送区域",
        )
        with pytest.raises(PermissionError, match="separate confirmation"):
            asyncio.run(runtime.execute(plan.id, second_action))

        assert len(adapter.actions) == 1

    def test_plan_resumes_from_persistent_checkpoint(self, tmp_path: Path):
        runtime, repository, adapter, vision = _runtime(tmp_path)
        first, _ = runtime.create_or_resume_plan(goal="继续设置主题")
        runtime.authorize_plan(first.id)
        action = _observed_action(
            runtime,
            first.id,
            action=ComputerActionType.CLICK,
            x=50,
            y=50,
            description="打开主题列表",
            expected="主题列表已经打开",
        )
        asyncio.run(runtime.execute(first.id, action))
        second_runtime = ComputerUseCoordinator(
            runtime._settings,
            "session-1",
            vision,
            adapter=adapter,
            repository=repository,
        )

        resumed, was_resumed = second_runtime.create_or_resume_plan(goal="继续设置主题")

        assert was_resumed is True
        assert resumed.id == first.id
        assert resumed.completed_actions == 1

    def test_expired_authorization_is_paused(self, tmp_path: Path):
        runtime, repository, _, _ = _runtime(tmp_path)
        plan, _ = runtime.create_or_resume_plan(goal="查看窗口")
        repository.authorize(plan.id, utc_now() - timedelta(seconds=1))

        with pytest.raises(PermissionError):
            asyncio.run(runtime.observe(plan.id))

        assert repository.get_plan(plan.id).status == ComputerPlanStatus.PAUSED

    def test_runtime_enforces_observe_act_verify_sequence(self, tmp_path: Path):
        runtime, _, _, _ = _runtime(tmp_path)
        plan, _ = runtime.create_or_resume_plan(
            goal="打开并保存设置",
            allowed_actions="click",
        )
        runtime.authorize_plan(plan.id)

        with pytest.raises(ValueError, match="observation_id"):
            asyncio.run(
                runtime.execute(
                    plan.id,
                    ComputerAction(
                        action=ComputerActionType.CLICK,
                        x=20,
                        y=20,
                        target_label="保存",
                        expected_outcome="保存成功",
                    ),
                )
            )

        first_action = _observed_action(
            runtime,
            plan.id,
            action=ComputerActionType.CLICK,
            x=20,
            y=20,
            description="打开设置",
            expected="设置面板打开",
        )
        asyncio.run(runtime.execute(plan.id, first_action))
        second_action = _observed_action(
            runtime,
            plan.id,
            action=ComputerActionType.CLICK,
            x=30,
            y=30,
            description="保存设置",
            expected="保存成功",
        )

        with pytest.raises(PermissionError, match="Verify the previous"):
            asyncio.run(runtime.execute(plan.id, second_action))
        with pytest.raises(ValueError, match="latest action is verified"):
            runtime.finish(plan.id, True)

        verification = asyncio.run(runtime.verify(plan.id, "设置面板打开"))
        assert verification.verified is True
        assert asyncio.run(runtime.execute(plan.id, second_action)).success is True

    def test_action_is_bound_to_fresh_semantic_target(self, tmp_path: Path):
        runtime, _, _, _ = _runtime(
            tmp_path,
            observation_response=(
                '{"summary":"保存按钮可见","targets":[{"label":"保存","role":"button",'
                '"x":100,"y":100,"width":80,"height":30,"confidence":0.97}]}'
            ),
        )
        plan, _ = runtime.create_or_resume_plan(
            goal="保存设置",
            allowed_actions="click",
        )
        runtime.authorize_plan(plan.id)
        observation = asyncio.run(runtime.observe(plan.id))
        target = next(item for item in observation.targets if item.label == "保存")
        action = ComputerAction(
            action=ComputerActionType.CLICK,
            observation_id=observation.observation_id,
            target_id=target.id,
            target_label=target.label,
            target_role=target.role,
            expected_outcome="保存成功提示可见",
            description="点击保存按钮",
            x=700,
            y=500,
        )

        with pytest.raises(ValueError, match="outside the selected semantic target"):
            asyncio.run(runtime.execute(plan.id, action))

        broad_target = next(item for item in observation.targets if item.id == "native-workspace")
        with pytest.raises(ValueError, match="most specific semantic target"):
            asyncio.run(
                runtime.execute(
                    plan.id,
                    action.model_copy(
                        update={
                            "target_id": broad_target.id,
                            "target_label": broad_target.label,
                            "target_role": broad_target.role,
                            "x": 120,
                            "y": 110,
                        }
                    ),
                )
            )

        runtime._observations[observation.observation_id] = observation.model_copy(
            update={"observed_at": utc_now() - timedelta(minutes=5)}
        )
        with pytest.raises(ValueError, match="expired"):
            asyncio.run(
                runtime.execute(
                    plan.id,
                    action.model_copy(update={"x": 120, "y": 110}),
                )
            )

    def test_verification_expectation_cannot_change_after_action(self, tmp_path: Path):
        runtime, _, _, _ = _runtime(tmp_path)
        plan, _ = runtime.create_or_resume_plan(
            goal="保存设置",
            allowed_actions="click",
        )
        runtime.authorize_plan(plan.id)
        action = _observed_action(
            runtime,
            plan.id,
            action=ComputerActionType.CLICK,
            x=20,
            y=20,
            description="点击保存",
            expected="保存成功提示可见",
        )
        asyncio.run(runtime.execute(plan.id, action))

        with pytest.raises(ValueError, match="match the expectation"):
            asyncio.run(runtime.verify(plan.id, "窗口关闭"))

    def test_two_ambiguous_verifications_fail_the_plan(self, tmp_path: Path):
        runtime, repository, _, _ = _runtime(
            tmp_path,
            vision_responses=[
                '{"verified":false,"summary":"没有看到成功提示","confidence":0.4}',
                '{"verified":false,"summary":"结果仍然不明确","confidence":0.2}',
            ],
        )
        plan, _ = runtime.create_or_resume_plan(
            goal="保存设置",
            allowed_actions="click",
        )
        runtime.authorize_plan(plan.id)
        action = _observed_action(
            runtime,
            plan.id,
            action=ComputerActionType.CLICK,
            x=20,
            y=20,
            description="点击保存",
            expected="保存成功提示可见",
        )
        result = asyncio.run(runtime.execute(plan.id, action))

        first = asyncio.run(
            runtime.verify(
                plan.id,
                "保存成功提示可见",
                checkpoint_id=result.checkpoint_id,
            )
        )
        second = asyncio.run(
            runtime.verify(
                plan.id,
                "保存成功提示可见",
                checkpoint_id=result.checkpoint_id,
            )
        )

        assert first.verified is False
        assert second.verified is False
        assert repository.get_plan(plan.id).status == ComputerPlanStatus.FAILED
        checkpoint = repository.get_checkpoint(plan.id, result.checkpoint_id)
        assert checkpoint is not None
        assert checkpoint.verification_attempts == 2

    def test_progress_events_are_privacy_safe_and_step_keyed(self, tmp_path: Path):
        bus = EventBus()
        events: list[ComputerUseProgress] = []
        bus.subscribe(ComputerUseProgress, events.append)
        runtime, _, _, _ = _runtime(
            tmp_path,
            event_bus=bus,
            task_id="task-1",
        )
        plan, _ = runtime.create_or_resume_plan(
            goal="填写昵称",
            allowed_actions="type_text",
        )
        runtime.authorize_plan(plan.id)
        action = _observed_action(
            runtime,
            plan.id,
            action=ComputerActionType.TYPE_TEXT,
            text="private nickname",
            description="填写昵称",
            expected="昵称字段显示已填写状态",
        )
        result = asyncio.run(runtime.execute(plan.id, action))
        asyncio.run(
            runtime.verify(
                plan.id,
                "昵称字段显示已填写状态",
                checkpoint_id=result.checkpoint_id,
            )
        )

        assert [event.step_key for event in events] == [
            "plan",
            "authorize",
            "observe-1",
            "observe-1",
            "act-1",
            "act-1",
            "verify-1",
            "verify-1",
        ]
        assert all(event.task_id == "task-1" for event in events)
        assert [event.stage_family for event in events] == [
            "computer-plan",
            "computer-authorize",
            "computer-observe",
            "computer-observe",
            "computer-act",
            "computer-act",
            "computer-verify",
            "computer-verify",
        ]
        assert [event.depends_on for event in events] == [
            (),
            ("plan",),
            ("authorize",),
            ("authorize",),
            ("observe-1",),
            ("observe-1",),
            ("act-1",),
            ("act-1",),
        ]
        assert "private nickname" not in str(events)


class TestComputerUseSafety:
    def test_blocks_unapproved_action_and_out_of_bounds_coordinates(self):
        safety = ComputerUseSafety()
        plan = _plan_for_safety([ComputerActionType.CLICK])

        with pytest.raises(ValueError, match="outside the approved plan"):
            safety.validate_action(
                ComputerAction(
                    action=ComputerActionType.TYPE_TEXT,
                    text="hello",
                ),
                plan,
                (800, 600),
            )
        with pytest.raises(ValueError, match="x coordinate"):
            safety.validate_action(
                ComputerAction(action=ComputerActionType.CLICK, x=900, y=10),
                plan,
                (800, 600),
            )

    def test_blocks_unknown_hotkeys_and_flags_high_impact_actions(self):
        safety = ComputerUseSafety()
        plan = _plan_for_safety([ComputerActionType.HOTKEY])

        with pytest.raises(ValueError, match="not allowed"):
            safety.validate_action(
                ComputerAction(
                    action=ComputerActionType.HOTKEY,
                    hotkey=["alt", "f4"],
                ),
                plan,
                (800, 600),
            )
        assert safety.requires_individual_confirmation(
            ComputerAction(
                action=ComputerActionType.CLICK,
                x=1,
                y=1,
                description="点击发送按钮",
            )
        )

    def test_rejects_tasks_that_require_credentials_or_secrets(self):
        safety = ComputerUseSafety()

        with pytest.raises(ValueError, match="does not handle"):
            safety.validate_goal("在登录页输入密码并继续")

    def test_native_semantics_never_reads_text_field_values(self, monkeypatch):
        monkeypatch.setattr(
            WindowsDesktopAdapter,
            "_window_text",
            staticmethod(lambda _user32, _hwnd: "private value"),
        )

        assert WindowsDesktopAdapter._control_label(None, 1, "Edit") == ""
        assert WindowsDesktopAdapter._control_label(None, 1, "RichEdit20W") == ""
        assert WindowsDesktopAdapter._control_label(None, 1, "Button") == "private value"


class TestComputerUsePrivacy:
    def test_trace_repository_redacts_computer_typed_text(self, tmp_path: Path):
        settings = Settings(llm_api_key="test", data_dir=tmp_path / "data")
        repository = ExecutionTraceRepository(Database(settings))

        repository.record(
            session_id="s1",
            intent="computer_use",
            tool_name="computer_act",
            arguments={"action": "type_text", "text": "top secret"},
            status="completed",
        )
        row = repository.get_traces_for_session("s1")[0]

        assert "top secret" not in row["arguments_json"]
        assert "<redacted:10 chars>" in row["arguments_json"]

    def test_checkpoint_schema_has_no_screen_or_typed_text_columns(self, tmp_path: Path):
        runtime, repository, _, _ = _runtime(tmp_path)
        plan, _ = runtime.create_or_resume_plan(goal="schema")
        with repository.db.get_connection() as conn:
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(computer_use_checkpoint)")
            }

        assert "screenshot" not in columns
        assert "text" not in columns
        assert "plan_id" in columns
        assert plan.id

    def test_existing_checkpoint_table_is_upgraded_in_place(self, tmp_path: Path):
        settings = Settings(llm_api_key="test", data_dir=tmp_path / "data")
        database = Database(settings)
        with database.get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE computer_use_checkpoint (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    action_summary TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_summary TEXT NOT NULL DEFAULT '',
                    verification_summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

        repository = ComputerUseRepository(database)
        with repository.db.get_connection() as conn:
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(computer_use_checkpoint)")
            }

        assert {
            "observation_id",
            "target_summary",
            "target_source",
            "expected_outcome",
            "verification_attempts",
        } <= columns


def _plan_for_safety(actions: list[ComputerActionType]):
    from core.computer_use.models import ComputerPlan

    return ComputerPlan(
        id="plan",
        session_id="s",
        goal="test",
        allowed_actions=actions,
        status=ComputerPlanStatus.ACTIVE,
        authorized_until=utc_now() + timedelta(minutes=1),
    )
