"""Immutable proposals, fixed evaluation, promotion CAS and observable rollback."""

from __future__ import annotations

import difflib
import hashlib
import json
from collections.abc import Awaitable, Callable

from pydantic import JsonValue

from core.service.workflow_engine import serialize
from core.service.workflow_evaluation import context_definition, evaluate
from core.service.workflow_protocol import ContextProposal, WorkflowDefinition, WorkflowView
from core.storage.db import Database


class WorkflowService:
    def __init__(self, db: Database) -> None:
        self.db = db
        with db.transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS workflow_version(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,parent TEXT NOT NULL,body TEXT NOT NULL,
                reason TEXT NOT NULL,evidence TEXT NOT NULL,status TEXT NOT NULL,
                evaluation TEXT NOT NULL DEFAULT '{}',observed INTEGER NOT NULL DEFAULT 0)""")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS workflow_active(
                name TEXT PRIMARY KEY,version_id TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1)"""
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS workflow_observation(
                run_id TEXT PRIMARY KEY,version_id TEXT NOT NULL,state TEXT NOT NULL)""")
        self.seed(context_definition())
        self.seed(
            WorkflowDefinition.model_validate(
                {
                    "name": "organize-files",
                    "permissions": ["lobuddy_organize"],
                    "nodes": [
                        {
                            "id": "preview",
                            "kind": "tool",
                            "tool": "lobuddy_organize",
                            "arguments": {"source": "$input.source", "output": "$input.output"},
                        },
                        {
                            "id": "copy",
                            "kind": "tool",
                            "tool": "lobuddy_organize",
                            "after": ["preview"],
                            "arguments": {
                                "source": "$input.source",
                                "output": "$input.output",
                                "preview_id": "$preview.preview_id",
                            },
                        },
                        {"id": "check", "kind": "verify", "after": ["copy"]},
                        {"id": "result", "kind": "output", "source": "check", "after": ["check"]},
                    ],
                }
            )
        )
        self.seed(
            WorkflowDefinition.model_validate(
                {
                    "name": "source-digest",
                    "permissions": ["lobuddy_digest"],
                    "nodes": [
                        {
                            "id": "digest",
                            "kind": "tool",
                            "tool": "lobuddy_digest",
                            "arguments": {"sources": "$input.sources"},
                        },
                        {"id": "result", "kind": "output", "source": "digest", "after": ["digest"]},
                    ],
                }
            )
        )

    def seed(self, definition: WorkflowDefinition) -> None:
        identity = "builtin-" + definition.name + "-1"
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO workflow_version(id,name,parent,body,reason,evidence,status) VALUES(?,?,?,?,'内置固定版本','[]','stable')",
                (identity, definition.name, "", definition.model_dump_json()),
            )
            conn.execute(
                "INSERT OR IGNORE INTO workflow_active(name,version_id) VALUES(?,?)",
                (definition.name, identity),
            )

    def active(self, name: str) -> WorkflowView:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT version_id FROM workflow_active WHERE name=? AND enabled=1", (name,)
            ).fetchone()
        if not row:
            raise ValueError("工作流已停用或不存在")
        return self.get(row[0])

    def get(self, identity: str) -> WorkflowView:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM workflow_version WHERE id=?", (identity,)).fetchone()
            if not row:
                raise ValueError("工作流版本不存在")
            active = conn.execute(
                "SELECT 1 FROM workflow_active WHERE version_id=? AND enabled=1", (identity,)
            ).fetchone()
            parent = conn.execute(
                "SELECT body FROM workflow_version WHERE id=?", (row["parent"],)
            ).fetchone()
        definition = WorkflowDefinition.model_validate_json(row["body"])
        before = (
            WorkflowDefinition.model_validate_json(parent[0]).model_dump_json(indent=2)
            if parent
            else ""
        )
        diff = "\n".join(
            difflib.unified_diff(
                before.splitlines(),
                definition.model_dump_json(indent=2).splitlines(),
                fromfile="stable",
                tofile="candidate",
            )
        )
        return WorkflowView(
            version_id=identity,
            parent_id=row["parent"],
            definition=definition,
            reason=row["reason"],
            evidence=json.loads(row["evidence"]),
            status=row["status"],
            evaluation=json.loads(row["evaluation"]),
            observed=row["observed"],
            active=bool(active),
            diff=diff,
        )

    def versions(self) -> list[WorkflowView]:
        with self.db.get_connection() as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    "SELECT id FROM workflow_version ORDER BY rowid DESC LIMIT 100"
                )
            ]
        return [self.get(identity) for identity in ids]

    def propose(
        self, definition: WorkflowDefinition, reason: str, evidence: list[str]
    ) -> WorkflowView:
        stable = self.active(definition.name)
        body = definition.model_dump_json()
        identity = hashlib.sha256(
            (stable.version_id + body + json.dumps(evidence)).encode()
        ).hexdigest()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO workflow_version(id,name,parent,body,reason,evidence,status) VALUES(?,?,?,?,?,?,'candidate')",
                (identity, definition.name, stable.version_id, body, reason, json.dumps(evidence)),
            )
        return self.get(identity)

    def evaluate(self, identity: str) -> WorkflowView:
        value = self.get(identity)
        if value.status != "candidate":
            return value
        stable = self.get(value.parent_id)
        result = evaluate(stable.definition, value.definition)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE workflow_version SET evaluation=?,status=? WHERE id=? AND status='candidate'",
                (
                    json.dumps(result),
                    "rejected" if result["decision"] == "rejected" else "review",
                    identity,
                ),
            )
        if result["decision"] == "promote":
            self.enable(identity)
        return self.get(identity)

    def enable(self, identity: str) -> None:
        value = self.get(identity)
        with self.db.transaction() as conn:
            if (
                value.status in ("stable", "probation")
                and conn.execute(
                    "UPDATE workflow_active SET enabled=1 WHERE version_id=?", (identity,)
                ).rowcount
            ):
                return
        if (
            value.status not in ("review", "stable")
            or value.evaluation.get("decision") != "promote"
        ):
            raise ValueError("没有固定验证通过的晋升记录")
        with self.db.transaction() as conn:
            changed = conn.execute(
                "UPDATE workflow_active SET version_id=?,enabled=1 WHERE name=? AND version_id=? AND enabled=1",
                (identity, value.definition.name, value.parent_id),
            )
            if changed.rowcount != 1:
                raise ValueError("稳定版本已变化，需重新评测")
            conn.execute("UPDATE workflow_version SET status='probation' WHERE id=?", (identity,))

    def disable(self, identity: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE workflow_active SET enabled=0 WHERE version_id=?", (identity,))

    def rollback(self, identity: str, reason: str = "用户否定此次改变") -> None:
        value = self.get(identity)
        if not value.parent_id:
            raise ValueError("内置基线无上一个版本，可停用")
        with self.db.transaction() as conn:
            changed = conn.execute(
                "UPDATE workflow_active SET version_id=?,enabled=1 WHERE version_id=?",
                (value.parent_id, identity),
            )
            if changed.rowcount:
                conn.execute(
                    "UPDATE workflow_version SET status='rolled_back',evaluation=? WHERE id=?",
                    (json.dumps(value.evaluation | {"rollback_reason": reason}), identity),
                )

    def observe(self, identity: str, run_id: str, good: bool) -> None:
        value = self.get(identity)
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT state FROM workflow_observation WHERE run_id=?", (run_id,)
            ).fetchone()
            if existing and existing[0] != "running":
                return
            conn.execute(
                "INSERT OR REPLACE INTO workflow_observation VALUES(?,?,?)",
                (run_id, identity, "passed" if good else "failed"),
            )
            if good and value.status == "probation":
                conn.execute(
                    "UPDATE workflow_version SET observed=observed+1,status=CASE WHEN observed+1>=5 THEN 'stable' ELSE status END WHERE id=?",
                    (identity,),
                )
        if not good and value.status == "probation":
            self.rollback(identity, "观察期出现行为回归，已回退")

    def begin(self, identity: str, run_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO workflow_observation VALUES(?,?,'running')",
                (run_id, identity),
            )

    def recover(self) -> None:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_observation WHERE state='running'"
            ).fetchall()
        for row in rows:
            self.observe(row["version_id"], row["run_id"], False)

    def context(self, data: dict[str, JsonValue], run_id: str) -> str:
        try:
            with self.db.get_connection() as conn:
                pinned = conn.execute(
                    "SELECT version_id FROM workflow_observation WHERE run_id=?",
                    ("context:" + run_id,),
                ).fetchone()
            value = self.get(pinned[0]) if pinned else self.active("assistant-context")
        except ValueError:
            return serialize(data, "pretty")
        expected = context_definition(value.definition.nodes[0].format)
        good = value.definition == expected
        self.observe(value.version_id, "context:" + run_id, good)
        return serialize(data, value.definition.nodes[0].format if good else "pretty")

    async def generate(
        self, source_id: str, model: Callable[[str], Awaitable[str]]
    ) -> WorkflowView:
        stable = self.active("assistant-context")
        prompt = (
            "提出一个低风险上下文工作流候选，减少序列化开销并保留全部字段。"
            '仅返回简短 JSON {"format":"pretty或compact","reason":"简短理由"}，不要解释或代码围栏。'
            "不能修改权限、节点类型、评测或安全规则。"
            '开发样例：{"records":[{"id":"demo","description":"简短偏好"}]}。'
            "允许 context 节点 format=pretty 或 compact。不增加提示或删减记录。当前版本："
            + stable.definition.model_dump_json(exclude_defaults=True)
        )
        proposal = ContextProposal.model_validate_json(await model(prompt))
        definition = context_definition(proposal.format)
        candidate = self.propose(definition, proposal.reason, [source_id])
        return self.evaluate(candidate.version_id)
