"""Main entry point for Lobuddy application."""

import asyncio
import sys

from loguru import logger

from app.bootstrap import async_bootstrap
from app.config import Settings, get_settings
from core.agent.nanobot_adapter import AgentResult, NanobotAdapter


async def run_cli_test(settings: Settings) -> None:
    """Run a simple CLI test to verify nanobot integration."""
    print("\n🧪 Testing nanobot integration...")
    print("-" * 50)

    adapter = NanobotAdapter(settings)

    # Test prompt
    test_prompt = "Say hello and tell me your name."
    session_key = adapter.build_session_key("test-001")

    print(f"Prompt: {test_prompt}")
    print(f"Session: {session_key}")
    print("Running...")

    result = await adapter.run_task(test_prompt, session_key)

    print("\n📋 Result:")
    print(f"  Success: {result.success}")
    print(f"  Summary: {result.summary}")

    if result.success:
        print(f"\n📝 Full Output:\n{result.raw_output}")
    else:
        print(f"\n❌ Error: {result.error_message}")


async def interactive_mode(settings: Settings) -> None:
    """Run interactive CLI mode."""
    print(f"\n🐱 Welcome to {settings.app_name}!")
    print("Type your message or 'exit' to quit\n")

    adapter = NanobotAdapter(settings)
    session_key = adapter.build_session_key("interactive")

    while True:
        try:
            user_input = input("You: ").strip()

            if user_input.lower() in ("exit", "quit", "q"):
                print("👋 Goodbye!")
                break

            if not user_input:
                continue

            print("🤔 Thinking...")
            result = await adapter.run_task(user_input, session_key)

            if result.success:
                print(f"\n🐱 {settings.pet_name}: {result.raw_output}\n")
            else:
                print(f"\n❌ Error: {result.error_message}\n")

        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except EOFError:
            break


def main() -> None:
    """Main entry point."""
    try:
        settings, health = asyncio.run(async_bootstrap())

        # For now, run interactive mode
        # In future stages, this will launch the desktop pet UI
        asyncio.run(interactive_mode(settings))

    except Exception as e:
        logger.exception("Fatal error")
        print(f"\n💥 Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
