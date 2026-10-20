"""Native macOS acceptance using synthetic credentials and a disposable document."""

import asyncio
import tempfile
import uuid
from pathlib import Path

from core.agent.dsh.web import fetch_page
from core.safety.guardrails import SafetyGuardrails
from core.services.local_open import LocalOpenService, open_native
from core.storage.keychain import MacKeychain


async def main() -> None:
    store = MacKeychain("com.lobuddy.acceptance." + uuid.uuid4().hex)
    try:
        assert store.get("synthetic") is None
        store.set("synthetic", "test-only-" + uuid.uuid4().hex)
        store.set("synthetic", "replacement-test-only")
        assert store.get("synthetic") == "replacement-test-only"
    finally:
        store.delete("synthetic")
    assert store.get("synthetic") is None
    print("PASS: native Keychain create/read/update/delete and cleanup", flush=True)
    with tempfile.TemporaryDirectory(prefix="lobuddy-native-p5-") as directory:
        workspace = Path(directory).resolve()
        document = workspace / "Lobuddy-acceptance.txt"
        document.write_text("Lobuddy macOS 本地打开验收。此文件仅用于测试。\n", encoding="utf-8")
        resolver = LocalOpenService(workspace)
        candidates = resolver.resolve("Lobuddy-acceptance")
        assert any(item["path"] == str(document) for item in candidates)
        await open_native(resolver.validate(str(document)))
        print(
            "PASS: actual macOS candidate lookup and /usr/bin/open accepted the test document",
            flush=True,
        )
        result = await asyncio.to_thread(
            fetch_page, "https://example.com", SafetyGuardrails(workspace), 3000
        )
        assert "Example Domain" in result
        print("PASS: real public HTTPS fetch with pinned DNS and bounded text", flush=True)
        search = await asyncio.to_thread(
            fetch_page,
            "https://www.bing.com/search?format=rss&q=DeepSeek+Harness",
            SafetyGuardrails(workspace),
            3000,
        )
        assert "https://www.deepseek.com" in search
        print("PASS: public RSS search returns actual result text and source URLs", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
