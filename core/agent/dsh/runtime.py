"""Own the version-matched SDK process and its authenticated plugin transport."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import stat
import tempfile
import uuid
from collections.abc import AsyncIterator
from importlib.metadata import version
from pathlib import Path
from typing import Literal

import httpx
from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, JsonValue

DSH_VERSION = "0.1.5rc1"

# Fixed rc.1 profile row IDs. No model-facing built-in tools or autonomous drivers.
DISABLED_ROWS = (
    "session-log-deepseek",
    "session-telemetry-otel",
    "plugin-package-inventory-deepseek",
    "session-title-llm",
    "agent-instructions",
    "skill-filesystem",
    "tool-skill",
    "tool-bash",
    "tool-pwsh",
    "tool-jobs",
    "tool-fs",
    "tool-fs-search",
    "tool-web",
    "tool-subagent",
    "tool-subagent-fork",
    "tool-subagent-control",
    "tool-subagent-list-agents",
    "tool-workflow",
    "tool-todo",
    "tool-goal",
    "tool-ralph",
    "goal-round-driver",
    "plan-mode",
    "command-feedback",
    "command-goal",
    "command-compact",
)


class BridgeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sessionId: str
    taskId: str
    turnId: str
    sequence: int = Field(ge=1)
    kind: Literal[
        "turn.started",
        "turn.completed",
        "turn.cancelled",
        "turn.failed",
        "text.delta",
        "text.final",
        "tool.request",
        "usage",
    ]
    data: dict[str, JsonValue]


class ReadyInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    port: int = Field(ge=1, le=65535)
    pid: int = Field(ge=1)
    protocol: Literal[1]


class DshRuntime:
    """Explicit start/close; never restarts or retries a potentially effectful request."""

    def __init__(
        self,
        *,
        home: Path,
        workspace: Path,
        plugin: Path,
        api_key: str,
        base_url: str,
        model: str,
    ) -> None:
        self.home = home.resolve()
        self.workspace = workspace.resolve()
        self.plugin = plugin.resolve()
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._harness: DeepSeekHarness | None = None
        self._http: httpx.AsyncClient | None = None
        self._startup: asyncio.Task[None] | None = None
        self._launch: tempfile.TemporaryDirectory[str] | None = None
        self._sequence = 0
        self._stream_open = False
        self.ready = asyncio.Event()
        self.process_id: int | None = None

    async def start(self) -> None:
        if self._harness:
            raise RuntimeError("Runtime already started")
        if not all((self._api_key.strip(), self._base_url.strip(), self._model.strip())):
            raise RuntimeError(
                "Configure LLM_API_KEY, LLM_BASE_URL and LLM_MODEL before starting DSH"
            )
        for package in ("deepseek-harness-sdk", "deepseek-harness-runtime-bin"):
            if version(package) != DSH_VERSION:
                raise RuntimeError(f"{package} must be {DSH_VERSION}")
        if not self.plugin.is_file():
            raise RuntimeError("Build the DSH plugin first: npm run --prefix bridge/dsh build")
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "nt":
            raise RuntimeError("DSH private home ACL validation is pending Windows qualification")
        self.home.chmod(0o700)
        self._launch = tempfile.TemporaryDirectory(prefix="bridge-", dir=self.home)
        launch = Path(self._launch.name)
        token = secrets.token_urlsafe(48)
        patch = launch / "plugin.patch.json"
        rows: list[dict[str, JsonValue]] = [{"id": row, "disabled": True} for row in DISABLED_ROWS]
        rows.extend(
            [
                {
                    "id": "system-prompt",
                    "config": {
                        "personaPrefix": "你是 Lobuddy 桌面个人助手。尊重用户偏好；工具被拒绝时不要绕过审批。",
                        "personaSuffix": "长期记忆由 Lobuddy 管理，不自行修改用户画像或安装插件。",
                    },
                },
                {"insert": [{"id": "lobuddy-bridge", "name": str(self.plugin)}]},
            ]
        )
        patch.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        patch.chmod(0o600)
        ready_path = launch / "ready.json"
        config = DeepSeekHarnessConfig(
            dsh_home=str(self.home),
            cwd=str(self.workspace),
            profile="sdk",
            patches=(str(patch),),
            api_key=self._api_key,
            base_url=self._base_url,
            provider="deepseek-official",
            model=self._model,
            env={
                "LOBUDDY_BRIDGE_TOKEN": token,
                "LOBUDDY_BRIDGE_READY": str(ready_path),
                "LOBUDDY_DSH_PROVIDER": "deepseek-official",
                "LOBUDDY_DSH_MODEL": self._model,
                "DSH_TELEMETRY_DISABLED": "1",
            },
            initialize_timeout_seconds=30,
            request_timeout_seconds=15,
        )
        self._harness = DeepSeekHarness(config)
        try:
            self._startup = asyncio.create_task(asyncio.to_thread(self._harness.start))
            await asyncio.shield(self._startup)
            async with asyncio.timeout(15):
                while not ready_path.exists():
                    await asyncio.sleep(0.05)
            if stat.S_IMODE(ready_path.stat().st_mode) != 0o600:
                raise RuntimeError("Bridge ready file permissions are unsafe")
            ready = ReadyInfo.model_validate_json(ready_path.read_text())
            self.process_id = ready.pid
            self._http = httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{ready.port}",
                headers={"Authorization": f"Bearer {token}"},
                trust_env=False,
                timeout=15,
            )
            await self.call("health", {})
        except BaseException:
            await self.close()
            raise

    async def call(self, method: str, params: dict[str, JsonValue]) -> JsonValue:
        if self._http is None:
            raise RuntimeError("Runtime is not connected")
        response = await self._http.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": method,
                "params": params,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError("DSH bridge rejected the request; no automatic retry")
        return payload["result"]  # type: ignore[no-any-return]

    async def events(self) -> AsyncIterator[BridgeEvent]:
        if self._http is None or self._stream_open:
            raise RuntimeError("Event stream unavailable")
        self._stream_open = True
        try:
            async with self._http.stream(
                "GET", "/events", timeout=httpx.Timeout(15, read=15)
            ) as stream:
                stream.raise_for_status()
                self.ready.set()
                async for line in stream.aiter_lines():
                    if len(line) > 1024 * 1024:
                        raise RuntimeError("Oversized bridge event")
                    if line.startswith("data: "):
                        event = BridgeEvent.model_validate_json(line[6:])
                        if event.sequence != self._sequence + 1:
                            raise RuntimeError("Lost or reordered bridge event; recovery required")
                        self._sequence = event.sequence
                        yield event
        finally:
            self.ready.clear()
            self._stream_open = False

    async def close(self) -> None:
        if self._startup is not None:
            # A failed startup may still own a child; wait for launch before teardown.
            with contextlib.suppress(Exception):
                await asyncio.shield(self._startup)
            self._startup = None
        if self._http:
            await self._http.aclose()
            self._http = None
        if self._harness:
            await asyncio.to_thread(self._harness.close)
            self._harness = None
        if self._launch:
            self._launch.cleanup()
            self._launch = None
        self._sequence = 0
        self.process_id = None
        self.ready.clear()
