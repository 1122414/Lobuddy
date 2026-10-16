"""Real DSH relationship extraction and cross-session recall in a disposable database."""

import asyncio
import tempfile
import uuid
from pathlib import Path

from core.agent.dsh.runtime import DshRuntime
from core.config.credentials import load_settings
from core.models.chat import ChatMessage
from core.service.application import ApplicationService
from core.service.protocol import RpcRequest
from core.storage.db import Database


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="lobuddy-e1-live-") as directory:
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
            service.chat.get_or_create_session("source")
            service.chat.save_message(
                ChatMessage(
                    id="source-message",
                    session_id="source",
                    role="user",
                    content="我喜欢白桃乌龙茶。",
                )
            )
            service.learning.repo.enqueue(
                "relationship", "source-message", service.learning.clock()
            )
            service.learning.last_activity -= 61
            await service.learning.tick()
            assert service.learning.current is not None
            await service.learning.current
            relations = service.knowledge.relationship.list_relations()
            saved = next(
                item for item in relations if item.status == "active" and "白桃乌龙" in item.content
            )
            assert saved.source_ids == ["source-message"]
            assert service.learning.repo.usage(service.learning.clock()).calls == 1
            print("PASS: real DSH extraction, exact source and reserved model budget")
            service.knowledge.relationship.edit(
                saved.id, "我现在喜欢桂花红茶，不再喜欢白桃乌龙茶。"
            )

            async def recall() -> str:
                session_id = uuid.uuid4().hex
                service.chat.get_or_create_session(session_id)
                result = await service.handle(
                    RpcRequest(
                        jsonrpc="2.0",
                        id=uuid.uuid4().hex,
                        method="turn.send",
                        params={
                            "session_id": session_id,
                            "text": "根据当前记忆，我现在喜欢哪种茶？只回答茶名，不用工具。",
                        },
                    )
                )
                assert isinstance(result, dict)
                turn_id = str(result["turn_id"])
                async with asyncio.timeout(90):
                    while service.repo.get(turn_id).status in ("queued", "running"):
                        await asyncio.sleep(0.1)
                state = service.repo.get(turn_id)
                assert state.status == "completed"
                return state.output_text

            assert "桂花红茶" in await recall()
            print("PASS: explicit correction recalled by real DSH in a new session")
            service.knowledge.relationship.forget(saved.id)
            assert not service.knowledge.relationship._sources(["source-message"])
            assert "桂花红茶" not in await recall()
            print(
                "PASS: forgotten sources excluded and fresh-session recall no longer contains the fact"
            )
        finally:
            await service.close()


if __name__ == "__main__":
    asyncio.run(main())
