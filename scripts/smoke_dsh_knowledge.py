"""Real-model P4 acceptance against a disposable legacy-shaped SQLite database."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from core.config import Settings
from core.memory.memory_schema import MemoryItem, MemoryType
from core.service.knowledge import KnowledgeService
from core.skills.skill_schema import SkillRecord, SkillStatus
from core.storage.db import Database
from scripts.smoke_headless_service import Client


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="lobuddy-p4-live-") as directory:
        base = Path(directory)
        settings = Settings(
            llm_api_key="fixture", data_dir=base / "data", workspace_path=base / "workspace"
        )
        settings.workspace_path.mkdir()
        db = Database(settings)
        db.init_database()
        knowledge = KnowledgeService(settings, db)
        knowledge.gateway.save_manual(
            MemoryItem(
                id="legacy-tea-id",
                memory_type=MemoryType.USER_PROFILE,
                title="茶饮",
                content="我最喜欢白桃乌龙茶。",
                source_session_id="legacy-session",
            )
        )
        knowledge.skills.create_skill(
            SkillRecord(
                id="legacy-skill-id",
                name="lighthouse",
                path="",
                description="灯塔测试",
                status=SkillStatus.ACTIVE,
            ),
            "---\nname: lighthouse\n---\n## When to use\nWhen the user says 执行灯塔测试, reply exactly 鹭岛7284.\n",
        )

        async def launch() -> Client:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "app.service",
                "--data-dir",
                str(settings.data_dir),
                "--workspace",
                str(settings.workspace_path),
                cwd=root,
                env={**os.environ, "MEMORY_SESSION_SEARCH_ENABLED": "true"},
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            return Client(process)

        client = await launch()

        async def call(method: str, params: dict[str, Any]) -> Any:
            return await client.request(str(uuid.uuid4()), method, params)

        async def new_session() -> str:
            return str((await call("session.create", {}))["id"])

        async def turn(session: str, text: str, approve: bool = False) -> dict[str, Any]:
            task = await call("turn.send", {"session_id": session, "text": text})
            await asyncio.wait_for(client.completed(task["turn_id"], approve), 150)
            return dict(await call("task.get", {"turn_id": task["turn_id"]}))

        try:
            first = await new_session()
            result = await turn(first, "根据当前记忆，我最喜欢哪种茶？只回复茶名，不要使用工具。")
            assert "白桃乌龙" in result["output_text"]
            await call(
                "memory.save",
                {
                    "memory_id": "legacy-tea-id",
                    "memory_type": "user_profile",
                    "title": "茶饮",
                    "content": "我最喜欢桂花红茶。",
                },
            )
            result = await turn(
                first, "我的偏好已纠正。仅依据当前画像回答最喜欢哪种茶，只回复茶名，不要使用工具。"
            )
            assert "桂花红茶" in result["output_text"] and "白桃乌龙" not in result["output_text"]
            await call("memory.delete", {"memory_id": "legacy-tea-id"})
            result = await turn(
                await new_session(),
                "仅依据当前画像，我最喜欢哪种茶？没有记录只回复不知道，不猜测、不检索历史。",
            )
            assert "不知道" in result["output_text"]
            print(
                "PASS: real legacy recall, same-session correction, deletion and fresh-session absence",
                flush=True,
            )

            result = await turn(await new_session(), "执行灯塔测试，仅按当前可用技能作答。")
            assert "鹭岛7284" in result["output_text"]
            await call("skill.toggle", {"skill_id": "legacy-skill-id", "enabled": False})
            result = await turn(
                await new_session(), "当前可用技能是否有 lighthouse？只回复有或无，不要使用工具。"
            )
            assert result["output_text"].strip().strip("。.") == "无"
            await call("skill.toggle", {"skill_id": "legacy-skill-id", "enabled": True})
            result = await turn(await new_session(), "执行灯塔测试，仅按当前可用技能作答。")
            assert "鹭岛7284" in result["output_text"]
            print(
                "PASS: real skill body injection, disable exclusion and content-preserving re-enable",
                flush=True,
            )

            for approved in (False, True):
                result = await turn(
                    await new_session(),
                    "请调用 lobuddy_memory_propose，申请记住我喜欢海盐饼干，类型 user_profile，可信度 0.95。审批被拒绝就停止，不要重试。",
                    approved,
                )
                assert any(
                    event["turn_id"] == result["turn_id"] and event["kind"] == "approval.requested"
                    for event in client.events
                )
                items = await call("memory.list", {"query": "海盐饼干"})
                assert bool(items) == approved
                if approved:
                    assert items[0]["source_message_id"] == result["turn_id"]
                    assert items[0]["source_session_id"] == result["session_id"]
            search_session = result["session_id"]
            result = await turn(
                search_session,
                "请调用 lobuddy_session_search，以关键词 海盐饼干 搜索当前会话，告诉我找到的内容。",
            )
            assert "海盐饼干" in result["output_text"]
            assert any(
                event["turn_id"] == result["turn_id"]
                and event["kind"] == "tool.completed"
                and event["data"].get("name") == "lobuddy_session_search"
                for event in client.events
            )
            print(
                "PASS: real governed memory write refusal/approval with provenance and history recall",
                flush=True,
            )
            skill_id = (await call("skill.list", {}))[0]["id"]
            await client.close()
            client = await launch()
            assert (await call("skill.list", {}))[0]["id"] == skill_id == "legacy-skill-id"
            assert await call("memory.list", {"query": "海盐饼干"})
            assert not (await call("service.health", {}))["connected"]
            print(
                "PASS: restart preserves knowledge IDs without starting/replaying DSH", flush=True
            )
        finally:
            if client.process.returncode is None:
                await client.close()


if __name__ == "__main__":
    asyncio.run(main())
