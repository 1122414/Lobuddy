"""Real model method proposal from measured synthetic task evidence, no external writes."""

import asyncio
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from core.agent.dsh.runtime import DshRuntime
from core.config.credentials import load_settings
from core.service.application import ApplicationService
from core.service.digest_evaluation import digest_definition
from core.service.outcomes import Outcome
from core.service.protocol import RpcRequest
from core.storage.db import Database


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = Path(os.environ.get("LOBUDDY_VALIDATION_PLUGIN_ROOT", str(root)))
    evidence: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="lobuddy-method-live-") as directory:
        settings = load_settings().model_copy(
            update={
                "data_dir": Path(directory) / "data",
                "workspace_path": Path(directory) / "workspace",
                "memory_enable_migration": False,
            }
        )
        settings.workspace_path.mkdir()
        (settings.workspace_path / "a.txt").write_text(
            "决定：采用青绿色主题。\n待办：核对全部来源。"
        )
        (settings.workspace_path / "b.txt").write_text("另一来源：保留独立意见。")
        db = Database(settings)
        db.init_database(allow_desktop=True)
        backend = DshRuntime(
            home=settings.data_dir / "dsh",
            workspace=settings.workspace_path,
            plugin=plugin_root / "bridge/dsh/dist/index.js",
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )
        service = ApplicationService(settings, db, backend, lambda event: None)

        async def rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
            response = await service.handle(
                RpcRequest(jsonrpc="2.0", id=uuid.uuid4().hex, method=method, params=params)
            )
            if not isinstance(response, dict):
                raise TypeError("验收 RPC 未返回预期对象")
            return response

        async def run() -> Outcome:
            session = service.chat.get_or_create_session(uuid.uuid4().hex)
            result = await rpc(
                "turn.send",
                {
                    "session_id": session.id,
                    "text": "归纳这三个来源，保留各自引用。",
                    "workflow_id": "source-digest",
                    "workflow_input": {"sources": ["a.txt", "./a.txt", "b.txt"]},
                    "lane": "background",
                },
            )
            async with asyncio.timeout(10):
                while service.repo.get(result["turn_id"]).status in ("queued", "running"):
                    await asyncio.sleep(0.02)
            outcome = service.ledger.outcomes.get(result["turn_id"])
            assert outcome.verdict == "verified"
            return outcome

        try:
            await rpc("learning.configure", {"enabled": False})
            baseline = await run()
            assert baseline.metrics["physical_reads"] == 3
            await rpc("learning.configure", {"enabled": True})
            service.learning.repo.enqueue("workflow_proposal", baseline.turn_id, time.time())
            claimed = service.learning.repo.claim(
                "workflow_proposal",
                time.time(),
                service.learning.policy,
                calls=1,
                input_tokens=8192,
                output_tokens=2048,
            )
            assert claimed and claimed[1] == baseline.turn_id
            result = await service._learn_workflow(baseline.turn_id)
            service.learning.repo.finish(claimed[0], "completed", time.time(), json.dumps(result))
            version_id = result.get("version_id")
            if not isinstance(version_id, str):
                raise TypeError("学习结果未提供工作流版本 ID")
            candidate = service.knowledge.workflows.get(version_id)
            assert candidate.active and candidate.status == "probation"
            await rpc("learning.configure", {"enabled": False})
            improved = await run()
            assert improved.metrics["physical_reads"] == 2 and {
                item.get("ref") for item in improved.evidence if "ref" in item
            } == {"S1", "S2", "S3"}
            evidence["promoted"] = {
                "reason": candidate.reason,
                "evaluation": candidate.evaluation,
                "actual_before": baseline.metrics,
                "actual_after": improved.metrics,
            }
            print(
                "PASS: real model uses measured duplicate references; fixed task comparison promotes; actual new task reads 2 instead of 3 with all references",
                flush=True,
            )
            service.knowledge.workflows.rollback(candidate.version_id)
            reverted = await run()
            assert reverted.metrics["physical_reads"] == 3
            evidence["rollback"] = {
                "status": service.knowledge.workflows.get(candidate.version_id).status,
                "actual_after_rollback": reverted.metrics,
            }
            no_change = service.knowledge.workflows.propose(
                digest_definition(), "对照：不改变读取策略", [baseline.turn_id]
            )
            rejected = await asyncio.to_thread(
                service.knowledge.workflows.evaluate, no_change.version_id
            )
            assert rejected.status == "rejected"
            evidence["rejected"] = rejected.evaluation
            print(
                "PASS: user rejection restores previous behavior; no-improvement candidate rejected",
                flush=True,
            )
        finally:
            await service.close()
    report = root / "reports/2026-10-19_n5_real_method.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
