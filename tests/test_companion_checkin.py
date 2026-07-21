"""Tests for explicit, expiring, privacy-minimized Companion Check-ins."""

from datetime import datetime, timedelta
from pathlib import Path

from core.companion.models import (
    CompanionCheckIn,
    CompanionEnergy,
    CompanionMood,
    CompanionSupportMode,
    InterventionKind,
    ObservationSnapshot,
)
from core.companion.runtime import CompanionRuntime
from core.config import Settings
from core.storage.companion_event_repo import CompanionEventRepository
from core.storage.db import Database


class _Adapter:
    def __init__(self, snapshots: list[ObservationSnapshot]) -> None:
        self._snapshots = iter(snapshots)

    def observe(self) -> ObservationSnapshot:
        return next(self._snapshots)


class TestCompanionCheckInRuntime:
    """User-authored state is a separate input from desktop observation."""

    def test_check_in_returns_explainable_user_initiated_response(self, tmp_path: Path):
        now = datetime(2026, 7, 19, 10)
        settings = _settings(tmp_path)
        runtime = CompanionRuntime(settings, db=Database(settings))

        result = runtime.submit_check_in(
            CompanionMood.TIRED,
            CompanionEnergy.LOW,
            CompanionSupportMode.ENCOURAGE,
            now=now,
        )

        assert result.accepted is True
        assert result.persisted is True
        assert result.intervention.kind == InterventionKind.CHECK_IN
        assert result.intervention.event_id is None
        assert "主动选择" in result.intervention.reason
        assert "不是从应用活动推断" in result.intervention.reason
        assert result.check_in.expires_at == now + timedelta(minutes=120)

    def test_privacy_mode_keeps_check_in_in_memory_only(self, tmp_path: Path):
        now = datetime(2026, 7, 19, 10)
        settings = _settings(tmp_path)
        db = Database(settings)
        runtime = CompanionRuntime(settings, db=db)

        result = runtime.submit_check_in(
            "steady",
            "medium",
            "listen",
            privacy_active=True,
            now=now,
        )

        assert result.persisted is False
        assert runtime.active_check_in(now=now) == result.check_in
        with db.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM companion_checkin").fetchone()[0] == 0

    def test_quiet_support_revokes_proactive_interruptions(self, tmp_path: Path):
        now = datetime(2026, 7, 19, 10)
        settings = _settings(tmp_path, companion_work_streak_minutes=10)
        runtime = CompanionRuntime(
            settings,
            adapter=_Adapter(
                [
                    ObservationSnapshot(idle_seconds=0),
                    ObservationSnapshot(idle_seconds=0),
                ]
            ),
            db=Database(settings),
        )
        runtime.submit_check_in("steady", "medium", "quiet", now=now)

        assert runtime.poll(now=now).intervention is None
        assert runtime.poll(now=now + timedelta(minutes=11)).intervention is None
        assert runtime.record_task_outcome(False, now=now + timedelta(minutes=12)) is None
        assert runtime.record_task_outcome(False, now=now + timedelta(minutes=13)) is None

    def test_low_energy_state_changes_rest_tone_without_emotion_inference(self, tmp_path: Path):
        now = datetime(2026, 7, 19, 10)
        settings = _settings(
            tmp_path,
            companion_work_streak_minutes=10,
            companion_min_intervention_interval_minutes=1,
        )
        runtime = CompanionRuntime(
            settings,
            adapter=_Adapter(
                [
                    ObservationSnapshot(idle_seconds=0),
                    ObservationSnapshot(idle_seconds=0),
                ]
            ),
            db=Database(settings),
        )
        runtime.submit_check_in("tired", "low", "encourage", now=now)

        assert runtime.poll(now=now).intervention is None
        rest = runtime.poll(now=now + timedelta(minutes=11)).intervention

        assert rest is not None
        assert rest.kind == InterventionKind.REST
        assert "你刚刚说电量不多" in rest.message
        assert "主动提交" in rest.reason

    def test_clear_revokes_current_state_immediately(self, tmp_path: Path):
        now = datetime(2026, 7, 19, 10)
        settings = _settings(tmp_path)
        runtime = CompanionRuntime(settings, db=Database(settings))
        runtime.submit_check_in("good", "high", "encourage", now=now)

        assert runtime.clear_check_in() == 1
        assert runtime.active_check_in(now=now) is None


class TestCompanionCheckInRepository:
    """Persistence keeps one current enum-only state, not a mood history."""

    def test_schema_contains_no_note_or_observation_content(self, tmp_path: Path):
        settings = _settings(tmp_path)
        repo = CompanionEventRepository(Database(settings))
        now = datetime(2026, 7, 19, 10)
        first = _submit(repo, now, mood=CompanionMood.STEADY)
        second = _submit(repo, now + timedelta(minutes=1), mood=CompanionMood.GOOD)

        with repo.db.get_connection() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(companion_checkin)")}
            rows = conn.execute("SELECT COUNT(*) FROM companion_checkin").fetchone()[0]

        assert columns == {
            "id",
            "mood",
            "energy",
            "support_mode",
            "created_at",
            "expires_at",
        }
        assert rows == 1
        assert first.id == 1
        assert second.id == 2
        assert repo.active_check_in(now + timedelta(minutes=1)).mood == CompanionMood.GOOD

    def test_expired_state_is_deleted_on_read(self, tmp_path: Path):
        settings = _settings(tmp_path)
        repo = CompanionEventRepository(Database(settings))
        now = datetime(2026, 7, 19, 10)
        _submit(repo, now, duration_minutes=15)

        assert repo.active_check_in(now + timedelta(minutes=15)) is None
        with repo.db.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM companion_checkin").fetchone()[0] == 0


def _submit(
    repo: CompanionEventRepository,
    now: datetime,
    *,
    mood: CompanionMood = CompanionMood.STEADY,
    duration_minutes: int = 120,
):
    return repo.save_check_in(
        CompanionCheckIn(
            mood=mood,
            energy=CompanionEnergy.MEDIUM,
            support_mode=CompanionSupportMode.ENCOURAGE,
            created_at=now,
            expires_at=now + timedelta(minutes=duration_minutes),
        )
    )


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "llm_api_key": "test",
        "data_dir": tmp_path / "data",
        "daily_greeting_enabled": False,
        "proactive_companion_enabled": True,
        "observation_enabled": True,
        "observation_active_app_enabled": True,
        "companion_min_intervention_interval_minutes": 30,
        "companion_max_interventions_per_day": 4,
        "companion_work_streak_minutes": 50,
        "companion_return_idle_minutes": 20,
        "companion_activity_reset_idle_minutes": 5,
        "companion_quiet_start_hour": 0,
        "companion_quiet_end_hour": 7,
        "companion_late_night_hour": 23,
        "companion_failure_support_threshold": 2,
        "companion_feedback_snooze_minutes": 60,
        "companion_checkin_duration_minutes": 120,
    }
    values.update(overrides)
    return Settings(**values)
