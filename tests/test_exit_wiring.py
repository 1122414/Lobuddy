import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_exit_wiring():
    errors = []

    main_path = Path(__file__).parent.parent / "app" / "main.py"
    main_content = main_path.read_text(encoding="utf-8")

    if "system_tray.exit_requested.connect" not in main_content:
        errors.append("Missing: system_tray.exit_requested connection")
    else:
        print("OK: SystemTray exit signal is connected")

    if "pet_window.force_close()" not in main_content:
        errors.append("Missing: pet_window.force_close() on exit")
    else:
        print("OK: pet_window.force_close() called on exit")

    if "task_panel.close()" not in main_content:
        errors.append("Missing: task_panel.close() on exit")
    else:
        print("OK: task_panel.close() called on exit")

    if "app.exit(0)" not in main_content:
        errors.append("Missing: app.exit(0)")
    else:
        print("OK: app.exit(0) present")

    if "threading.Timer(" not in main_content or "os._exit(0)" not in main_content:
        errors.append("Missing: kill-switch timer in on_exit_requested")
    else:
        print("OK: kill-switch timer present")

    if (
        "try:" in main_content
        and "exit_code = app.exec()" in main_content
        and "finally:" in main_content
    ):
        print("OK: app.exec() wrapped in try/finally")
    else:
        errors.append("Missing try/finally around app.exec()")

    if "SetConsoleCtrlHandler" in main_content:
        print("OK: Windows console close handler registered")
    else:
        errors.append("Missing SetConsoleCtrlHandler")

    factory_path = Path(__file__).parent.parent / "core" / "agent" / "subagent_factory.py"
    factory_content = factory_path.read_text(encoding="utf-8")

    if "threading.Thread" in factory_content and "daemon=True" in factory_content:
        print("OK: SubagentFactory uses daemon thread")
    else:
        errors.append("SubagentFactory not using daemon thread")

    if "asyncio.to_thread" in factory_content:
        errors.append("asyncio.to_thread still present (non-daemon thread source)")
    else:
        print("OK: asyncio.to_thread removed from subagent_factory")

    hotkey_path = Path(__file__).parent.parent / "ui" / "hotkey_manager.py"
    hotkey_content = hotkey_path.read_text(encoding="utf-8")

    if "_should_stop" in hotkey_content:
        print("OK: HotkeyWorker has _should_stop flag")
    else:
        errors.append("Missing _should_stop in HotkeyWorker")

    if errors:
        print("\nERRORS FOUND:")
        for e in errors:
            print(f"  - {e}")
    assert not errors, "Exit wiring validation failed"
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    test_exit_wiring()
