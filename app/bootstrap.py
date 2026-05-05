"""Bootstrap module for Lobuddy application initialization."""

import sys

from loguru import logger

from app.config import Settings, get_settings
from core.agent.nanobot_adapter import NanobotAdapter
from core.storage.chat_repo import ChatRepository
from core.storage.db import init_database
from core.storage.pet_repo import PetRepository


def setup_logging(settings: Settings) -> None:
    """Configure trace logging with daily folder organization."""
    from core.logging.trace import setup_trace_logging

    logs_dir = settings.logs_dir
    logs_dir.mkdir(parents=True, exist_ok=True)
    setup_trace_logging(logs_dir, settings.log_level)


def create_directories(settings: Settings) -> None:
    """Create necessary runtime directories."""
    directories = [
        settings.data_dir,
        settings.logs_dir,
        settings.workspace_path,
    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Ensured directory exists: {directory}")


async def _run_check(name: str, check_fn, results: dict, error_fmt: str = "") -> bool:
    """Run a health check and record result."""
    import inspect
    try:
        if inspect.iscoroutinefunction(check_fn):
            result = await check_fn()
        else:
            result = check_fn()
        if result is False:
            results["errors"].append(f"{name} failed")
            logger.error(f"{name} failed")
            return False
        return True
    except Exception as e:
        msg = (error_fmt or f"{name} error: {{}}").format(e)
        results["errors"].append(msg)
        logger.error(msg)
        return False


async def health_check(settings: Settings) -> dict:
    """Run health checks on application dependencies."""
    results = {
        "config_loaded": False,
        "nanobot_available": False,
        "workspace_accessible": False,
        "database_ready": False,
        "pillow_available": None,
        "errors": [],
    }

    def _check_config():
        if settings.llm_api_key and settings.llm_api_key != "your_api_key_here":
            logger.info("Configuration loaded successfully")
            return True
        logger.warning("LLM API key not configured")
        results["errors"].append("LLM API key not configured")
        return False

    def _check_workspace():
        workspace = settings.workspace_path
        workspace.mkdir(parents=True, exist_ok=True)
        test_file = workspace / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
        logger.info(f"Workspace accessible: {workspace}")

    def _check_database():
        init_database(settings)
        pet_repo = PetRepository()
        pet = pet_repo.get_or_create_pet()
        chat_repo = ChatRepository()
        chat_repo.get_or_create_session("default", "default")
        logger.info(f"Database ready, pet: {pet.name} (Lv{pet.level})")

    async def _check_nanobot():
        adapter = NanobotAdapter(settings)
        nanobot_healthy = await adapter.health_check()
        if nanobot_healthy:
            logger.info("Nanobot adapter initialized successfully")
        else:
            results["errors"].append("Nanobot initialization failed")
            logger.error("Nanobot adapter initialization failed")
        return nanobot_healthy

    def _check_pillow():
        from PIL import Image
        logger.info(f"Pillow available: {Image.__version__}")

    results["config_loaded"] = await _run_check("Config", _check_config, results)
    results["workspace_accessible"] = await _run_check("Workspace", _check_workspace, results)
    results["database_ready"] = await _run_check("Database", _check_database, results)

    if settings.llm_multimodal_model:
        results["pillow_available"] = await _run_check("Pillow", _check_pillow, results, "Pillow not available: {}")

    results["nanobot_available"] = await _run_check("Nanobot", _check_nanobot, results)

    return results


def bootstrap() -> Settings:
    """Initialize the application.

    Returns:
        Settings instance.

    Raises:
        SystemExit: If critical initialization fails.
    """
    print("[*] Starting Lobuddy...")

    # Load settings
    try:
        settings = get_settings()
    except Exception as e:
        print(f"[ERROR] Failed to load configuration: {e}")
        print("[*] Please create a .env file with your API key")
        print("   Copy .env.example to .env and fill in your values")
        sys.exit(1)

    # Setup logging
    setup_logging(settings)
    logger.info(f"Starting {settings.app_name} v0.1.0")

    # Create directories
    create_directories(settings)

    return settings


async def async_bootstrap() -> tuple[Settings, dict]:
    """Async initialization with health checks.

    Returns:
        Tuple of (Settings, health_check_results).
    """
    settings = bootstrap()
    health_results = await health_check(settings)

    # Print summary
    print("\n[SUMMARY] Health Check Summary:")
    print(f"  Configuration: {'[OK]' if health_results['config_loaded'] else '[FAIL]'}")
    print(f"  Workspace: {'[OK]' if health_results['workspace_accessible'] else '[FAIL]'}")
    print(f"  Database: {'[OK]' if health_results['database_ready'] else '[FAIL]'}")
    pillow_status = (
        "[OK]"
        if health_results["pillow_available"] is True
        else ("[FAIL]" if health_results["pillow_available"] is False else "[SKIP]")
    )
    print(f"  Pillow: {pillow_status}")
    print(f"  Nanobot: {'[OK]' if health_results['nanobot_available'] else '[FAIL]'}")

    if health_results["errors"]:
        print("\n[!] Warnings:")
        for error in health_results["errors"]:
            print(f"  - {error}")

    if not health_results["nanobot_available"]:
        print("\n[CRITICAL] Nanobot is not available")
        print("   Please check your .env configuration and API key")
        sys.exit(1)

    if settings.llm_multimodal_model and not health_results["pillow_available"]:
        print("\n[CRITICAL] Pillow is required for image analysis but is not available")
        print("   Please install it: pip install 'Pillow>=10.0.0'")
        sys.exit(1)

    print(f"\n[SUCCESS] {settings.app_name} is ready!")
    return settings, health_results
