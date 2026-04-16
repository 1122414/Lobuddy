"""Tests for bootstrap health check behavior."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.bootstrap import async_bootstrap, health_check
from app.config import Settings


class TestBootstrap:
    @pytest.mark.asyncio
    async def test_health_check_pillow_missing_reported(self, monkeypatch):
        """When PIL is unavailable, health_check should report pillow_available=False."""
        pil_modules = {
            name: mod
            for name, mod in sys.modules.items()
            if name == "PIL" or name.startswith("PIL.")
        }
        for name in pil_modules:
            monkeypatch.delitem(sys.modules, name, raising=False)
        monkeypatch.setitem(sys.modules, "PIL", None)

        settings = Settings(
            llm_api_key="test-key",
            llm_multimodal_model="some-model",
        )
        results = await health_check(settings)
        assert results["pillow_available"] is False
        assert any("Pillow not available" in err for err in results["errors"])

        for name, mod in pil_modules.items():
            sys.modules[name] = mod

    @pytest.mark.asyncio
    async def test_async_bootstrap_exits_when_multimodal_enabled_but_pillow_missing(self):
        """If multimodal model is configured but Pillow is missing, startup should exit."""
        mock_settings = MagicMock()
        mock_settings.llm_multimodal_model = "qwen-vl"
        mock_settings.app_name = "Lobuddy"

        with patch("app.bootstrap.bootstrap", return_value=mock_settings):
            with patch(
                "app.bootstrap.health_check",
                return_value={
                    "config_loaded": True,
                    "workspace_accessible": True,
                    "database_ready": True,
                    "pillow_available": False,
                    "nanobot_available": True,
                    "errors": ["Pillow not available: No module named 'PIL'"],
                },
            ):
                with pytest.raises(SystemExit) as exc_info:
                    await async_bootstrap()

        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_health_check_pillow_skipped_when_multimodal_disabled(self):
        """When multimodal is not configured, Pillow check should be skipped (None)."""
        settings = Settings(
            llm_api_key="test-key",
            llm_multimodal_model="",
        )
        results = await health_check(settings)
        assert results["pillow_available"] is None
        assert not any("Pillow" in err for err in results["errors"])
