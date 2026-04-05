"""Bootstrap module for Lobuddy application initialization."""

import sys
from pathlib import Path

from loguru import logger

from app.config import Settings, get_settings
from core.agent.nanobot_adapter import NanobotAdapter
from core.storage.db import init_database
from core.storage.pet_repo import PetRepository


def setup_logging(settings: Settings) -> None:
    """Configure logging system."""
    logs_dir = settings.logs_dir
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / "lobuddy.log"

    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>",
    )
    logger.add(
        log_file,
        level=settings.log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="7 days",
    )


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


async def health_check(settings: Settings) -> dict:
    """Run health checks on application dependencies.

    Returns:
        Dictionary with health check results.
    """
    results = {
        "config_loaded": False,
        "nanobot_available": False,
        "workspace_accessible": False,
        "database_ready": False,
        "errors": [],
    }

    # Check config
    try:
        if settings.llm_api_key and settings.llm_api_key != "your_api_key_here":
            results["config_loaded"] = True
            logger.info("Configuration loaded successfully")
        else:
            results["errors"].append("LLM API key not configured")
            logger.warning("LLM API key not configured")
    except Exception as e:
        results["errors"].append(f"Config error: {e}")
        logger.error(f"Configuration error: {e}")

    # Check workspace
    try:
        workspace = settings.workspace_path
        workspace.mkdir(parents=True, exist_ok=True)
        test_file = workspace / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
        results["workspace_accessible"] = True
        logger.info(f"Workspace accessible: {workspace}")
    except Exception as e:
        results["errors"].append(f"Workspace error: {e}")
        logger.error(f"Workspace error: {e}")

    # Check database and pet
    try:
        init_database(settings)
        pet_repo = PetRepository()
        pet = pet_repo.get_or_create_pet()
        results["database_ready"] = True
        logger.info(f"Database ready, pet: {pet.name} (Lv{pet.level})")
    except Exception as e:
        results["errors"].append(f"Database error: {e}")
        logger.error(f"Database error: {e}")

    # Check nanobot
    try:
        adapter = NanobotAdapter(settings)
        nanobot_healthy = await adapter.health_check()
        results["nanobot_available"] = nanobot_healthy
        if nanobot_healthy:
            logger.info("Nanobot adapter initialized successfully")
        else:
            results["errors"].append("Nanobot initialization failed")
            logger.error("Nanobot adapter initialization failed")
    except Exception as e:
        results["errors"].append(f"Nanobot error: {e}")
        logger.error(f"Nanobot error: {e}")

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
    print(f"  Nanobot: {'[OK]' if health_results['nanobot_available'] else '[FAIL]'}")

    if health_results["errors"]:
        print("\n[!] Warnings:")
        for error in health_results["errors"]:
            print(f"  - {error}")

    if not health_results["nanobot_available"]:
        print("\n[CRITICAL] Nanobot is not available")
        print("   Please check your .env configuration and API key")
        sys.exit(1)

    print(f"\n[SUCCESS] {settings.app_name} is ready!")
    return settings, health_results
