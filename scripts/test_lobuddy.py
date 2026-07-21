#!/usr/bin/env python
"""Lobuddy functional test script.

Usage:
    python scripts/test_lobuddy.py

This script runs a quick functional verification of core Lobuddy features
without requiring a display server or API keys.
"""

import os
import py_compile
import subprocess
import sys
from pathlib import Path


def run_command(cmd, description, optional=False):
    """Run a shell command and report success/failure.

    Args:
        cmd: Command list to execute.
        description: Human-readable test description.
        optional: If True, failure is reported but does not fail the suite.
    """
    print("\n" + "=" * 60)
    print("Testing: {}".format(description))
    print("Command: {}".format(" ".join(cmd)))
    print("=" * 60)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            print("PASS")
            if result.stdout:
                print(result.stdout[:500])
            return True
        else:
            print("FAIL (exit code {})".format(result.returncode))
            if result.stdout:
                print("STDOUT:", result.stdout[:500])
            if result.stderr:
                print("STDERR:", result.stderr[:500])
            if optional:
                print("[WARNING] Optional check failed - continuing")
                return True
            return False
    except subprocess.TimeoutExpired:
        print("FAIL (timeout)")
        return False if not optional else True
    except FileNotFoundError:
        print("SKIP (command not found: {})".format(cmd[0]))
        if optional:
            return True
        return False
    except Exception as e:
        print("FAIL ({})".format(e))
        return False if not optional else True


def compile_all_python():
    """Compile all Python files in app/, core/, ui/, tests/."""
    print("\n" + "=" * 60)
    print("Testing: Python syntax compilation")
    print("=" * 60)
    failed = []
    for root in ["app", "core", "ui", "tests"]:
        path = Path(root)
        if not path.exists():
            print("  Skip: {} not found".format(root))
            continue
        for py_file in path.rglob("*.py"):
            try:
                py_compile.compile(str(py_file), doraise=True)
            except py_compile.PyCompileError as e:
                failed.append((str(py_file), str(e)))
    if failed:
        print("FAIL - {} file(s) failed compilation:".format(len(failed)))
        for f, err in failed[:5]:
            print("  {}: {}".format(f, err))
        return False
    print("PASS - all Python files compiled successfully")
    return True


def main():
    """Run all functional tests and return exit code."""
    print("Lobuddy Functional Test Suite")
    print("=" * 60)

    os.environ.setdefault("LLM_API_KEY", "dummy-test-key")
    os.environ.setdefault("LLM_BASE_URL", "https://api.openai.com/v1")

    tests = [
        (["python", "-m", "ruff", "check", "."], "Code linting (ruff)", True),
        (["python", "-m", "black", "--check", "."], "Code formatting (black)", True),
        (None, "Python syntax compilation", False),
        (["python", "-m", "pytest", "tests/test_tool_policy.py", "-q"], "Security policy tests", False),
        (["python", "-m", "pytest", "tests/test_migrations.py", "-q"], "Database migration tests", False),
        (["python", "-m", "pytest", "tests/test_ui_smoke.py", "-q"], "UI smoke tests", False),
        (["python", "-m", "pytest", "tests/test_security_fixes.py", "-q"], "Security fix tests", False),
        (["python", "-m", "app.health"], "Health check", False),
    ]

    results = []
    for item in tests:
        if item[0] is None:
            results.append(compile_all_python())
        else:
            cmd, desc, optional = item
            results.append(run_command(cmd, desc, optional))

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print("Results: {}/{} tests passed".format(passed, total))
    print("=" * 60)

    if passed == total:
        print("\n[SUCCESS] All functional tests passed!")
        return 0
    else:
        print("\n[WARNING] Some tests failed. Review output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
