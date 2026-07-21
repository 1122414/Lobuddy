"""Tests for explainable, revocable current-session Data Control."""

from datetime import timedelta
from pathlib import Path

from PIL import Image

from core.companion.models import (
    CompanionEnergy,
    CompanionMood,
    CompanionSupportMode,
)
from core.companion.runtime import CompanionRuntime
from core.computer_use.models import (
    ComputerAction,
    ComputerActionType,
    ComputerPlanStatus,
    utc_now,
)
from core.config import Settings
from core.data_control import DataControlAction, DataControlCenter, DataControlTone
from core.memory.memory_control_service import MemoryControlService
from core.memory.memory_repository import MemoryRepository
from core.memory.privacy_mode import PrivacyModeManager
from core.models.chat import ChatMessage
from core.screen_region.models import ScreenRegionBounds, ScreenRegionDraft
from core.screen_region.runtime import ScreenRegionRuntime
from core.skills.skill_manager import SkillManager
from core.storage.chat_repo import ChatRepository
from core.storage.computer_use_repo import ComputerUseRepository
from core.storage.db import Database


def _build_center(tmp_path: Path, **overrides):
    values = {
        "llm_api_key": "super-secret-key",
        "llm_base_url": "https://models.example.test/v1",
        "llm_multimodal_model": "vision-test",
        "computer_use_enabled": True,
        "data_dir": tmp_path / "data",
        "workspace_path": tmp_path / "workspace",
        "skill_archive_dir": tmp_path / "archive",
    }
    values.update(overrides)
    settings = Settings(**values)
    db = Database(settings)
    chat = ChatRepository(db)
    computers = ComputerUseRepository(db)
    privacy = PrivacyModeManager(settings)
    companion = CompanionRuntime(settings, db=db)
    regions = ScreenRegionRuntime(
        settings,
        root=tmp_path / "regions",
        draft_roots=[tmp_path],
        file_hardener=lambda _path: None,
    )
    memories = MemoryControlService(
        settings,
        repo=MemoryRepository(db),
    )
    skills = SkillManager(settings, db)
    center = DataControlCenter(
        settings,
        privacy=privacy,
        chat_repo=chat,
        computer_repo=computers,
        screen_regions=regions,
        companion=companion,
        memories=memories,
        skills=skills,
    )
    return {
        "center": center,
        "settings": settings,
        "chat": chat,
        "computers": computers,
        "privacy": privacy,
        "companion": companion,
        "regions": regions,
    }


def _card(snapshot, key: str):
    return next(card for card in snapshot.cards if card.key == key)


def test_snapshot_explains_effective_surfaces_without_content(tmp_path):
    state = _build_center(tmp_path)
    snapshot = state["center"].snapshot("session-a")

    assert snapshot.headline == "本次对话使用你的常规数据设置"
    assert {card.key for card in snapshot.cards} == {
        "chat_history",
        "structured_memory",
        "companion_checkin",
        "activity_observation",
        "screen_region",
        "computer_use",
        "skill_evolution",
        "model_sharing",
    }
    assert _card(snapshot, "model_sharing").state_label.endswith("models.example.test")
    assert _card(snapshot, "computer_use").tone == DataControlTone.PROTECTED
    projection = snapshot.model_dump_json()
    assert "super-secret-key" not in projection
    assert "session-a" in projection


def test_privacy_mode_shows_chat_retention_as_an_independent_choice(tmp_path):
    state = _build_center(tmp_path, privacy_mode_allow_chat_history=True)
    center = state["center"]

    result = center.execute(
        DataControlAction.ENABLE_SESSION_PRIVACY,
        "session-a",
    )

    assert result.changed_count == 1
    assert result.snapshot.privacy_active is True
    assert _card(result.snapshot, "structured_memory").state_label == "本次不使用"
    assert _card(result.snapshot, "skill_evolution").state_label == "本次不学习"
    assert _card(result.snapshot, "activity_observation").state_label == "最小观察"
    assert _card(result.snapshot, "chat_history").tone == DataControlTone.ATTENTION


def test_revoke_computer_use_pauses_plan_but_preserves_checkpoint(tmp_path):
    state = _build_center(tmp_path)
    repository = state["computers"]
    plan, _ = repository.create_or_resume_plan(
        session_id="session-a",
        goal="保存当前文件",
        target_app="editor",
        allowed_actions=[ComputerActionType.CLICK],
        max_actions=3,
    )
    plan = repository.authorize(plan.id, utc_now() + timedelta(minutes=10))
    repository.record_action(
        plan,
        ComputerAction(
            action=ComputerActionType.CLICK,
            x=10,
            y=20,
            description="点击保存",
        ),
        success=True,
        result_summary="已点击",
    )

    result = state["center"].execute(
        DataControlAction.REVOKE_COMPUTER_USE,
        "session-a",
    )

    stored = repository.get_plan(plan.id)
    assert result.changed_count == 1
    assert stored is not None
    assert stored.status == ComputerPlanStatus.PAUSED
    assert stored.authorized_until is None
    assert len(repository.list_checkpoints(plan.id)) == 1


def test_data_control_finds_and_revokes_legacy_prefixed_session_grants(
    tmp_path,
):
    state = _build_center(tmp_path)
    repository = state["computers"]
    plan, _ = repository.create_or_resume_plan(
        session_id="lobuddy:session:session-a",
        goal="旧版本计划",
        target_app="editor",
        allowed_actions=[ComputerActionType.CLICK],
        max_actions=2,
    )
    repository.authorize(plan.id, utc_now() + timedelta(minutes=5))

    before = state["center"].snapshot("session-a")
    result = state["center"].execute(
        DataControlAction.REVOKE_COMPUTER_USE,
        "session-a",
    )

    assert _card(before, "computer_use").action == (
        DataControlAction.REVOKE_COMPUTER_USE
    )
    assert result.changed_count == 1
    assert repository.get_plan(plan.id).status == ComputerPlanStatus.PAUSED


def test_clear_chat_does_not_remove_session_or_other_data(tmp_path):
    state = _build_center(tmp_path)
    chat = state["chat"]
    chat.get_or_create_session("session-a")
    chat.save_message(
        ChatMessage(
            id="message-1",
            session_id="session-a",
            role="user",
            content="只用于验证清除边界",
        )
    )
    state["companion"].submit_check_in(
        CompanionMood.STEADY,
        CompanionEnergy.MEDIUM,
        CompanionSupportMode.QUIET,
    )

    result = state["center"].execute(
        DataControlAction.CLEAR_SESSION_CHAT,
        "session-a",
    )

    assert result.changed_count == 1
    assert chat.count_messages("session-a") == 0
    assert chat.get_session("session-a") is not None
    assert state["companion"].active_check_in() is not None


def test_revoke_companion_checkin_is_immediate(tmp_path):
    state = _build_center(tmp_path)
    state["companion"].submit_check_in(
        CompanionMood.TIRED,
        CompanionEnergy.LOW,
        CompanionSupportMode.ENCOURAGE,
    )
    before = state["center"].snapshot("session-a")
    assert _card(before, "companion_checkin").action == (DataControlAction.CLEAR_COMPANION_CHECKIN)

    result = state["center"].execute(
        DataControlAction.CLEAR_COMPANION_CHECKIN,
        "session-a",
    )

    assert result.changed_count == 1
    assert state["companion"].active_check_in() is None
    assert _card(result.snapshot, "companion_checkin").state_label == "未分享"


def test_clear_screen_regions_deletes_only_managed_temporary_pixels(tmp_path):
    state = _build_center(tmp_path)
    draft_path = tmp_path / "selected-region.png"
    Image.new("RGB", (320, 180), "white").save(draft_path)
    capture = state["regions"].adopt_temporary_capture(
        ScreenRegionDraft(
            path=draft_path,
            bounds=ScreenRegionBounds(x=20, y=30, width=320, height=180),
            screen_name="test-display",
        )
    )
    assert state["regions"].managed_capture_count == 1

    result = state["center"].execute(
        DataControlAction.CLEAR_SCREEN_REGIONS,
        "session-a",
    )

    assert result.changed_count == 1
    assert state["regions"].managed_capture_count == 0
    assert not capture.path.exists()
