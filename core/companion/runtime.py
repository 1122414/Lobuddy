"""Deep runtime module for observation and companion decisions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from core.companion.checkin import CompanionCheckInStore, InMemoryCompanionCheckInStore
from core.companion.models import (
    CompanionCheckIn,
    CompanionCheckInResult,
    CompanionEnergy,
    CompanionFeedbackAction,
    CompanionFeedbackResult,
    CompanionIntervention,
    CompanionMood,
    CompanionPollResult,
    CompanionPreferenceSummary,
    CompanionSupportMode,
    ObservationSnapshot,
    intervention_kind_label,
)
from core.companion.observation import (
    NullObservationAdapter,
    ObservationAdapter,
    create_system_observation_adapter,
)
from core.companion.policy import CompanionPolicy, InterventionHistory
from core.config import Settings
from core.storage.companion_event_repo import CompanionEventRepository
from core.storage.db import Database

logger = logging.getLogger(__name__)


class CompanionRuntime:
    """Expose one poll interface over observation, privacy, and policy state."""

    def __init__(
        self,
        settings: Settings,
        *,
        adapter: ObservationAdapter | None = None,
        history: InterventionHistory | None = None,
        checkins: CompanionCheckInStore | None = None,
        db: Database | None = None,
    ) -> None:
        self._settings = settings
        self._adapter = adapter or create_system_observation_adapter()
        self._history: InterventionHistory
        self._checkins: CompanionCheckInStore
        if history is None:
            repository = CompanionEventRepository(db)
            self._history = repository
            self._checkins = checkins or repository
        else:
            self._history = history
            self._checkins = checkins or InMemoryCompanionCheckInStore()
        self._private_checkins = InMemoryCompanionCheckInStore()
        self._policy = CompanionPolicy(settings, self._history)
        self._last_snapshot = ObservationSnapshot(available=False)

    @property
    def last_snapshot(self) -> ObservationSnapshot:
        return self._last_snapshot

    def update_settings(self, settings: Settings) -> None:
        """Update runtime and policy configuration in place."""
        self._settings = settings
        self._policy.update_settings(settings)

    def poll(
        self,
        *,
        privacy_active: bool = False,
        focus_active: bool = False,
        now: datetime | None = None,
    ) -> CompanionPollResult:
        now = now or datetime.now()
        if not self._settings.observation_enabled:
            snapshot = NullObservationAdapter().observe()
        else:
            try:
                snapshot = self._adapter.observe().model_copy(update={"observed_at": now})
            except Exception as exc:
                logger.debug("Observation adapter failed: %s", exc)
                snapshot = ObservationSnapshot(observed_at=now, available=False)

        if privacy_active or not self._settings.observation_active_app_enabled:
            snapshot = snapshot.privacy_filtered()
        self._last_snapshot = snapshot
        check_in = self.active_check_in(now=now)
        intervention = self._policy.evaluate(
            snapshot,
            privacy_active=privacy_active,
            focus_active=focus_active,
            check_in=check_in,
            now=now,
        )
        return CompanionPollResult(
            snapshot=snapshot,
            intervention=intervention,
        )

    def startup_greeting(
        self,
        message: str,
        *,
        privacy_active: bool = False,
        now: datetime | None = None,
    ) -> CompanionIntervention | None:
        now = now or datetime.now()
        return self._policy.startup_greeting(
            message,
            privacy_active=privacy_active,
            check_in=self.active_check_in(now=now),
            now=now,
        )

    def record_task_outcome(
        self,
        success: bool,
        *,
        privacy_active: bool = False,
        focus_active: bool = False,
        now: datetime | None = None,
    ) -> CompanionIntervention | None:
        now = now or datetime.now()
        return self._policy.record_task_outcome(
            success,
            privacy_active=privacy_active,
            focus_active=focus_active,
            check_in=self.active_check_in(now=now),
            now=now,
        )

    def submit_check_in(
        self,
        mood: CompanionMood | str,
        energy: CompanionEnergy | str,
        support_mode: CompanionSupportMode | str,
        *,
        privacy_active: bool = False,
        now: datetime | None = None,
    ) -> CompanionCheckInResult:
        """Accept explicit state without deriving or retaining free-form emotion text."""
        now = now or datetime.now()
        check_in = CompanionCheckIn(
            mood=CompanionMood(mood),
            energy=CompanionEnergy(energy),
            support_mode=CompanionSupportMode(support_mode),
            created_at=now,
            expires_at=now + timedelta(minutes=self._settings.companion_checkin_duration_minutes),
        )
        if privacy_active:
            self._checkins.clear_check_in()
            stored = self._private_checkins.save_check_in(check_in)
            persisted = False
        else:
            self._private_checkins.clear_check_in()
            stored = self._checkins.save_check_in(check_in)
            persisted = True
        return CompanionCheckInResult(
            accepted=True,
            check_in=stored,
            intervention=self._policy.respond_to_check_in(stored, now=now),
            persisted=persisted,
        )

    def active_check_in(self, *, now: datetime | None = None) -> CompanionCheckIn | None:
        """Return ephemeral state first, then the minimal persisted state."""
        now = now or datetime.now()
        private = self._private_checkins.active_check_in(now)
        if private is not None:
            return private
        return self._checkins.active_check_in(now)

    def clear_check_in(self) -> int:
        """Revoke current state from both privacy and persistent adapters."""
        return self._private_checkins.clear_check_in() + self._checkins.clear_check_in()

    def submit_feedback(
        self,
        intervention_id: int,
        action: CompanionFeedbackAction | str,
        *,
        now: datetime | None = None,
    ) -> CompanionFeedbackResult:
        """Persist a user's explicit preference without storing observation content."""
        now = now or datetime.now()
        parsed_action = CompanionFeedbackAction(action)
        kind = self._history.record_feedback(intervention_id, parsed_action, now)
        if kind is None:
            return CompanionFeedbackResult(
                accepted=False,
                action=parsed_action,
                message="这条关怀记录已经失效，没有修改你的偏好。",
            )
        if parsed_action == CompanionFeedbackAction.HELPFUL:
            message = f"记住啦，“{intervention_kind_label(kind)}”对你有帮助。"
            snoozed_until = None
        elif parsed_action == CompanionFeedbackAction.LATER:
            snoozed_until = now.replace(microsecond=0) + timedelta(
                minutes=self._settings.companion_feedback_snooze_minutes
            )
            message = (
                f"好，我先安静 {self._settings.companion_feedback_snooze_minutes} 分钟，"
                "需要我时随时叫我。"
            )
        else:
            snoozed_until = None
            message = f"记住了，以后不再主动发送“{intervention_kind_label(kind)}”。"
        return CompanionFeedbackResult(
            accepted=True,
            action=parsed_action,
            kind=kind,
            message=message,
            snoozed_until=snoozed_until,
        )

    def feedback_summary(self, *, now: datetime | None = None) -> CompanionPreferenceSummary:
        """Return the explainable preference state used by settings and diagnostics."""
        summary = self._history.get_feedback_summary(
            self._settings.companion_feedback_snooze_minutes
        )
        now = now or datetime.now()
        if summary.snoozed_until is not None and summary.snoozed_until <= now:
            return summary.model_copy(update={"snoozed_until": None})
        return summary

    def clear_feedback_preferences(self) -> int:
        """Forget mute/snooze choices while retaining positive feedback history."""
        return self._history.clear_feedback_preferences()
