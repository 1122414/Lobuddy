"""Native masked credential input. Values never enter Electron's renderer or arguments."""

import asyncio
import os
import sys
from typing import Literal

from pydantic import BaseModel, ConfigDict

from core.config.credentials import SECRET_FIELDS
from core.storage.keychain import MacKeychain


class CredentialConfigure(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    account: Literal["llm_api_key", "llm_multimodal_api_key", "fish_api_key"]


async def configure_credential(account: str) -> bool:
    if account not in SECRET_FIELDS or sys.platform != "darwin":
        raise ValueError("当前平台不支持此凭据入口")
    label = {
        "llm_api_key": "模型服务",
        "llm_multimodal_api_key": "旧版图片模型",
        "fish_api_key": "Fish Audio",
    }[account]
    script = f'text returned of (display dialog "请输入{label} API Key，将保存到 macOS 钥匙串。" default answer "" with hidden answer buttons {{"取消", "保存"}} default button "保存" cancel button "取消" with title "Lobuddy 凭据设置")'
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/osascript",
        "-e",
        script,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={key: value for key, value in os.environ.items() if key in {"HOME", "PATH", "LANG"}},
        limit=8192,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 120)
        if process.returncode:
            return False
        secret = output.decode("utf-8").strip()
        if not secret or len(secret) > 4096 or any(char.isspace() for char in secret):
            raise ValueError("凭据格式无效，未保存")
        await asyncio.to_thread(MacKeychain().set, account, secret)
        return True
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
