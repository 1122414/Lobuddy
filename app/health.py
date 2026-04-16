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

        all_healthy = (
            health["config_loaded"]
            and health["workspace_accessible"]
            and health["nanobot_available"]
            and health["pillow_available"]
        )

        return 0 if all_healthy else 1

    except Exception as e:
        print(f"\n[ERROR] Health check failed: {e}")
        return 1


def main() -> None:
    """Entry point for health check command."""
    exit_code = asyncio.run(check())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
