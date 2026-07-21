"""Tests for active observation and the proactive companion policy."""

from datetime import datetime, timedelta
from pathlib import Path

from core.companion.models import (
    ActivityCategory,
    CompanionFeedbackAction,
    CompanionPreferenceSummary,
    InterventionKind,
    ObservationSnapshot,
)
from core.companion.observation import (
    NullObservationAdapter,
    classify_application,
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


class _History:
    def __init__(self) -> None:
        self.events: list[tuple[InterventionKind, datetime]] = []
        self.feedback: dict[
            int, tuple[InterventionKind, CompanionFeedbackAction, datetime]
        ] = {}

    def record(self, kind: InterventionKind, created_at: datetime) -> int:
        self.events.append((kind, created_at))
        return len(self.events)

    def count_since(
        self,
        since: datetime,
        kind: InterventionKind | None = None,
    ) -> int:
        return sum(
            1
            for event_kind, created_at in self.events
            if created_at >= since and (kind is None or event_kind == kind)
        )

    def last_at(self, kind: InterventionKind | None = None) -> datetime | None:
        matches = [
            created_at
            for event_kind, created_at in self.events
            if kind is None or event_kind == kind
        ]
        return max(matches) if matches else None

    def record_feedback(
        self,
        intervention_id: int,
        action: CompanionFeedbackAction,
        created_at: datetime,
    ) -> InterventionKind | None:
        if intervention_id < 1 or intervention_id > len(self.events):
            return None
        kind = self.events[intervention_id - 1][0]
        self.feedback[intervention_id] = (kind, action, created_at)
        return kind

    def is_kind_muted(self, kind: InterventionKind) -> bool:
        return any(
            feedback_kind == kind and action == CompanionFeedbackAction.MUTE_KIND
            for feedback_kind, action, _created_at in self.feedback.values()
        )

    def snoozed_until(self, snooze_minutes: int) -> datetime | None:
        later = [
            created_at
            for _kind, action, created_at in self.feedback.values()
            if action == CompanionFeedbackAction.LATER
        ]
        return max(later) + timedelta(minutes=snooze_minutes) if later else None

    def get_feedback_summary(self, snooze_minutes: int) -> CompanionPreferenceSummary:
        values = list(self.feedback.values())
        return CompanionPreferenceSummary(
            helpful_count=sum(
                action == CompanionFeedbackAction.HELPFUL
                for _kind, action, _created_at in values
            ),
            later_count=sum(
                action == CompanionFeedbackAction.LATER
                for _kind, action, _created_at in values
            ),
            muted_kinds=sorted(
                {
                    kind
                    for kind, action, _created_at in values
                    if action == CompanionFeedbackAction.MUTE_KIND
                },
                key=lambda kind: kind.value,
            ),
            snoozed_until=self.snoozed_until(snooze_minutes),
        )

    def clear_feedback_preferences(self) -> int:
        removable = [
            event_id
            for event_id, (_kind, action, _created_at) in self.feedback.items()
            if action in {
                CompanionFeedbackAction.LATER,
                CompanionFeedbackAction.MUTE_KIND,
            }
        ]
        for event_id in removable:
            del self.feedback[event_id]
        return len(removable)


class TestObservation:
    def test_application_categories_are_semantic(self):
        assert classify_application("Code.exe") == ActivityCategory.DEVELOPMENT
        assert classify_application("msedge.exe") == ActivityCategory.BROWSER
        assert classify_application("WeChat.exe") == ActivityCategory.COMMUNICATION
        assert classify_application("unknown.exe") == ActivityCategory.UNKNOWN

    def test_null_adapter_reports_unavailable(self):
        assert NullObservationAdapter().observe().available is False

    def test_privacy_filters_application_identity(self):
        settings = _settings()
        runtime = CompanionRuntime(
            settings,
            adapter=_Adapter(
                [
                    ObservationSnapshot(
                        idle_seconds=5,
                        foreground_app="code",
                        activity_category=ActivityCategory.DEVELOPMENT,
                    )
                ]
            ),
            history=_History(),
        )

        result = runtime.poll(
            privacy_active=True,
            now=datetime(2026, 7, 18, 10),
        )

        assert result.snapshot.foreground_app == ""
        assert result.snapshot.activity_category == ActivityCategory.UNKNOWN
        assert result.intervention is None


class TestCompanionPolicy:
    def test_long_work_streak_produces_one_rest_intervention(self):
        start = datetime(2026, 7, 18, 10)
        history = _History()
        runtime = CompanionRuntime(
            _settings(companion_work_streak_minutes=50),
            adapter=_Adapter(
                [
                    ObservationSnapshot(idle_seconds=5),
                    ObservationSnapshot(idle_seconds=10),
                ]
            ),
            history=history,
        )

        assert runtime.poll(now=start).intervention is None
        result = runtime.poll(now=start + timedelta(minutes=51))

        assert result.intervention is not None
        assert result.intervention.kind == InterventionKind.REST
        assert result.intervention.event_id == 1
        assert "连续活跃" in result.intervention.reason
        assert len(history.events) == 1

    def test_return_after_idle_is_welcoming(self):
        start = datetime(2026, 7, 18, 10)
        runtime = CompanionRuntime(
            _settings(companion_return_idle_minutes=20),
            adapter=_Adapter(
                [
                    ObservationSnapshot(idle_seconds=25 * 60),
                    ObservationSnapshot(idle_seconds=5),
                ]
            ),
            history=_History(),
        )

        assert runtime.poll(now=start).intervention is None
        result = runtime.poll(now=start + timedelta(minutes=25))

        assert result.intervention is not None
        assert result.intervention.kind == InterventionKind.RETURNED
        assert "欢迎回来" in result.intervention.message

    def test_quiet_hours_and_focus_suppress_presence(self):
        start = datetime(2026, 7, 18, 1)
        runtime = CompanionRuntime(
            _settings(companion_work_streak_minutes=10),
            adapter=_Adapter(
                [
                    ObservationSnapshot(idle_seconds=0),
                    ObservationSnapshot(idle_seconds=0),
                ]
            ),
            history=_History(),
        )

        assert runtime.poll(now=start).intervention is None
        assert (
            runtime.poll(
                focus_active=True,
                now=start + timedelta(minutes=11),
            ).intervention
            is None
        )

    def test_task_failures_receive_support_then_recovery(self):
        start = datetime(2026, 7, 18, 10)
        runtime = CompanionRuntime(
            _settings(companion_min_intervention_interval_minutes=1),
            adapter=NullObservationAdapter(),
            history=_History(),
        )

        assert runtime.record_task_outcome(False, now=start) is None
        support = runtime.record_task_outcome(
            False,
            now=start + timedelta(minutes=1),
        )
        recovery = runtime.record_task_outcome(
            True,
            now=start + timedelta(minutes=2),
        )

        assert support is not None
        assert support.kind == InterventionKind.FAILURE_SUPPORT
        assert recovery is not None
        assert recovery.kind == InterventionKind.RECOVERY

    def test_daily_greeting_honors_configured_maximum(self):
        start = datetime(2026, 7, 18, 10)
        runtime = CompanionRuntime(
            _settings(daily_greeting_enabled=True, daily_greeting_max_per_day=1),
            adapter=NullObservationAdapter(),
            history=_History(),
        )

        assert runtime.startup_greeting("早上好", now=start) is not None
        assert (
            runtime.startup_greeting(
                "又见面啦",
                now=start + timedelta(hours=1),
            )
            is None
        )

    def test_later_feedback_snoozes_all_proactive_care(self):
        start = datetime(2026, 7, 18, 10)
        history = _History()
        runtime = CompanionRuntime(
            _settings(
                companion_work_streak_minutes=10,
                companion_min_intervention_interval_minutes=1,
                companion_feedback_snooze_minutes=60,
            ),
            adapter=_Adapter(
                [
                    ObservationSnapshot(idle_seconds=0),
                    ObservationSnapshot(idle_seconds=0),
                    ObservationSnapshot(idle_seconds=0),
                    ObservationSnapshot(idle_seconds=0),
                ]
            ),
            history=history,
        )

        assert runtime.poll(now=start).intervention is None
        first = runtime.poll(now=start + timedelta(minutes=11)).intervention
        assert first is not None and first.event_id is not None
        result = runtime.submit_feedback(
            first.event_id,
            CompanionFeedbackAction.LATER,
            now=start + timedelta(minutes=11),
        )

        assert result.accepted is True
        assert result.snoozed_until == start + timedelta(minutes=71)
        assert runtime.poll(now=start + timedelta(minutes=30)).intervention is None
        assert runtime.poll(now=start + timedelta(minutes=72)).intervention is not None

    def test_mute_feedback_suppresses_only_that_kind(self):
        start = datetime(2026, 7, 18, 10)
        history = _History()
        runtime = CompanionRuntime(
            _settings(companion_min_intervention_interval_minutes=1),
            adapter=NullObservationAdapter(),
            history=history,
        )

        runtime.record_task_outcome(False, now=start)
        support = runtime.record_task_outcome(False, now=start + timedelta(minutes=1))
        assert support is not None and support.event_id is not None
        result = runtime.submit_feedback(
            support.event_id,
            CompanionFeedbackAction.MUTE_KIND,
            now=start + timedelta(minutes=1),
        )
        runtime.record_task_outcome(False, now=start + timedelta(minutes=2))
        muted_support = runtime.record_task_outcome(False, now=start + timedelta(minutes=3))
        recovery = runtime.record_task_outcome(True, now=start + timedelta(minutes=4))

        assert result.accepted is True
        assert result.kind == InterventionKind.FAILURE_SUPPORT
        assert muted_support is None
        assert recovery is not None
        assert recovery.kind == InterventionKind.RECOVERY


class TestCompanionEventRepository:
    def test_persists_only_kind_and_time(self, tmp_path: Path):
        settings = _settings(data_dir=tmp_path / "data")
        repo = CompanionEventRepository(Database(settings))
        now = datetime(2026, 7, 18, 10)

        intervention_id = repo.record(InterventionKind.REST, now)

        assert repo.count_since(now.replace(hour=0)) == 1
        assert repo.count_since(now.replace(hour=0), InterventionKind.REST) == 1
        assert repo.last_at() == now
        with repo.db.get_connection() as conn:
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(companion_intervention)")
            }
        assert columns == {"id", "kind", "created_at"}
        assert intervention_id == 1

    def test_feedback_persists_preferences_without_observation_content(self, tmp_path: Path):
        settings = _settings(data_dir=tmp_path / "data")
        repo = CompanionEventRepository(Database(settings))
        now = datetime(2026, 7, 18, 10)
        intervention_id = repo.record(InterventionKind.REST, now)

        kind = repo.record_feedback(
            intervention_id,
            CompanionFeedbackAction.MUTE_KIND,
            now + timedelta(minutes=1),
        )
        summary = repo.get_feedback_summary(settings.companion_feedback_snooze_minutes)

        assert kind == InterventionKind.REST
        assert repo.is_kind_muted(InterventionKind.REST) is True
        assert summary.muted_kinds == [InterventionKind.REST]
        with repo.db.get_connection() as conn:
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(companion_feedback)")
            }
        assert columns == {"id", "intervention_id", "kind", "action", "created_at"}
        assert repo.clear_feedback_preferences() == 1
        assert repo.is_kind_muted(InterventionKind.REST) is False


def _settings(**overrides) -> Settings:
    values = {
        "llm_api_key": "test",
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
    }
    values.update(overrides)
    return Settings(**values)
