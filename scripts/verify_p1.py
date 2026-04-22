"""Verification script for P1 issues."""

import re
from pathlib import Path


def verify_p1_9():
    print("=== P1 #9: Circular Dependency ===")
    files = [
        ("core/tasks/task_manager.py", "from app.config"),
        ("core/agent/nanobot_adapter.py", "from app.config"),
        ("core/agent/config_builder.py", "from app.config"),
        ("app/config.py", "from core"),
        ("core/storage/db.py", "from app.config"),
    ]
    for filepath, pattern in files:
        try:
            with open(filepath, "r") as f:
                for i, line in enumerate(f, 1):
                    if pattern in line:
                        print(f"{filepath}:{i}: {line.strip()}")
        except FileNotFoundError:
            pass
    print()


def verify_p1_11():
    print("=== P1 #11: Shared State Without Locks ===")
    for filepath in [
        "core/runtime/token_meter.py",
        "core/abilities/ability_system.py",
        "core/tasks/task_manager.py",
    ]:
        try:
            with open(filepath, "r") as f:
                content = f.read()
                has_lock = "Lock" in content or "Mutex" in content
                print(f"{filepath}: has_lock={has_lock}")
        except FileNotFoundError:
            pass
    print()


def verify_p1_12():
    print("=== P1 #12: Missing Transactions ===")
    with open("core/storage/chat_repo.py", "r") as f:
        lines = f.readlines()
        for i, line in enumerate(lines[198:223], start=199):
            if "commit" in line.lower():
                print(f"chat_repo.py:{i}: {line.strip()}")

    with open("core/storage/task_repo.py", "r") as f:
        lines = f.readlines()
        for i, line in enumerate(lines[55:75], start=56):
            if "commit" in line.lower() or 'f"' in line:
                print(f"task_repo.py:{i}: {line.strip()}")
    print()


def verify_p1_15():
    print("=== P1 #15: Image DoS ===")
    with open("core/agent/image_validation.py", "r") as f:
        lines = f.readlines()
        for i, line in enumerate(lines[53:102], start=54):
            if "while " in line or "quality" in line or "scale" in line:
                print(f"image_validation.py:{i}: {line.strip()}")
    print()


def verify_p1_16():
    print("=== P1 #16: Asset Manager ===")
    with open("ui/asset_manager.py", "r") as f:
        for i, line in enumerate(f, 1):
            if any(k in line for k in ["_pixmap_cache", "__init__", "get_tray_movie", "isNull"]):
                if i <= 30 or i >= 160:
                    print(f"asset_manager.py:{i}: {line.strip()}")
    print()


def verify_p1_19():
    print("=== P1 #19: Silent Exceptions ===")
    files = [
        ("app/config.py", "except Exception"),
        ("core/storage/pet_repo.py", "except Exception"),
        ("core/storage/settings_repo.py", "except"),
        ("core/storage/db.py", "except"),
    ]
    for filepath, pattern in files:
        try:
            with open(filepath, "r") as f:
                lines = f.readlines()
                for i, line in enumerate(lines, 1):
                    if pattern in line:
                        # Check if next line is pass
                        if i < len(lines) and "pass" in lines[i].lower():
                            print(f"{filepath}:{i}: {line.strip()}")
                            print(f"{filepath}:{i + 1}: {lines[i].strip()}")
        except FileNotFoundError:
            pass
    print()


if __name__ == "__main__":
    verify_p1_9()
    verify_p1_11()
    verify_p1_12()
    verify_p1_15()
    verify_p1_16()
    verify_p1_19()
