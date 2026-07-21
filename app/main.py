"""Main entry point for Lobuddy application."""

import asyncio
import sys

from app.bootstrap import async_bootstrap
from app.container import AppContainer
from app.ui_controller import UiController
from core.logging.trace import get_logger

system_log = get_logger("system")


def run_ui_mode(settings):
    """Run PySide6 UI mode using the container/controller pattern."""
    container = AppContainer(settings)
    controller = UiController(container)
    exit_code = controller.start()
    sys.exit(exit_code)


def main():
    """Main entry point — bootstrap then delegate to UI controller."""
    try:
        settings, _ = asyncio.run(async_bootstrap())
        system_log.info(
            "UI mode starting — app=%s, model=%s",
            settings.app_name,
            settings.llm_model,
        )
        run_ui_mode(settings)
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
