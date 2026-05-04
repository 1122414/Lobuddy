#!/usr/bin/env python3
"""Lobuddy 5.4 执行能力升级 —— 功能验收脚本

Run: python tests/run_54_execution_tests.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_tests(name: str, paths: list[str]) -> bool:
    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")
    result = subprocess.run(
        ["pytest", "-q", "--tb=short"] + paths,
        cwd=str(ROOT), capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0


def main() -> int:
    print("Lobuddy 5.4 执行能力升级 —— 验收测试")
    print(f"Workdir: {ROOT}\n")

    suites = [
        ("Execution Intent Router", ["tests/test_execution_intent.py"]),
        ("Execution Governance Hook", ["tests/test_execution_governance_hook.py"]),
        ("Local Tools (resolve + open)", ["tests/test_54_execution_regression.py"]),
        ("Tool Policy Chain Detection", ["tests/test_tool_policy_54.py"]),
    ]

    results: list[tuple[str, bool]] = []
    for name, paths in suites:
        ok = run_tests(name, paths)
        results.append((name, ok))

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'=' * 60}")
    print(f"  VERDICT: {passed}/{total} suites passed")
    print(f"{'=' * 60}")
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
