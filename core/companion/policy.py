"""Rate-limited, non-intrusive companion policy."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from core.companion.models import (
    CompanionCheckIn,
    CompanionEnergy,
    CompanionFeedbackAction,
    CompanionIntervention,
    CompanionMood,
    CompanionPreferenceSummary,
    CompanionSupportMode,
    InterventionKind,
    ObservationSnapshot,
    companion_energy_label,
    companion_mood_label,
    companion_support_label,
)
from core.config import Settings


class InterventionHistory(Protocol):
    def record(self, kind: InterventionKind, created_at: datetime) -> int | None: ...

    def count_since(
        self,
        since: datetime,
        kind: InterventionKind | None = None,
    ) -> int: ...

    def last_at(self, kind: InterventionKind | None = None) -> datetime | None: ...

    def record_feedback(
        self,
        intervention_id: int,
        action: CompanionFeedbackAction,
        created_at: datetime,
    ) -> InterventionKind | None: ...

    def is_kind_muted(self, kind: InterventionKind) -> bool: ...

    def snoozed_until(self, snooze_minutes: int) -> datetime | None: ...

    def get_feedback_summary(self, snooze_minutes: int) -> CompanionPreferenceSummary: ...

    def clear_feedback_preferences(self) -> int: ...


class CompanionPolicy:
    """Turn semantic presence into a small number of supportive interventions."""

    def __init__(self, settings: Settings, history: InterventionHistory) -> None:
        self._settings = settings
        self._history = history
        self._previous_snapshot: ObservationSnapshot | None = None
        self._active_since: datetime | None = None
        self._consecutive_failures = 0

    def update_settings(self, settings: Settings) -> None:
        """Apply settings changes without discarding rate-limit history."""
        self._settings = settings

    def evaluate(
        self,
        snapshot: ObservationSnapshot,
        *,
        privacy_active: bool = False,
        focus_active: bool = False,
        check_in: CompanionCheckIn | None = None,
        now: datetime | None = None,
    ) -> CompanionIntervention | None:
        now = now or snapshot.observed_at
        if not self._settings.proactive_companion_enabled:
            return None
        if privacy_active:
            self._previous_snapshot = None
            self._active_since = None
            return None
        previous = self._previous_snapshot
        self._previous_snapshot = snapshot
        self._update_active_streak(snapshot, now)
        if not snapshot.available:
            return None
        if focus_active and self._settings.focus_mute_greeting:
            return None
        if self._wants_quiet(check_in, now):
            return None

        candidate = self._presence_candidate(snapshot, previous, now, check_in)
        if candidate is None or not self._can_emit(candidate.kind, now):
            return None
        return self._record(candidate, now)

    def startup_greeting(
        self,
        message: str,
        *,
        privacy_active: bool = False,
        check_in: CompanionCheckIn | None = None,
        now: datetime | None = None,
    ) -> CompanionIntervention | None:
        now = now or datetime.now()
        if (
            not message
            or not self._settings.daily_greeting_enabled
            or privacy_active
            or self._is_quiet_hour(now.hour)
            or self._wants_quiet(check_in, now)
        ):
            return None
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if not self._preference_allows(InterventionKind.GREETING, now):
            return None
        if (
            self._history.count_since(today, InterventionKind.GREETING)
            >= self._settings.daily_greeting_max_per_day
        ):
            return None
        return self._record(
            CompanionIntervention(
                kind=InterventionKind.GREETING,
                title="今天的问候",
                message=message,
                reason="这是今天第一次主动问候，不包含屏幕或输入内容。",
                duration_ms=4000,
                created_at=now,
            ),
            now,
        )

    def record_task_outcome(
        self,
        success: bool,
        *,
        privacy_active: bool = False,
        focus_active: bool = False,
        check_in: CompanionCheckIn | None = None,
        now: datetime | None = None,
    ) -> CompanionIntervention | None:
        now = now or datetime.now()
        previous_failures = self._consecutive_failures
        if success:
            self._consecutive_failures = 0
            if previous_failures < self._settings.companion_failure_support_threshold:
                return None
            candidate = CompanionIntervention(
                kind=InterventionKind.RECOVERY,
                title="一起跑通了",
                message=self._task_recovery_message(check_in, now),
                reason=f"连续 {previous_failures} 次没有完成后，这次任务已经成功。",
                created_at=now,
            )
        else:
            self._consecutive_failures += 1
            if self._consecutive_failures < self._settings.companion_failure_support_threshold:
                return None
            candidate = CompanionIntervention(
                kind=InterventionKind.FAILURE_SUPPORT,
                title="我在这儿",
                message=self._task_failure_message(check_in, now),
                reason=f"最近连续 {self._consecutive_failures} 次任务没有成功完成。",
                state_hint="error",
                created_at=now,
            )

        if privacy_active or (focus_active and self._settings.focus_mute_greeting):
            return None
        if self._wants_quiet(check_in, now):
            return None
        if not self._can_emit(candidate.kind, now):
            return None
        return self._record(candidate, now)

    def respond_to_check_in(
        self,
        check_in: CompanionCheckIn,
        *,
        now: datetime | None = None,
    ) -> CompanionIntervention:
        """Respond to explicit user state without counting it as proactive care."""
        now = now or datetime.now()
        mood = companion_mood_label(check_in.mood)
        energy = companion_energy_label(check_in.energy)
        support = companion_support_label(check_in.support_mode)
        message_by_support = {
            CompanionSupportMode.LISTEN: (
                "我在。你可以从最想说的那一句开始，不必先把情绪整理得很完整。"
            ),
            CompanionSupportMode.ENCOURAGE: self._encouragement_message(check_in),
            CompanionSupportMode.FOCUS: (
                "收到。我们先只照顾眼前这一小步；需要时点“专注陪伴”，我会安静守着。"
            ),
            CompanionSupportMode.PRACTICAL: (
                "交给我一起理。把眼前最卡的事情告诉我，我会先拆出一个可验证的小步骤。"
            ),
            CompanionSupportMode.QUIET: (
                "好，我先不主动打扰。你需要我时点一下宠物，我一直在这里。"
            ),
        }
        return CompanionIntervention(
            kind=InterventionKind.CHECK_IN,
            title=self._check_in_title(check_in.support_mode),
            message=message_by_support[check_in.support_mode],
            reason=(
                f"根据你刚刚主动选择的“{mood} · {energy} · {support}”回应，"
                "不是从应用活动推断。"
            ),
            state_hint=self._check_in_state_hint(check_in),
            duration_ms=6500,
            created_at=now,
        )

    def _presence_candidate(
        self,
        snapshot: ObservationSnapshot,
        previous: ObservationSnapshot | None,
        now: datetime,
        check_in: CompanionCheckIn | None,
    ) -> CompanionIntervention | None:
        returned_threshold = self._settings.companion_return_idle_minutes * 60
        if (
            previous is not None
            and previous.idle_seconds >= returned_threshold
            and snapshot.idle_seconds < 60
        ):
            return CompanionIntervention(
                kind=InterventionKind.RETURNED,
                title="欢迎回来",
                message="欢迎回来～不用急着一下子进入状态，我陪你慢慢来。",
                reason=f"检测到你离开约 {max(1, int(previous.idle_seconds / 60))} 分钟后回来。",
                created_at=now,
            )

        if now.hour >= self._settings.companion_late_night_hour:
            return CompanionIntervention(
                kind=InterventionKind.LATE_NIGHT,
                title="夜深了",
                message="已经很晚啦。手上的事可以先收个尾，明天的你也值得有精神。",
                reason=f"现在已经是 {now.hour:02d} 点后的晚间时段。",
                duration_ms=5500,
                created_at=now,
            )

        if self._is_quiet_hour(now.hour):
            return None

        if self._active_since is not None:
            active_for = now - self._active_since
            if active_for >= timedelta(minutes=self._settings.companion_work_streak_minutes):
                message = "已经专注很久啦，活动一下肩颈、喝口水吧。回来我继续陪你。"
                reason = (
                    "检测到你已连续活跃约 "
                    f"{max(1, int(active_for.total_seconds() / 60))} 分钟。"
                )
                if self._is_low_energy(check_in, now):
                    message = "你刚刚说电量不多，又连续忙了一阵。先停两分钟，我替你守住节奏。"
                    reason += " 休息建议也参考了你主动提交的低能量状态。"
                return CompanionIntervention(
                    kind=InterventionKind.REST,
                    title="休息一下",
                    message=message,
                    reason=reason,
                    duration_ms=5500,
                    created_at=now,
                )
        return None

    def _update_active_streak(
        self,
        snapshot: ObservationSnapshot,
        now: datetime,
    ) -> None:
        reset_seconds = self._settings.companion_activity_reset_idle_minutes * 60
        if not snapshot.available or snapshot.idle_seconds >= reset_seconds:
            self._active_since = None
            return
        if self._active_since is None:
            self._active_since = now

    def _can_emit(self, kind: InterventionKind, now: datetime) -> bool:
        if not self._preference_allows(kind, now):
            return False
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if self._history.count_since(today) >= self._settings.companion_max_interventions_per_day:
            return False
        last = self._history.last_at()
        if last is not None and now - last < timedelta(
            minutes=self._settings.companion_min_intervention_interval_minutes
        ):
            return False
        if kind == InterventionKind.LATE_NIGHT:
            return self._history.count_since(today, kind) == 0
        return True

    def _record(
        self,
        intervention: CompanionIntervention,
        now: datetime,
    ) -> CompanionIntervention:
        event_id = self._history.record(intervention.kind, now)
        if intervention.kind == InterventionKind.REST:
            self._active_since = now
        return intervention.model_copy(update={"event_id": event_id, "created_at": now})

    def _preference_allows(self, kind: InterventionKind, now: datetime) -> bool:
        if self._history.is_kind_muted(kind):
            return False
        snoozed_until = self._history.snoozed_until(
            self._settings.companion_feedback_snooze_minutes
        )
        return snoozed_until is None or now >= snoozed_until

    def _is_quiet_hour(self, hour: int) -> bool:
        start = self._settings.companion_quiet_start_hour
        end = self._settings.companion_quiet_end_hour
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    @staticmethod
    def _is_active_check_in(
        check_in: CompanionCheckIn | None,
        now: datetime,
    ) -> bool:
        return check_in is not None and check_in.is_active(now)

    def _wants_quiet(
        self,
        check_in: CompanionCheckIn | None,
        now: datetime,
    ) -> bool:
        return bool(
            self._is_active_check_in(check_in, now)
            and check_in is not None
            and check_in.support_mode == CompanionSupportMode.QUIET
        )

    def _is_low_energy(
        self,
        check_in: CompanionCheckIn | None,
        now: datetime,
    ) -> bool:
        return bool(
            self._is_active_check_in(check_in, now)
            and check_in is not None
            and (
                check_in.energy == CompanionEnergy.LOW
                or check_in.mood in {CompanionMood.TIRED, CompanionMood.LOW}
            )
        )

    def _task_failure_message(
        self,
        check_in: CompanionCheckIn | None,
        now: datetime,
    ) -> str:
        if (
            self._is_active_check_in(check_in, now)
            and check_in is not None
            and check_in.support_mode == CompanionSupportMode.PRACTICAL
        ):
            return "这条路还没跑通。我先保留现有证据，再换成一个更小、可验证的步骤。"
        if self._is_low_energy(check_in, now):
            return "这次没跑通不是你的负担。我会缩小问题，一步一步继续找路。"
        return "连续两次没跑通确实不轻松。先别把责任揽到自己身上，我会换一条路继续试。"

    def _task_recovery_message(
        self,
        check_in: CompanionCheckIn | None,
        now: datetime,
    ) -> str:
        if self._is_low_energy(check_in, now):
            return "这次跑通啦。你不用再硬撑这一段，剩下的收尾交给我一起看。"
        return "这次跑通啦。刚才的卡住没有白费，我们一起把路找到了。"

    @staticmethod
    def _check_in_title(support_mode: CompanionSupportMode) -> str:
        return {
            CompanionSupportMode.LISTEN: "我在听",
            CompanionSupportMode.ENCOURAGE: "给你一点底气",
            CompanionSupportMode.FOCUS: "一起守住这一小步",
            CompanionSupportMode.PRACTICAL: "我们来理一理",
            CompanionSupportMode.QUIET: "安静陪着你",
        }[support_mode]

    @staticmethod
    def _check_in_state_hint(check_in: CompanionCheckIn) -> str:
        if check_in.support_mode == CompanionSupportMode.LISTEN:
            return "listening"
        if check_in.mood == CompanionMood.TIRED or check_in.energy == CompanionEnergy.LOW:
            return "sleepy"
        return "happy"

    @staticmethod
    def _encouragement_message(check_in: CompanionCheckIn) -> str:
        if check_in.mood == CompanionMood.TIRED or check_in.energy == CompanionEnergy.LOW:
            return "累了也不用硬撑。今天能走到这里已经很好，我们只做最值得做的那一小步。"
        if check_in.mood == CompanionMood.TENSE:
            return "先松一点肩膀。事情可以一件件来，你不需要同时扛住全部。"
        if check_in.mood == CompanionMood.LOW:
            return "今天不用表现得很好。你愿意告诉我现在的状态，本身就是在照顾自己。"
        if check_in.mood == CompanionMood.GOOD:
            return "这份好状态很珍贵。我们顺着它走，但也不用把今天塞得太满。"
        return "你不需要一下子准备好。先迈出一个很小的动作，我会跟上。"
