"""Real DSH project recall and grounded companionship using synthetic records only."""

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
from core.service.companionship import CompanionTrigger
from core.service.protocol import RpcRequest
from core.storage.db import Database


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    plugin_root = Path(os.environ.get("LOBUDDY_VALIDATION_PLUGIN_ROOT", str(root)))
    evidence: dict[str, Any] = {
        "scope": "synthetic project and conversation; real configured DSH model; no microphone",
        "checks": [],
    }
    with tempfile.TemporaryDirectory(prefix="lobuddy-personal-live-") as directory:
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

        async def chat(session: str, text: str) -> str:
            result = await rpc("turn.send", {"session_id": session, "text": text})
            async with asyncio.timeout(90):
                while service.repo.get(result["turn_id"]).status in ("queued", "running"):
                    await asyncio.sleep(0.1)
            state = service.repo.get(result["turn_id"])
            assert state.status == "completed", state.status
            return state.output_text

        try:
            await rpc("learning.configure", {"enabled": False})
            first = await rpc(
                "project.create", {"name": "合成水彩计划", "goal": "保留明确的制作决定"}
            )
            second = await rpc(
                "project.create", {"name": "合成水彩计划", "goal": "独立验证同名项目隔离"}
            )
            source = await rpc(
                "source.share",
                {
                    "title": "配色决定",
                    "project_id": first["id"],
                    "text": "决定：水彩封面采用琥珀色。",
                    "category": "decision",
                },
            )
            for name, project in (("a", first), ("b", first), ("unrelated", second)):
                service.chat.get_or_create_session(name)
                await rpc(
                    "project.bind", {"session_id": name, "project_id": project["id"], "revision": 0}
                )
            answer = await chat("a", "当前项目决定使用什么封面颜色？只根据明确材料回答，不用工具。")
            assert "琥珀" in answer
            await rpc(
                "source.correct",
                {
                    "source_id": source["id"],
                    "revision": 1,
                    "text": "纠正决定：水彩封面采用孔雀蓝，取消先前配色。",
                },
            )
            answer = await chat("b", "当前项目最后确定什么封面颜色？只说颜色，不用工具。")
            assert "孔雀蓝" in answer and "琥珀" not in answer
            evidence["checks"].append({"check": "cross_session_correction", "answer": answer})
            unrelated = await chat(
                "unrelated", "当前项目确定什么封面颜色？没有明确材料就说不知道，不用工具。"
            )
            assert "孔雀蓝" not in unrelated and "琥珀" not in unrelated
            evidence["checks"].append({"check": "same_name_project_isolation", "answer": unrelated})
            print(
                "PASS: real model project recall, explicit correction, cross-session continuation and same-name isolation",
                flush=True,
            )
            shared = await rpc(
                "source.share",
                {
                    "title": "共同完成的检查",
                    "project_id": first["id"],
                    "text": "我们一起完成了提醒功能的测试。",
                    "category": "shared",
                },
            )
            # Exercise the existing reservation before the real auxiliary model call.
            await rpc("learning.configure", {"enabled": True})
            service.companionship.state.pending = ""
            service.companionship.state.cooldown_until = 0
            service.companionship.state.last_shown = 0
            service.companionship.trigger(CompanionTrigger(event="app_returned"))
            service.dialogue.enqueue()
            claimed = service.learning.repo.claim(
                "companion_topic",
                time.time(),
                service.learning.policy,
                calls=1,
                input_tokens=8192,
                output_tokens=1024,
            )
            assert claimed
            result = await service.dialogue.prepare(claimed[1])
            assert result.get("prepared"), result
            service.learning.repo.finish(claimed[0], "completed", time.time(), json.dumps(result))
            choice = service.dialogue.choose()
            assert choice and choice.memory_id == "project:" + shared["id"]
            evidence["checks"].append(
                {
                    "check": "source_grounded_real_model_invitation",
                    "text": choice.text,
                    "budget_calls": service.learning.repo.usage(time.time()).calls,
                }
            )
            print(
                "PASS: real model source quote, bounded invitation composition and durable shared budget",
                flush=True,
            )
            await rpc("learning.configure", {"enabled": False})
            answer = await chat("b", "先听我讲")
            dialogue_state = service.dialogue.state("b")
            assert dialogue_state is not None and dialogue_state.mode == "listening"
            assert answer.count("？") + answer.count("?") <= 1
            evidence["checks"].append(
                {"check": "listening_mode_response_not_human_acceptance", "answer": answer}
            )
            await rpc("source.forget", {"source_id": source["id"], "revision": 2})
            service.chat.get_or_create_session("after-forget")
            await rpc(
                "project.bind",
                {"session_id": "after-forget", "project_id": first["id"], "revision": 0},
            )
            forgotten = await chat(
                "after-forget", "当前封面确定什么颜色？没有明确材料就说不知道，不用工具。"
            )
            assert "孔雀蓝" not in forgotten
            evidence["checks"].append(
                {"check": "forgotten_source_not_recalled", "answer": forgotten}
            )
            print(
                "PASS: explicit listening state and forgotten project source excluded from fresh-session recall",
                flush=True,
            )
        finally:
            await service.close()
    report = root / "reports/2026-10-19_n4_real_context.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
