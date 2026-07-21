"""Health check command for Lobuddy."""

import asyncio
import sys

from app.bootstrap import async_bootstrap


async def check() -> int:
    """Run health checks and exit with appropriate code.

    Returns:
        0 if healthy, 1 if unhealthy.
    """
    try:
        settings, health = await async_bootstrap()

        # P1-F5: Extended health checks
        _run_extended_checks(settings, health)

        pillow_required = bool(settings.llm_multimodal_model)
        all_healthy = (
            health["config_loaded"]
            and health["workspace_accessible"]
            and health.get("database_ready", False)
            and health["nanobot_available"]
            and (health["pillow_available"] if pillow_required else True)
        )

        return 0 if all_healthy else 1

    except Exception as e:
        print(f"\n[ERROR] Health check failed: {e}")
        return 1


def _run_extended_checks(settings, health: dict) -> None:
    """P1-F5: Run extended health checks and print readable report.

    Checks:
    - DB writable
    - workspace writable
    - nanobot importable or fallback status
    - PySide6 available
    - required config fields present
    """
    print("\n[Extended Health Checks]")

    # DB writable
    db_ok = health.get("database_ready", False)
    print(f"  Database writable: {'[OK]' if db_ok else '[FAIL]'}")

    # Workspace writable
    ws_ok = health.get("workspace_accessible", False)
    print(f"  Workspace writable: {'[OK]' if ws_ok else '[FAIL]'}")

    # Nanobot importable or fallback
    try:
        import nanobot
        print(f"  Nanobot importable: [OK] (version: {getattr(nanobot, '__version__', 'unknown')})")
    except ImportError:
        print("  Nanobot importable: [WARN] (fallback mode)")

    # PySide6 available
    try:
        import PySide6
        print(f"  PySide6 available: [OK] (version: {PySide6.__version__})")
    except ImportError:
        print("  PySide6 available: [FAIL]")

    # Required config fields
    config_ok = bool(
        settings.llm_api_key
        and settings.llm_api_key != "your_api_key_here"
        and settings.llm_base_url
    )
    print(f"  Required config fields: {'[OK]' if config_ok else '[FAIL]'}")
    if not config_ok:
        print("    - LLM_API_KEY must be set")
        print("    - LLM_BASE_URL must be set")


def main() -> None:
    """Entry point for health check command."""
    exit_code = asyncio.run(check())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
