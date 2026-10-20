"""Owned local scheduler: no model calls during polling or deterministic reminders."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING

from core.service.delegation_protocol import DelegationChange
from core.service.jev_notifications import NotificationDecisions
from core.service.schedule_protocol import NotificationView
from core.storage.notification_repo import NotificationRepository
from core.storage.schedule_repo import ScheduleRepository

if TYPE_CHECKING:
    from core.service.application import ApplicationService
    from core.service.outcomes import Outcome
    from core.service.protocol import TurnState


class LocalScheduler:
    def __init__(self, service: ApplicationService) -> None:
        self.service = service
        self.notifications = NotificationRepository(service.delegation_repo.db)
        self.repo = ScheduleRepository(service.delegation_repo, self.notifications)
        self.notifications.valid = self.valid_notice
        self.suspended = False
        self.closed = False
        self.task: asyncio.Task[None] | None = None
        self.decisions = NotificationDecisions(
            service.settings,
            service.delegation_repo.db,
            self.notifications,
            self.quiet,
            lambda identity: service.delegation_repo.get(identity).spec.goal,
        )
        self.notifications.eligible = self.decisions.allowed

    def start(self) -> None:
        if not self.closed and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self._run())

    def quiet(self) -> bool:
        service = self.service
        voice = getattr(service, "voice", None)
        now = time.time()
        return bool(
            self.suspended
            or self.closed
            or service.focus.is_active
            or service.companionship.policy.do_not_disturb
            or voice
            and voice.view().state not in ("off", "error")
            or any(state.lane == "foreground" for state in service._states.values())
            or any(
                now - updated < 10 and (value.typing or value.conversation)
                for updated, value in service.companionship.activity.values()
            )
        )

    def valid_notice(self, notice: NotificationView) -> bool:
        if not notice.delegation_id or notice.reason != "reminder":
            return True
        value = self.service.delegation_repo.get(notice.delegation_id)
        return bool(
            value.status not in ("paused", "cancelled", "draft", "failed", "needs_review")
            and value.expires_at
            and time.time() < value.expires_at
        )

    async def _run(self) -> None:
        while not self.closed:
            if not self.suspended:
                try:
                    dispatches = self.repo.tick()
                    # Foreground conversation/voice takes precedence over unattended execution.
                    if not self.service._learning_busy():
                        for identity, revision, trigger in dispatches[:1]:
                            try:
                                value = self.service.delegation_repo.get(identity)
                                version = self.service.knowledge.workflows.active(value.spec.kind)
                                if any(node.kind == "model" for node in version.definition.nodes):
                                    self.service.delegation_repo.review(
                                        identity, "该工作流包含模型步骤，需要手动继续并计量"
                                    )
                                else:
                                    await self.service.delegations.run(
                                        trigger,
                                        DelegationChange(delegation_id=identity, revision=revision),
                                    )
                            except (ValueError, RuntimeError):
                                self.service.delegation_repo.review(
                                    identity, "调度条件已变化，未自动重试，请核对范围和授权"
                                )
                            finally:
                                self.repo.dispatched(trigger)
                except (ValueError, RuntimeError):
                    # Keep durable pending records; no model retry loop.
                    pass
            await asyncio.sleep(1)

    def finished(self, state: TurnState, outcome: Outcome) -> None:
        if state.lane != "background":
            return
        now = time.time()
        self.notifications.put(
            NotificationView(
                id="task-" + state.turn_id,
                reason="task_result",
                source_id=state.turn_id,
                delegation_id=state.delegation_id,
                text=f"{state.input_text[:80]}：{outcome.reason}",
                planned_at=now,
                created_at=now,
            )
        )
        if state.delegation_id:
            value = self.service.delegation_repo.get(state.delegation_id)
            if value.status == "completed":
                self.repo.event("completed-" + state.turn_id, "delegation_completed", value.id)
                if value.spec.repeat.frequency != "once":
                    with self.repo.db.transaction() as conn:
                        row = conn.execute(
                            "SELECT next_at FROM delegation_schedule WHERE id=?", (value.id,)
                        ).fetchone()
                        if row and row[0] is not None:
                            value.status, value.reason = (
                                "scheduled",
                                "本次结果已验证，等待下次约定时间",
                            )
                            self.repo._save(conn, value)

    async def power(self, suspended: bool) -> None:
        self.suspended = suspended
        if suspended:
            await self.decisions.stop()
            voice = getattr(self.service, "voice", None)
            if voice:
                await voice.stop()
            for state in list(self.service._states.values()):
                await self.service.cancel(state.turn_id)
            self.repo.release()

    async def close(self) -> None:
        self.closed = True
        await self.decisions.stop(close=True)
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        self.repo.release()
