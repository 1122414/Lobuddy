"""Optional advisory notification timing; hard delivery rules always run first."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from collections.abc import Callable

from core.agent.jev import JevClient, JevContext, JevUnavailable, request_body
from core.config import Settings
from core.memory.memory_service import _sanitize_memory_text
from core.service.jev_protocol import JevDecision, JevStatus
from core.service.relationship import SECRETS, SENSITIVE
from core.service.schedule_protocol import NotificationView
from core.storage.db import Database
from core.storage.jev_repo import JevRepository
from core.storage.notification_repo import NotificationRepository


class NotificationDecisions:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        notifications: NotificationRepository,
        quiet: Callable[[], bool],
        goal: Callable[[str], str],
        *,
        client: JevClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings, self.notifications = settings, notifications
        self.repo, self.client = JevRepository(db), client or JevClient()
        self.quiet, self.goal, self.clock = quiet, goal, clock
        self.task: asyncio.Task[None] | None = None
        self.closed = False
        self.generation = 0

    def configure(self, settings: Settings) -> None:
        self.settings = settings
        self.generation += 1
        if self.task and not self.task.done():
            self.task.cancel()

    def enabled(self) -> bool:
        return self.settings.jev_mode != "off" and bool(self.settings.typesafe_api_key)

    def allowed(self, notice: NotificationView) -> bool:
        if (
            not self.enabled()
            or self.settings.jev_mode != "active"
            or notice.reason != "task_result"
        ):
            return True
        value = self.repo.get(notice.id)
        if value is None:
            return False
        # Observations collected in shadow mode never become active decisions retroactively.
        if value.mode == "shadow":
            return True
        return value.status != "running" and (
            value.action == "notify" or value.action == "defer" and self.clock() >= value.not_before
        )

    def context(self, notice: NotificationView) -> JevContext:
        goal = self.goal(notice.delegation_id) if notice.delegation_id else ""
        # Only the same explicit delegation; never borrow another project's history.
        recent = [
            item.text[:300]
            for item in self.notifications.list()
            if notice.delegation_id
            and item.delegation_id == notice.delegation_id
            and item.id != notice.id
            and item.status in ("delivered", "read")
            and item.delivered_at is not None
            and self.clock() - item.delivered_at < 86400
            and self.notifications.valid(item)
        ][:3]
        text = "\n".join([notice.text, goal, *recent])
        configured_secrets = (
            self.settings.llm_api_key,
            self.settings.llm_multimodal_api_key,
            self.settings.fish_api_key,
            self.settings.typesafe_api_key,
        )
        if (
            _sanitize_memory_text(text) != text.strip()
            or SECRETS.search(text)
            or SENSITIVE.search(text)
            or any(secret and len(secret) >= 6 and secret in text for secret in configured_secrets)
        ):
            raise ValueError("Private context is not eligible for Jev")
        return JevContext(notification=notice.text[:600], goal=goal[:600], recent_delivered=recent)

    def poll(self) -> None:
        if (
            self.closed
            or not self.enabled()
            or self.quiet()
            or self.task is not None
            and not self.task.done()
        ):
            return
        for item in self.notifications.pending():
            if (
                item.reason == "task_result"
                and self.notifications.valid(item)
                and self.repo.get(item.id) is None
            ):
                self.task = asyncio.create_task(self._decide(item))
                break

    async def _decide(self, notice: NotificationView) -> None:
        now, started, generation = self.clock(), time.monotonic(), self.generation
        mode = self.settings.jev_mode
        if mode == "off":
            return
        value = JevDecision(
            reason="正在判断；暂存收件箱",
            mode=mode,
            status="running",
            created_at=now,
            not_before=now + 600,
        )
        try:
            body = request_body(self.context(notice), self.settings.jev_model)
        except ValueError:
            value.status, value.reason = "fallback", "内容不适合发送给 Jev，延后合并"
            self.repo.reserve(notice.id, "", value, 0, 0, 0)
            # This is not a budget denial and does not consume a call.
            value.reason = "内容不适合发送给 Jev，延后合并"
            self.repo.finish(notice.id, value)
            return
        digest = hashlib.sha256(body).hexdigest()
        if not self.repo.reserve(
            notice.id,
            digest,
            value,
            len(body),
            self.settings.jev_daily_calls,
            self.settings.jev_daily_request_bytes,
        ):
            return
        try:
            result = await self.client.decide(body, self.settings.typesafe_api_key)
            current = self.notifications.get(notice.id)
            if (
                self.closed
                or generation != self.generation
                or self.quiet()
                or current is None
                or current.status in ("cancelled", "missed", "read")
                or not self.notifications.valid(current)
                or hashlib.sha256(
                    request_body(self.context(current), self.settings.jev_model)
                ).hexdigest()
                != digest
            ):
                value.status, value.reason = "stale", "判断期间状态或来源已变化，延后合并"
            else:
                value.model, value.answers = result.model, result.answers
                value.status = "decided"
                answers = result.answers
                threshold = self.settings.jev_min_confidence
                if (
                    answers.duplicate.choice == "yes"
                    and answers.duplicate.confidence >= threshold
                    or answers.relevant.choice == "no"
                    and answers.relevant.confidence >= threshold
                ):
                    value.action, value.reason = "quiet", "内容重复或与当前委托无关，仅留收件箱"
                elif any(
                    answer.confidence < self.settings.jev_min_confidence
                    or answer.choice == "unknown"
                    for answer in (answers.relevant, answers.time_sensitive, answers.duplicate)
                ):
                    value.reason = "判断不确定，延后合并"
                elif answers.time_sensitive.choice == "yes":
                    value.action, value.reason = "notify", "与委托相关且有时效性，允许提示"
                else:
                    value.reason = "没有明确时效性，延后十分钟合并"
            value.input_tokens = result.usage.input_tokens
            value.output_tokens = result.usage.output_tokens
        except asyncio.CancelledError:
            value.status, value.reason = "interrupted", "判断已取消，未自动重试"
            raise
        except JevUnavailable as error:
            value.status, value.reason = "fallback", f"Jev 暂不可用（{error}），延后合并"
        except ValueError:
            value.status, value.reason = "stale", "来源已失效，延后合并"
        finally:
            value.elapsed_ms = round((time.monotonic() - started) * 1000, 2)
            self.repo.finish(notice.id, value)

    def view(self) -> JevStatus:
        calls, size = self.repo.usage(self.clock())
        return JevStatus(
            mode=self.settings.jev_mode,
            configured=bool(self.settings.typesafe_api_key),
            model=self.settings.jev_model,
            calls_today=calls,
            request_bytes_today=size,
            daily_calls=self.settings.jev_daily_calls,
            daily_request_bytes=self.settings.jev_daily_request_bytes,
            running=bool(self.task and not self.task.done()),
            recent=self.repo.recent(),
        )

    async def stop(self, *, close: bool = False) -> None:
        self.closed = close
        self.generation += 1
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
