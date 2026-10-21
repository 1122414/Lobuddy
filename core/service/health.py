"""Read-only readiness diagnostics for the DSH desktop runtime, without legacy Qt bootstrap."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from core.config import Settings
from core.service.settings_service import settings_from_rows


class HealthItem(BaseModel):
    name: str
    state: Literal["ok", "unavailable", "optional"]
    detail: str


class DesktopHealth(BaseModel):
    ready: bool
    scope: str = "本地就绪检查；不调用模型、不采音、不迁移或恢复任务"
    checks: list[HealthItem]


def directory_available(path: Path) -> bool:
    candidate = path.resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)


def inspect_desktop(settings: Settings, root: Path | None = None) -> DesktopHealth:
    root = root or Path(__file__).resolve().parents[2]
    checks: list[HealthItem] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(HealthItem(name=name, state="ok" if passed else "unavailable", detail=detail))

    for name, path in (
        ("data_directory", settings.data_dir),
        ("workspace", settings.workspace_path),
    ):
        add(name, directory_available(path), "检查已有目录或最近父目录的访问权限；不写入文件")
    database = settings.data_dir / "lobuddy.db"
    try:
        if database.exists():
            with closing(
                sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
            ) as conn:
                add(
                    "database",
                    conn.execute("PRAGMA quick_check(1)").fetchone()[0] == "ok",
                    "已有数据库只读检查",
                )
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_settings'"
                ).fetchone():
                    settings = settings_from_rows(
                        settings, conn.execute("SELECT key,value FROM app_settings")
                    )
        else:
            add("database", True, "尚未初始化；首次启动时创建，本次不创建")
    except (sqlite3.Error, ValueError, OSError):
        add("database_settings", False, "数据库无法读取或保存的设置无效；未修改原数据")
    add(
        "model_configuration",
        bool(
            settings.llm_api_key.strip()
            and settings.llm_model.strip()
            and settings.llm_base_url.strip()
        ),
        "仅检查配置是否齐全，不验证远端模型或额度",
    )
    try:
        from deepseek_harness_runtime import bundled_runtime_path  # type: ignore[import-untyped]

        from core.agent.dsh.runtime import DSH_VERSION

        binary = bundled_runtime_path()
        matched = all(
            version(name) == DSH_VERSION
            for name in ("deepseek-harness-sdk", "deepseek-harness-runtime-bin")
        )
        add(
            "dsh_runtime",
            matched and binary.is_file() and os.access(binary, os.X_OK),
            "SDK/runtime版本匹配且本机可执行文件存在",
        )
    except (ImportError, OSError, RuntimeError, ValueError):
        add("dsh_runtime", False, "DSH依赖、版本或本机运行文件不可用")
    add(
        "plugin_bridge",
        (root / "bridge/dsh/dist/index.js").is_file(),
        "检查已构建插件桥入口；完整通信另由桌面握手验证",
    )
    checks.append(
        HealthItem(
            name="voice",
            state="optional",
            detail="语音模型、Fish额度及真实设备在语音设置和专项验收中检查；不阻塞文字",
        )
    )
    return DesktopHealth(ready=all(item.state != "unavailable" for item in checks), checks=checks)
