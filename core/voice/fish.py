"""Fish HTTP streaming with a fixed voice and explicit, non-secret error messages."""

from collections.abc import AsyncIterator

import httpx

from core.voice.protocol import VOICE_ID


class FishError(RuntimeError):
    pass


async def synthesize(
    text: str, key: str, model: str, *, client: httpx.AsyncClient | None = None
) -> AsyncIterator[bytes]:
    if not key:
        raise FishError("请先配置 Fish Audio 凭据")
    if client is None:
        async with httpx.AsyncClient(trust_env=False, timeout=30) as owned:
            async for chunk in synthesize(text, key, model, client=owned):
                yield chunk
        return
    try:
        async with (
            client.stream(
                "POST",
                "https://api.fish.audio/v1/tts",
                headers={"Authorization": "Bearer " + key, "model": model},
                json={
                    "text": text,
                    "reference_id": VOICE_ID,
                    "format": "pcm",
                    "sample_rate": 24000,
                    "latency": "balanced",
                },
            ) as response,
        ):
            if response.status_code != 200:
                messages = {
                    401: "Fish 凭据无效，请重新配置",
                    402: "Fish API 额度独立于网页积分，请检查 API 计费或选择免费档",
                    404: "选定音色不可用，未更换音色",
                    429: "Fish 请求过于频繁，请稍后重试",
                }
                raise FishError(messages.get(response.status_code, "Fish 合成暂不可用，未更换音色"))
            count = 0
            async for data in response.aiter_bytes(4096):
                count += len(data)
                if count > 24000 * 2 * 180:
                    raise FishError("合成音频超过单轮上限")
                yield data
            if count == 0:
                raise FishError("Fish 未返回音频，未更换音色")
    except httpx.HTTPError as error:
        raise FishError("Fish 连接中断，请检查网络；未自动重试") from error
