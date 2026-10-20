"""Source-checked readonly checkpoints and inspection of uncertain file effects."""

from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING

from pydantic import JsonValue

from core.agent.dsh.practical import read_file
from core.agent.dsh.tools import GovernedTools
from core.models.pet import TaskRecord, TaskStatus
from core.safety.hitl_approval import DenyAllHitlApprovalProvider
from core.service.outcomes import Outcome
from core.service.schedule_protocol import RecoveryRequest

if TYPE_CHECKING:
    from core.service.application import ApplicationService
    from core.service.protocol import TurnState


class DelegationRecovery:
    def __init__(self, service: ApplicationService) -> None:
        self.service = service
        self.db = service.delegation_repo.db
        with self.db.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS delegation_checkpoint(run_id TEXT PRIMARY KEY,version TEXT,sources TEXT,body TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS delegation_usage(run_id TEXT PRIMARY KEY,calls INTEGER,started_at REAL,spent REAL)"
            )

    def start_budget(self, run_id: str, seconds: float) -> float:
        now = time.time()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM delegation_usage WHERE run_id=?", (run_id,)
            ).fetchone()
            spent = float(row["spent"]) if row else 0.0
            if row and row["started_at"] is not None:
                spent += max(0.0, now - row["started_at"])
            if spent >= seconds:
                raise ValueError("原运行时间预算已耗尽，需要重新安排")
            conn.execute(
                "INSERT INTO delegation_usage VALUES(?,0,?,?) ON CONFLICT(run_id) DO UPDATE SET started_at=excluded.started_at,spent=excluded.spent",
                (run_id, now, spent),
            )
            return seconds - spent

    def reserve_call(self, run_id: str, limit: int) -> None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT calls FROM delegation_usage WHERE run_id=?", (run_id,)
            ).fetchone()
            if not row or row[0] >= limit:
                raise ValueError("原运行工具预算已耗尽")
            conn.execute("UPDATE delegation_usage SET calls=calls+1 WHERE run_id=?", (run_id,))

    def finish_budget(self, run_id: str) -> None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM delegation_usage WHERE run_id=?", (run_id,)
            ).fetchone()
            if row and row["started_at"] is not None:
                conn.execute(
                    "UPDATE delegation_usage SET spent=?,started_at=NULL WHERE run_id=?",
                    (row["spent"] + max(0.0, time.time() - row["started_at"]), run_id),
                )

    def fingerprints(self, sources: list[str], tools: GovernedTools) -> dict[str, str] | None:
        if any(source.startswith(("http://", "https://")) for source in sources):
            return None
        try:
            return {
                source: hashlib.sha256(
                    read_file(tools.workspace, tools._relative_path(source), 100000)
                ).hexdigest()
                for source in sources
            }
        except (ValueError, OSError):
            return None

    def prepare(self, state: TurnState, tools: GovernedTools) -> dict[str, JsonValue] | None:
        if not state.run_id:
            return None
        value = self.service.delegation_repo.get(state.delegation_id)
        if value.spec.kind != "source-digest":
            return None
        sources = self.fingerprints(value.spec.sources, tools)
        if sources is None:
            with self.db.get_connection() as conn:
                if conn.execute(
                    "SELECT 1 FROM delegation_checkpoint WHERE run_id=?", (state.run_id,)
                ).fetchone():
                    raise ValueError("检查点来源已不可验证")
            return None
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM delegation_checkpoint WHERE run_id=?", (state.run_id,)
            ).fetchone()
            if row:
                if (
                    row["version"] != state.workflow_version
                    or json.loads(row["sources"]) != sources
                ):
                    raise ValueError("来源或工作流版本已改变，不能使用旧检查点")
                values: dict[str, JsonValue] = json.loads(row["body"])
            else:
                values = {"input": state.workflow_input}
                conn.execute(
                    "INSERT INTO delegation_checkpoint VALUES(?,?,?,?)",
                    (state.run_id, state.workflow_version, json.dumps(sources), json.dumps(values)),
                )
        # Restoring verified evidence is allowed only after every local source hash matches.
        for item in values.values():
            if isinstance(item, dict) and isinstance(item.get("outcome"), dict):
                outcome = Outcome.model_validate(item["outcome"])
                if outcome.turn_id == state.turn_id:
                    self.service.ledger.outcomes.save(outcome)
        return values

    def save(self, run_id: str, values: dict[str, JsonValue]) -> None:
        body = json.dumps(values, ensure_ascii=False)
        if len(body.encode()) > 256000:
            return
        with self.db.transaction() as conn:
            conn.execute("UPDATE delegation_checkpoint SET body=? WHERE run_id=?", (body, run_id))

    async def recover(self, request_id: str, params: RecoveryRequest) -> None:
        repo = self.service.delegation_repo
        value = repo.get(params.delegation_id)
        if value.revision != params.revision or value.status not in ("paused", "needs_review"):
            raise ValueError("请重新读取需要核对的委托")
        runs = repo.detail(value.id).runs
        run = next((item for item in runs if item.id == value.active_run_id), None)
        if run is None or not run.turn_id or run.status in ("reserved", "running"):
            raise ValueError("执行尚未停止或没有可核对的记录")
        tools = GovernedTools(
            self.service.settings.workspace_path,
            DenyAllHitlApprovalProvider(),
            settings=self.service.settings,
        )
        if value.spec.kind == "organize-files":
            if params.action != "inspect":
                raise ValueError("未知写操作不得重放")
            with self.db.get_connection() as conn:
                effects = conn.execute(
                    "SELECT body FROM task_effect WHERE turn_id=?", (run.turn_id,)
                ).fetchall()
            if not effects:
                raise ValueError("没有写入证据；请核对产物并创建新委托，不复用旧审批")
            evidence = []
            for effect in effects:
                for item in json.loads(effect["body"]):
                    for key in ("source", "target"):
                        data = read_file(tools.workspace, tools._relative_path(item[key]))
                        if hashlib.sha256(data).hexdigest() != item["sha256"]:
                            raise ValueError("产物缺失或内容不符，保留未知状态；不会重做写入")
                    evidence.append(item)
            if not evidence:
                raise ValueError("没有足够的产物证据")
            outcome = Outcome(
                turn_id=run.turn_id,
                verdict="verified",
                scenario="organize",
                criteria=["原文件与全部副本 SHA-256 一致"],
                evidence=evidence,
                reason="重启后逐一核对了原文件和副本；未执行任何写入",
            )
            self.service.ledger.outcomes.save(outcome)
            with self.db.transaction() as conn:
                current = repo._read(conn, value.id)
                if current.revision != params.revision:
                    raise ValueError("委托已变化")
                run.status, run.verdict, run.reason = "completed", "verified", outcome.reason
                run.finished_at = repo.clock()
                conn.execute(
                    "UPDATE delegation_run SET body=? WHERE id=?", (run.model_dump_json(), run.id)
                )
                current.status, current.reason, current.active_run_id = (
                    "completed",
                    outcome.reason,
                    "",
                )
                current.revision += 1
                current.updated_at = repo.clock()
                repo._write(conn, current)
            return
        if value.spec.kind != "source-digest":
            raise ValueError("该委托不支持检查点恢复")
        state = self.service.repo.get(run.turn_id)
        with self.db.get_connection() as conn:
            snapshot = conn.execute(
                "SELECT * FROM delegation_checkpoint WHERE run_id=?", (run.id,)
            ).fetchone()
        fingerprints = self.fingerprints(value.spec.sources, tools)
        if (
            snapshot is None
            or fingerprints is None
            or json.loads(snapshot["sources"]) != fingerprints
        ):
            raise ValueError("无法确认来源版本一致，请重新确认范围并创建新委托")
        if (
            snapshot["version"] != run.workflow_version
            or not self.service.knowledge.workflows.get(run.workflow_version).active
        ):
            raise ValueError("原工作流版本已停用或发生变化")
        if params.action == "inspect":
            return
        if not value.expires_at or value.expires_at <= repo.clock():
            raise ValueError("授权已到期")
        with self.db.transaction() as conn:
            current = repo._read(conn, value.id)
            if current.revision != params.revision:
                raise ValueError("委托已更新")
            current.revision += 1
            current.updated_at = repo.clock()
            current.status, current.reason = "running", "来源版本一致，从只读检查点继续"
            run.revision, run.status, run.finished_at = current.revision, "running", None
            repo._write(conn, current)
            conn.execute(
                "UPDATE delegation_run SET body=? WHERE id=?", (run.model_dump_json(), run.id)
            )
        state.status, state.error = "queued", ""
        self.service.repo.save(state)
        self.service._states[state.task_id] = state
        self.service.emit(state, "turn.queued", {"recovered": True})
        await self.service._queues[state.lane].add_task(
            TaskRecord(id=state.task_id, input_text=state.input_text, status=TaskStatus.QUEUED)
        )
