"""Real DSH practical scenarios against synthetic files; fixture approvals only."""

import asyncio
import tempfile
import uuid
from pathlib import Path

from core.agent.dsh.runtime import DshRuntime
from core.config.credentials import load_settings
from core.service.application import ApplicationService
from core.service.protocol import RpcRequest
from core.storage.db import Database


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="lobuddy-e4-live-") as directory:
        settings = load_settings().model_copy(
            update={
                "data_dir": Path(directory) / "data",
                "workspace_path": Path(directory) / "workspace",
                "memory_enable_migration": False,
            }
        )
        settings.workspace_path.mkdir()
        db = Database(settings)
        db.init_database(allow_desktop=True)
        backend = DshRuntime(
            home=settings.data_dir / "dsh",
            workspace=settings.workspace_path,
            plugin=root / "bridge/dsh/dist/index.js",
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )
        service = ApplicationService(settings, db, backend, lambda _event: None)
        try:
            (settings.workspace_path / "input").mkdir()
            (settings.workspace_path / "input/a.txt").write_text(
                "决定采用绿色主题。\n待办：更新首页。"
            )

            async def run(text: str) -> str:
                session_id = uuid.uuid4().hex
                service.chat.get_or_create_session(session_id)
                result = await service.handle(
                    RpcRequest(
                        jsonrpc="2.0",
                        id=uuid.uuid4().hex,
                        method="turn.send",
                        params={"session_id": session_id, "text": text},
                    )
                )
                assert isinstance(result, dict)
                identity = str(result["turn_id"])
                async with asyncio.timeout(120):
                    while service.repo.get(identity).status in ("queued", "running"):
                        for pending in list(service.approvals.values()):
                            if not pending.future.done():
                                from core.safety.hitl_approval import HitlApprovalDecision

                                assert pending.request.tool_name == "lobuddy_organize"
                                pending.future.set_result(
                                    HitlApprovalDecision.approved_now(pending.request.request_id)
                                )
                        await asyncio.sleep(0.1)
                assert service.repo.get(identity).status == "completed"
                outcome = service.ledger.outcomes.get(identity)
                assert outcome.verdict == "verified", outcome.reason
                return identity

            copy_id = await run(
                "请调用 lobuddy_organize 将 input 目录文件按扩展名整理为 output 目录的副本，先预览再用原 preview_id 执行，审批界面会确认。保留原文件，展示验收结果。不要调用其他工具。"
            )
            assert (settings.workspace_path / "output/txt/a.txt").read_bytes() == (
                settings.workspace_path / "input/a.txt"
            ).read_bytes()
            print("PASS: real DSH preview → approval → copy → SHA256/count validation", flush=True)
            await run(
                "调用 lobuddy_digest 归纳 input/a.txt，给出带来源的摘要、决定和待办，不用其他工具。"
            )
            print(
                "PASS: real DSH source-cited digest and independently checked coverage", flush=True
            )
            service.learning.last_activity -= 61
            await service.learning.tick()
            assert service.learning.current is not None
            await service.learning.current
            candidate = service.knowledge.workflows.active("assistant-context")
            assert service.learning.repo.usage(service.learning.clock()).calls == 1
            assert candidate.status == "probation" and candidate.active
            assert candidate.evaluation["after"] < candidate.evaluation["before"]
            print(
                "PASS: real model proposed a candidate; 36 fixed cases promoted lossless compaction",
                flush=True,
            )
            from core.service.workflow_evaluation import context_definition

            bad = service.knowledge.workflows.propose(
                context_definition("pretty"), "synthetic regression", [copy_id]
            )
            assert service.knowledge.workflows.evaluate(bad.version_id).status == "rejected"
            print("PASS: regressing candidate rejected without activation", flush=True)
            service.knowledge.workflows.rollback(candidate.version_id)
            assert (
                service.knowledge.workflows.active("assistant-context").definition.nodes[0].format
                == "pretty"
            )
            print("PASS: explicit rollback restored stable working method", flush=True)
        finally:
            await service.close()


if __name__ == "__main__":
    asyncio.run(main())
