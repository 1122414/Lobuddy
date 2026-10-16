"""Owned idle worker. Handlers are trusted, read-only or idempotent derivations only."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import JsonValue

from core.config import Settings
from core.memory.memory_schema import MemoryStatus, MemoryType
from core.service.learning_protocol import (
    LearningConsumer,
    LearningPolicy,
    LearningState,
    LearningView,
)
from core.skills.skill_schema import SkillStatus
from core.storage.db import Database
from core.storage.learning_repo import LearningRepository
from core.storage.settings_repo import SettingsRepository


@dataclass(frozen=True)
class LearningHandler:
    run: Callable[[str], Awaitable[dict[str, JsonValue]]]
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class LearningService:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        busy: Callable[[], bool],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.repo = LearningRepository(db)
        self.settings = settings
        self.store = SettingsRepository(db)
        self.policy = LearningPolicy.model_validate_json(
            self.store.get_setting("learning_policy") or "{}"
        )
        self.clock, self.busy = clock, busy
        self.last_activity = clock()
        self.repo.recover(clock())
        self.handlers: dict[str, LearningHandler] = {}
        self.worker: asyncio.Task[None] | None = None
        self.current: asyncio.Task[None] | None = None
        self.closed = False

    def start(self) -> None:
        if not self.closed and self.policy.enabled and (self.worker is None or self.worker.done()):
            self.worker = asyncio.create_task(self._loop())

    async def configure(self, policy: LearningPolicy) -> LearningView:
        self.store.set_setting("learning_policy", policy.model_dump_json())
        self.policy = policy
        await self.activity()
        if not policy.enabled and self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
            self.worker = None
        self.start()
        return self.view()

    async def activity(self) -> None:
        self.last_activity = self.clock()
        if self.current and not self.current.done():
            self.current.cancel()
            await asyncio.gather(self.current, return_exceptions=True)

    async def tick(self) -> None:
        if self.closed or not self.policy.enabled:
            return
        if self.busy():
            self.last_activity = self.clock()
            return
        if self.clock() - self.last_activity < self.policy.idle_seconds:
            return
        if self.current and not self.current.done():
            return
        for kind, handler in self.handlers.items():
            claimed = self.repo.claim(
                kind,
                self.clock(),
                self.policy,
                calls=handler.calls,
                input_tokens=handler.input_tokens,
                output_tokens=handler.output_tokens,
            )
            if claimed:
                self.current = asyncio.create_task(self._run(claimed, handler))
                return

    async def _run(self, claimed: tuple[str, str], handler: LearningHandler) -> None:
        identity, source_id = claimed
        try:
            async with asyncio.timeout(60):
                result = await handler.run(source_id)
            self.repo.finish(
                identity, "completed", self.clock(), json.dumps(result, ensure_ascii=False)
            )
        except asyncio.CancelledError:
            self.repo.finish(
                identity, "interrupted", self.clock(), "{}", "前台活动或服务退出，已中断"
            )
            raise
        except Exception:  # noqa: BLE001 — worker boundary stores only a sanitized failure
            # Never persist provider responses, prompts or exception strings containing credentials.
            self.repo.finish(
                identity, "failed", self.clock(), "{}", "处理未完成，最多尝试三次；请检查服务状态"
            )

    async def _loop(self) -> None:
        while not self.closed and self.policy.enabled:
            self.repo.enqueue("maintenance", self.repo.day(self.clock()), self.clock())
            await self.tick()
            await asyncio.sleep(1)

    async def close(self) -> None:
        self.closed = True
        if self.worker:
            self.worker.cancel()
        await self.activity()
        if self.worker:
            await asyncio.gather(self.worker, return_exceptions=True)

    def view(self) -> LearningView:
        used = self.repo.usage(self.clock())
        state: LearningState = (
            "closed"
            if self.closed
            else (
                "disabled"
                if not self.policy.enabled
                else (
                    "running"
                    if self.current and not self.current.done()
                    else (
                        "waiting"
                        if self.busy()
                        or self.clock() - self.last_activity < self.policy.idle_seconds
                        else (
                            "budget_exhausted"
                            if (
                                used.calls >= self.policy.daily_calls
                                or used.input_tokens >= self.policy.daily_input_tokens
                                or used.output_tokens >= self.policy.daily_output_tokens
                            )
                            else "idle"
                        )
                    )
                )
            )
        )
        consumers = [
            LearningConsumer(
                setting="learning_policy.enabled",
                enabled=self.policy.enabled,
                consumer="LearningService",
                behavior="空闲调度；关闭会取消当前学习",
            ),
            LearningConsumer(
                setting="memory_lint_enabled",
                enabled=self.settings.memory_lint_enabled,
                consumer="maintenance",
                behavior="每日只读巡检，不自动修改或删除",
            ),
            LearningConsumer(
                setting="skill_maintenance_interval_hours",
                enabled=True,
                consumer="maintenance",
                behavior="新版每日只读巡检；旧小时配置不参与调度",
            ),
            LearningConsumer(
                setting="memory_profile_daily_consolidation",
                enabled=False,
                consumer="未接入",
                behavior="画像模型整理尚未接入；配置值不代表实际运行",
            ),
            LearningConsumer(
                setting="skill_auto_candidate_enabled",
                enabled=self.settings.skill_auto_candidate_enabled,
                consumer="KnowledgeService.completed",
                behavior="旧候选提取，尚无自动评测晋升",
            ),
        ]
        return LearningView(
            policy=self.policy, state=state, usage=used, jobs=self.repo.jobs(), consumers=consumers
        )


def maintenance_handler(settings: Settings, db: Database) -> LearningHandler:
    async def inspect(_source: str) -> dict[str, JsonValue]:
        from core.memory.memory_repository import MemoryRepository
        from core.skills.skill_manager import SkillManager

        memories = MemoryRepository(db)
        skills = SkillManager(
            settings.model_copy(
                update={"skill_archive_dir": settings.data_dir / "skills" / "archive"}
            ),
            db,
        )
        expired = duplicates = 0
        seen: set[tuple[str, str]] = set()
        profiles: dict[tuple[str, str], set[str]] = {}
        for kind in MemoryType:
            await asyncio.sleep(0)
            for item in memories.list_by_type(kind, MemoryStatus.ACTIVE, limit=10000):
                if settings.memory_lint_enabled:
                    expired += int(item.is_expired())
                    key = (kind.value, item.content.strip().casefold())
                    duplicates += int(key in seen)
                    seen.add(key)
                    if kind in (MemoryType.USER_PROFILE, MemoryType.SYSTEM_PROFILE) and item.title:
                        profiles.setdefault((kind.value, item.title), set()).add(item.content)
        stale = 0
        cutoff = datetime.now() - timedelta(days=settings.skill_stale_review_days)
        for skill in skills.list_skills(status=SkillStatus.ACTIVE, limit=10000):
            stale += int((skill.last_used_at or skill.created_at) < cutoff)
        return {
            "expired_memories": expired,
            "duplicate_memories": duplicates,
            "possible_conflicts": sum(len(values) > 1 for values in profiles.values()),
            "stale_skills": stale,
            "read_only": True,
        }

    return LearningHandler(inspect)
