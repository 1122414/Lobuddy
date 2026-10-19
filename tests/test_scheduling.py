"""PA-01/03 deterministic time, delivery, ownership and missed-trigger acceptance."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from core.config import Settings
from core.service.delegation_protocol import DelegationChange, DelegationConfirm, DelegationSpec
from core.service.schedule_protocol import NotificationView
from core.service.schedule_rules import RepeatRule, next_occurrence
from core.storage.chat_repo import ChatRepository
from core.storage.db import Database
from core.storage.delegation_repo import DelegationRepository
from core.storage.notification_repo import NotificationRepository
from core.storage.schedule_repo import ScheduleRepository


def stamp(value):
    return datetime.fromisoformat(value).timestamp()


@pytest.fixture
def system(tmp_path):
    settings = Settings(
        llm_api_key="synthetic", data_dir=tmp_path / "data", workspace_path=tmp_path
    )
    db = Database(settings)
    db.init_database(allow_desktop=True)
    ChatRepository(db)
    now = [1000.0]
    repo = DelegationRepository(db, lambda: now[0])
    notices = NotificationRepository(db, lambda: now[0])
    return now, repo, notices, ScheduleRepository(repo, notices, lambda: now[0])


def reminder(system, *, at=1010.0, repeat=None, identity="create", wait=None):
    _, repo, _, _ = system
    spec = DelegationSpec.model_validate(
        {
            "goal": "周五接着看项目",
            "kind": "reminder",
            "criteria": ["通知按规则投递（不代表已读）"],
            "wait": wait or {"kind": "time", "at": at, "timezone": "Asia/Shanghai"},
            "repeat": repeat or {},
        }
    )
    value = repo.create(identity, spec)
    return repo.change(
        "confirm-" + identity,
        "confirm",
        DelegationConfirm(delegation_id=value.id, revision=1, expires_at=10000000.0),
    )


class TestCalendarRules:
    @pytest.mark.parametrize(
        "frequency,after,expected",
        [
            ("daily", "2026-03-08T00:00:00-05:00", "2026-03-09T02:30:00-04:00"),
            ("daily", "2026-03-07T02:30:00-05:00", "2026-03-09T02:30:00-04:00"),
            ("weekly", "2026-03-07T00:00:00-05:00", "2026-03-15T02:30:00-04:00"),
        ],
    )
    def test_dst_gap_skips_impossible_wall_time(self, frequency, after, expected):
        rule = RepeatRule(
            frequency=frequency, local_time="02:30", weekdays=[6] if frequency == "weekly" else []
        )
        assert next_occurrence(rule, "America/New_York", stamp(after)) == stamp(expected)

    def test_repeated_hour_uses_first_fold_only(self):
        rule = RepeatRule(frequency="daily", local_time="01:30")
        first = next_occurrence(rule, "America/New_York", stamp("2026-11-01T00:00:00-04:00"))
        assert first == stamp("2026-11-01T01:30:00-04:00")
        assert next_occurrence(rule, "America/New_York", first) == stamp(
            "2026-11-02T01:30:00-05:00"
        )

    def test_weekly_end_date_and_explicit_zone(self):
        rule = RepeatRule(
            frequency="weekly",
            local_time="20:00",
            weekdays=[4],
            end_at=stamp("2026-10-23T21:00:00+08:00"),
        )
        value = next_occurrence(rule, "Asia/Shanghai", stamp("2026-10-19T12:00:00+00:00"))
        assert value == stamp("2026-10-23T20:00:00+08:00")
        assert next_occurrence(rule, "Asia/Shanghai", value) is None
        assert next_occurrence(RepeatRule(), "Asia/Shanghai", value) is None

    @pytest.mark.parametrize(
        "bad",
        [
            {"frequency": "cron"},
            {"frequency": "daily"},
            {"frequency": "daily", "local_time": "25:00"},
            {"frequency": "weekly", "local_time": "09:00"},
            {"frequency": "weekly", "local_time": "09:00", "weekdays": [7]},
            {"frequency": "weekly", "local_time": "09:00", "weekdays": [1, 1]},
            {"frequency": "once", "weekdays": [1]},
            {"end_at": float("inf")},
        ],
    )
    def test_invalid_rules_rejected(self, bad):
        with pytest.raises(ValidationError):
            RepeatRule.model_validate(bad)


class TestPersistentScheduling:
    def test_due_commits_once_and_completion_waits_for_delivery(self, system):
        now, repo, notices, scheduler = system
        value = reminder(system)
        scheduler.tick()
        assert notices.list() == []
        now[0] = 1010
        scheduler.tick()
        scheduler.tick()
        assert len(notices.list()) == 1 and repo.get(value.id).status == "waiting_user"
        assert notices.next(quiet=True) is None
        batch = notices.next(quiet=False)
        assert batch
        assert not notices.displayed(batch.batch_id, quiet=True)
        assert notices.displayed(batch.batch_id, quiet=False)
        scheduler.complete_deliveries()
        scheduler.complete_deliveries()
        assert repo.get(value.id).status == "completed"
        assert repo.detail(value.id).runs[0].verdict == "verified"
        notice = notices.list()[0]
        assert notice.delivered_at == 1010 and notice.read_at is None
        assert notices.read(notice.id).read_at == 1010
        assert notices.next(quiet=False) is None

    @pytest.mark.parametrize(
        "delay,status", [(86400, "pending"), (86401, "missed"), (30, "pending")]
    )
    def test_one_shot_missed_boundary(self, system, delay, status):
        now, _, notices, scheduler = system
        reminder(system)
        now[0] = 1010 + delay
        scheduler.tick()
        assert notices.list()[0].status == status

    def test_periodic_missed_occurrences_coalesce_and_restart_deduplicates(self, system):
        now, repo, notices, scheduler = system
        value = reminder(system, at=3600.0, repeat={"frequency": "daily", "local_time": "09:00"})
        now[0] = 1010 + 3 * 86400
        scheduler.tick()
        assert len(notices.list()) == 1 and notices.list()[0].status == "pending"
        future = scheduler.view(value.id).next_at
        assert future > now[0]
        scheduler.release()
        replacement = ScheduleRepository(repo, notices, lambda: now[0])
        replacement.tick()
        assert len(notices.list()) == 1 and replacement.view(value.id).next_at == future

    def test_two_owners_and_expiring_lease_do_not_duplicate(self, system):
        now, repo, notices, first = system
        reminder(system)
        first.tick()
        second = ScheduleRepository(repo, notices, lambda: now[0])
        now[0] = 1009
        second.tick()
        assert not notices.list()
        now[0] = 1011
        second.tick()
        first.tick()
        assert len(notices.list()) == 1

    def test_pause_resume_and_cancel_before_due(self, system):
        now, repo, notices, scheduler = system
        value = reminder(system)
        scheduler.tick()
        repo.change("pause", "pause", DelegationChange(delegation_id=value.id, revision=2))
        now[0] = 1020
        scheduler.tick()
        assert not notices.list()
        resumed = repo.change(
            "resume", "resume", DelegationChange(delegation_id=value.id, revision=3)
        )
        repo.change(
            "cancel", "cancel", DelegationChange(delegation_id=value.id, revision=resumed.revision)
        )
        scheduler.tick()
        assert not notices.list() and repo.get(value.id).status == "cancelled"

    def test_authority_expiry_does_not_execute(self, system):
        now, repo, notices, scheduler = system
        value = reminder(system)
        now[0] = 10000001
        scheduler.tick()
        assert not notices.list() and repo.get(value.id).status == "needs_review"

    def test_internal_event_dedup_and_subject_filter(self, system):
        _now, repo, notices, scheduler = system
        value = reminder(
            system,
            wait={"kind": "event", "event": "delegation_completed", "subject_id": "project-work"},
        )
        scheduler.event("wrong", "delegation_completed", "unrelated")
        scheduler.tick()
        assert not notices.list()
        scheduler.event("right", "delegation_completed", "project-work")
        scheduler.event("right", "delegation_completed", "project-work")
        scheduler.tick()
        scheduler.tick()
        assert len(notices.list()) == 1
        assert repo.detail(value.id).runs[0].trigger_id.endswith("right")

    def test_write_schedule_never_automatically_replays(self, system):
        now, repo, notices, scheduler = system
        spec = DelegationSpec(
            goal="整理副本",
            kind="organize-files",
            source_directory="in",
            output_directory="out",
            criteria=["副本数量和内容校验通过，原文件保留"],
            wait={"kind": "time", "at": 1010.0},
        )
        value = repo.create("file", spec)
        repo.change(
            "confirm",
            "confirm",
            DelegationConfirm(delegation_id=value.id, revision=1, expires_at=2000.0),
        )
        now[0] = 1010
        assert scheduler.tick() == []
        assert repo.get(value.id).status == "needs_review" and not notices.list()


class TestInbox:
    def test_suppressed_notifications_are_batched_then_acknowledged_once(self, system):
        now, _, notices, _ = system
        for i in range(3):
            notices.put(
                NotificationView(
                    id=str(i),
                    reason="task_result",
                    source_id=str(i),
                    text="结果",
                    planned_at=now[0],
                    created_at=now[0],
                )
            )
        assert notices.next(quiet=True) is None
        batch = notices.next(quiet=False)
        assert batch.count == 3
        assert notices.next(quiet=False) is None
        assert notices.displayed(batch.batch_id, quiet=False)
        assert notices.displayed(batch.batch_id, quiet=False)
        assert notices.next(quiet=False) is None

    def test_crash_before_display_releases_lease_but_not_read_receipt(self, system):
        now, _, notices, _ = system
        notices.put(
            NotificationView(
                id="n",
                reason="reminder",
                source_id="s",
                text="提醒",
                planned_at=now[0],
                created_at=now[0],
            )
        )
        first = notices.next(quiet=False)
        now[0] += 16
        second = notices.next(quiet=False)
        assert first.batch_id != second.batch_id and notices.list()[0].read_at is None
        assert not notices.displayed(first.batch_id, quiet=False)

    def test_revoked_scope_cannot_ack_a_leased_notice(self, system):
        now, _, notices, _ = system
        notices.put(
            NotificationView(
                id="n",
                reason="reminder",
                source_id="s",
                text="提醒",
                planned_at=now[0],
                created_at=now[0],
            )
        )
        batch = notices.next(quiet=False)
        notices.valid = lambda notice: False
        assert not notices.displayed(batch.batch_id, quiet=False)

    def test_clock_moves_back_without_duplicate_delivery(self, system):
        now, _, notices, scheduler = system
        reminder(system)
        now[0] = 1010
        scheduler.tick()
        batch = notices.next(quiet=False)
        notices.displayed(batch.batch_id, quiet=False)
        scheduler.complete_deliveries()
        now[0] = 900
        scheduler.tick()
        now[0] = 1010
        scheduler.tick()
        assert len(notices.list()) == 1 and notices.next(quiet=False) is None


def test_final_periodic_occurrence_missed_does_not_wait_forever(system):
    now, repo, notices, scheduler = system
    value = reminder(
        system,
        at=3600.0,
        repeat={"frequency": "daily", "local_time": "09:00", "catch_up": False, "end_at": 4000.0},
    )
    now[0] = 5000
    scheduler.tick()
    assert notices.list()[0].status == "missed"
    assert repo.get(value.id).status == "needs_review"
    assert scheduler.view(value.id).next_at is None
