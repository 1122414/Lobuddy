"""Read-only desktop health command; legacy bootstrap stays in app.bootstrap."""

import argparse
import asyncio
import json
from pathlib import Path

from core.config.credentials import load_settings
from core.service.health import inspect_desktop


async def check(data_dir: Path | None = None, workspace: Path | None = None) -> int:
    try:
        settings = load_settings()
        if data_dir:
            settings.data_dir = data_dir.resolve()
        if workspace:
            settings.workspace_path = workspace.resolve()
        report = inspect_desktop(settings)
        print(report.model_dump_json(indent=2))
        return 0 if report.ready else 1
    except (ValueError, RuntimeError, OSError, ImportError):
        # Validation and credential exceptions can contain sensitive input values.
        print(
            json.dumps(
                {"ready": False, "error": "无法读取配置或安全凭据；未修改数据"}, ensure_ascii=False
            )
        )
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Lobuddy DSH本地只读健康检查")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(check(args.data_dir, args.workspace)))


if __name__ == "__main__":
    main()
