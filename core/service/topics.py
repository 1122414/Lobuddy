"""Source-bound invitations and durable per-topic feedback; no inferred observation."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import MemoryItem, MemoryStatus, MemoryType
from core.memory.memory_service import _sanitize_memory_text
from core.service.relationship import REJECT_CONTEXT, SECRETS, SENSITIVE
from core.storage.db import Database


class TopicReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    topic_id: str = Field(min_length=1, max_length=128)


class TopicChoice(BaseModel):
    topic_id: str
    memory_id: str
    revision: str
    text: str


class TopicView(BaseModel):
    topic_id: str
    memory_id: str
    label: str
    blocked: bool
    cooldown_until: float


class CompanionOverview(BaseModel):
    experiences: list[dict[str, str]]
    preferences: list[dict[str, str]]
    available: list[str]
    verified_skills: list[str] = Field(default_factory=list)


class TopicService:
    def __init__(self, db: Database, clock: Callable[[], float]) -> None:
        self.db, self.clock = db, clock
        self.memory = MemoryRepository(db)
        with db.transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS companion_topic (
                id TEXT PRIMARY KEY, memory_id TEXT NOT NULL, revision TEXT NOT NULL,
                shown_at REAL NOT NULL, cooldown_until REAL NOT NULL DEFAULT 0,
                blocked INTEGER NOT NULL DEFAULT 0)""")

    @staticmethod
    def identity(item: MemoryItem) -> str:
        return hashlib.sha256(
            (item.memory_type.value + ":" + (item.title or item.id)).encode()
        ).hexdigest()

    def block_matching(self, subject: str) -> None:
        for kind in (MemoryType.EPISODIC_MEMORY, MemoryType.USER_PROFILE):
            for item in self.memory.list_by_type(kind, MemoryStatus.ACTIVE, limit=1000):
                if subject in item.content and item.scope == "global":
                    choice = TopicChoice(
                        topic_id=self.identity(item),
                        memory_id=item.id,
                        revision=hashlib.sha256(
                            (item.id + ":" + item.content).encode()
                        ).hexdigest(),
                        text="",
                    )
                    self.shown(choice)
                    self.feedback(choice.topic_id, "never")

    def choose(self) -> TopicChoice | None:
        now = self.clock()
        records = [
            item
            for kind in (MemoryType.EPISODIC_MEMORY, MemoryType.USER_PROFILE)
            for item in self.memory.list_by_type(kind, MemoryStatus.ACTIVE, limit=1000)
        ]
        records.sort(key=lambda item: item.updated_at, reverse=True)
        for item in records:
            if item.scope != "global" or item.is_expired() or len(item.content) > 150:
                continue
            if (
                SENSITIVE.search(item.content)
                or SECRETS.search(item.content)
                or _sanitize_memory_text(item.content) != item.content
            ):
                continue
            if item.memory_type == MemoryType.USER_PROFILE and (
                REJECT_CONTEXT.search(item.content)
                or not any(word in item.content for word in ("喜欢", "爱好", "偏好"))
            ):
                continue
            if item.memory_type == MemoryType.EPISODIC_MEMORY and item.source not in (
                "app_event",
                "relationship",
                "manual",
            ):
                continue
            topic = self.identity(item)
            revision = hashlib.sha256((item.id + ":" + item.content).encode()).hexdigest()
            with self.db.get_connection() as conn:
                previous = conn.execute(
                    "SELECT * FROM companion_topic WHERE id=?", (topic,)
                ).fetchone()
            if previous and (
                previous["blocked"]
                or previous["cooldown_until"] > now
                or (previous["revision"] == revision and now - previous["shown_at"] < 7 * 86400)
            ):
                continue
            lead = (
                "我们之前留下了一段记录"
                if item.memory_type == MemoryType.EPISODIC_MEMORY
                else "你之前提到"
            )
            return TopicChoice(
                topic_id=topic,
                memory_id=item.id,
                revision=revision,
                text=f"{lead}：「{item.content}」想接着聊聊吗？",
            )
        return None

    def shown(self, choice: TopicChoice) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO companion_topic(id,memory_id,revision,shown_at) VALUES(?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET memory_id=excluded.memory_id,
                revision=excluded.revision, shown_at=excluded.shown_at""",
                (choice.topic_id, choice.memory_id, choice.revision, self.clock()),
            )

    def valid(self, memory_id: str) -> bool:
        item = self.memory.get(memory_id)
        if not item or item.status != MemoryStatus.ACTIVE or item.is_expired():
            return False
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT revision,blocked FROM companion_topic WHERE id=?", (self.identity(item),)
            ).fetchone()
        revision = hashlib.sha256((item.id + ":" + item.content).encode()).hexdigest()
        return bool(row and not row["blocked"] and row["revision"] == revision)

    def feedback(self, topic_id: str, action: str) -> None:
        with self.db.transaction() as conn:
            if action == "never":
                conn.execute("UPDATE companion_topic SET blocked=1 WHERE id=?", (topic_id,))
            elif action in ("later", "ignored"):
                conn.execute(
                    "UPDATE companion_topic SET cooldown_until=? WHERE id=?",
                    (self.clock() + 86400, topic_id),
                )
            elif action == "unblock":
                conn.execute(
                    "UPDATE companion_topic SET blocked=0, cooldown_until=0 WHERE id=?", (topic_id,)
                )

    def list_topics(self) -> list[TopicView]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM companion_topic ORDER BY shown_at DESC LIMIT 100"
            ).fetchall()
        result = []
        for row in rows:
            memory = self.memory.get(row["memory_id"])
            result.append(
                TopicView(
                    topic_id=row["id"],
                    memory_id=row["memory_id"],
                    label=memory.content if memory else "来源记忆已删除",
                    blocked=bool(row["blocked"]),
                    cooldown_until=row["cooldown_until"],
                )
            )
        return result

    def overview(self) -> CompanionOverview:
        def records(kind: MemoryType) -> list[dict[str, str]]:
            return [
                {
                    "id": item.id,
                    "content": item.content,
                    "source": item.source,
                    "at": item.created_at.isoformat(),
                }
                for item in self.memory.list_by_type(kind, MemoryStatus.ACTIVE, limit=100)
                if not item.is_expired()
                and (kind == MemoryType.EPISODIC_MEMORY or item.title.startswith("相处 ·"))
            ]

        return CompanionOverview(
            experiences=records(MemoryType.EPISODIC_MEMORY),
            preferences=records(MemoryType.USER_PROFILE),
            available=["文字交流", "前台对话与后台任务", "专注计时", "记忆与技能管理"],
        )
