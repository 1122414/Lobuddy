"""Headless stdio entry point; lifecycle/composition only."""

import argparse
import asyncio
import logging
from pathlib import Path

from core.agent.dsh.runtime import DshRuntime
from core.config import Settings
from core.service.application import ApplicationService
from core.service.stdio import StdioServer
from core.storage.db import Database


async def run(data_dir: Path | None, workspace: Path | None) -> None:
    settings = Settings()  # type: ignore[call-arg]  # BaseSettings resolves the key from env.
    if data_dir:
        settings.data_dir = data_dir.resolve()
    if workspace:
        settings.workspace_path = workspace.resolve()
    settings.workspace_path.mkdir(parents=True, exist_ok=True)
    db = Database(settings)
    db.init_database()
    runtime = DshRuntime(
        home=settings.data_dir / "dsh-home",
        workspace=settings.workspace_path,
        plugin=Path(__file__).resolve().parents[1] / "bridge/dsh/dist/index.js",
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url or "https://api.deepseek.com",
        model=settings.llm_model,
    )
    transport = StdioServer()
    service = ApplicationService(settings, db, runtime, transport.publish)
    try:
        await transport.run(service.handle)
    finally:
        await service.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Lobuddy desktop stdio service")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run(args.data_dir, args.workspace))


if __name__ == "__main__":
    main()
