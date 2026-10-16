"""Event-driven proactive policy; quotas survive renderer and service restarts."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.storage.db import Database
from core.storage.settings_repo import SettingsRepository


def proactive_instruction(text: str) -> bool | None:
    """Only direct instructions change interruption policy, never quoted questions."""
    value = text.strip().rstrip("。！!.")
    if re.fullmatch(
        r"(?:以后|今后|现在)?(?:请)?(?:不要|别)(?:再)?(?:主动找我(?:聊天|说话)?|主动打扰我|打扰我)",
        value,
    ):
        return False
    if re.fullmatch(r"(?:以后|现在)?(?:可以|允许你)(?:主动找我(?:聊天|说话)?|主动和我聊天)", value):
        return True
    return None


class CompanionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = True
    daily_limit: int = Field(default=3, ge=0, le=10)
    interval_minutes: int = Field(default=60, ge=1, le=1440)
    ignore_minutes: int = Field(default=120, ge=1, le=10080)
    do_not_disturb: bool = False


class CompanionActivity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    client: Literal["manage", "quick"]
    typing: bool
    conversation: bool


class CompanionTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event: Literal["app_returned", "conversation_finished", "focus_finished"]


class CompanionFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    notice_id: str = Field(min_length=1, max_length=128)
    action: Literal["opened", "ignored"]


class CompanionPreference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["nickname", "tone", "boundary", "shared"]
    content: str = Field(max_length=1000)


class CompanionNotice(BaseModel):
    notice_id: str
    text: str
    source: str
    expires_at: float


class PolicyState(BaseModel):
    day: str = ""
    used: int = 0
    last_shown: float = 0
    cooldown_until: float = 0
    pending: str = ""
    pending_at: float = 0
    pending_expires: float = 0
    notice: CompanionNotice | None = None


class Companionship:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time) -> None:
        self.repo = SettingsRepository(db)
        self.clock = clock
        self.policy = CompanionPolicy.model_validate_json(
            self.repo.get_setting("companion_policy") or "{}"
        )
        self.state = PolicyState.model_validate_json(
            self.repo.get_setting("companion_policy_state") or "{}"
        )
        self.activity: dict[str, tuple[float, CompanionActivity]] = {}
        if self.state.notice:
            self.state.cooldown_until = max(
                self.state.cooldown_until,
                self.state.last_shown + self.policy.ignore_minutes * 60,
            )
            self.state.notice = None
            self._save()

    def _save(self) -> None:
        self.repo.set_setting("companion_policy_state", self.state.model_dump_json())

    def configure(self, policy: CompanionPolicy) -> CompanionPolicy:
        self.repo.set_setting("companion_policy", policy.model_dump_json())
        self.policy = policy
        if not policy.enabled or policy.do_not_disturb or policy.daily_limit == 0:
            self.state.notice = None
            self.state.pending = ""
            self._save()
        return policy

    def engage(self, value: CompanionActivity) -> None:
        self.activity[value.client] = (self.clock(), value)
        # Opening a conversation consumes the current invitation without an ignore penalty.
        if (value.typing or value.conversation) and self.state.notice:
            self.feedback(CompanionFeedback(notice_id=self.state.notice.notice_id, action="opened"))

    def trigger(self, value: CompanionTrigger) -> None:
        now = self.clock()
        if self.state.notice or self.state.pending or now < self.state.cooldown_until:
            return
        self.state.pending = value.event
        self.state.pending_at = now + 30
        self.state.pending_expires = now + 1800
        self._save()

    def feedback(self, value: CompanionFeedback) -> None:
        notice = self.state.notice
        if notice is None or notice.notice_id != value.notice_id:
            return
        self.state.notice = None
        self.state.pending = ""
        if value.action == "ignored":
            self.state.cooldown_until = self.clock() + self.policy.ignore_minutes * 60
        self._save()

    def poll(self, *, focused: bool, running: bool) -> CompanionNotice | None:
        now = self.clock()
        day = datetime.fromtimestamp(now).date().isoformat()
        if day > self.state.day:
            self.state.day, self.state.used = day, 0
            self._save()
        if self.state.notice and now >= self.state.notice.expires_at:
            self.feedback(
                CompanionFeedback(notice_id=self.state.notice.notice_id, action="ignored")
            )
        engaged = any(
            now - updated < 10 and (activity.typing or activity.conversation)
            for updated, activity in self.activity.values()
        )
        if not self.policy.enabled or self.policy.do_not_disturb or focused or running or engaged:
            if self.state.notice:
                self.state.notice = None
                self._save()
            return None
        if self.state.notice:
            return self.state.notice
        if self.state.pending and now > self.state.pending_expires:
            self.state.pending = ""
            self._save()
        if (
            not self.state.pending
            or now < self.state.pending_at
            or self.state.used >= self.policy.daily_limit
            or now < self.state.cooldown_until
            or now - self.state.last_shown < self.policy.interval_minutes * 60
        ):
            return None
        text = {
            "app_returned": "我在这里。想聊一会儿的话，点点我就好。",
            "conversation_finished": "刚才聊过的事，还想接着说说吗？",
            "focus_finished": "忙完这一会儿了，想聊聊现在的心情吗？",
        }[self.state.pending]
        self.state.notice = CompanionNotice(
            notice_id=str(uuid.uuid4()), text=text, source=self.state.pending, expires_at=now + 20
        )
        self.state.used += 1
        self.state.last_shown = now
        self.state.pending = ""
        self._save()
        return self.state.notice
