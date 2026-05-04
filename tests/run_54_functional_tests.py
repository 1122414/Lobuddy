#!/usr/bin/env python3
"""Lobuddy 5.4 记忆边界补全 —— 功能测试脚本

Run: python tests/run_54_functional_tests.py

此脚本运行 5.4 全部验收测试，与 plans/5.4 中的验收命令对应。
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_tests(name: str, paths: list[str], verbose: bool = False) -> bool:
    """Run pytest and return True if all passed."""
    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")

    args = ["pytest"]
    if verbose:
        args.append("-v")
    args.extend(paths)
    args.extend(["-q", "--tb=short"])

    result = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True)

    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    return result.returncode == 0


def run_compile_checks() -> bool:
    """Run py_compile on all key modules."""
    print(f"\n{'=' * 60}")
    print("  Compile Verification")
    print(f"{'=' * 60}")

    modules = [
        "core/agent/nanobot_adapter.py",
        "core/agent/tools/session_search_tool.py",
        "core/memory/memory_write_gateway.py",
        "core/memory/memory_service.py",
        "core/memory/exit_analyzer.py",
        "tests/test_memory_write_boundary.py",
    ]

    all_ok = True
    for mod in modules:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(ROOT / mod)],
            cwd=str(ROOT), capture_output=True, text=True)
        status = "OK" if result.returncode == 0 else f"FAIL ({result.stderr.strip()})"
        print(f"  py_compile {mod}: {status}")
        if result.returncode != 0:
            all_ok = False
    return all_ok


def main() -> int:
    print("Lobuddy 5.4 记忆边界补全 —— 验收测试")
    print(f"Workdir: {ROOT}")
    print()

    results: list[tuple[str, bool]] = []

    # ---- Suite 1: Memory write boundary (core 5.4 tests) ----
    ok = run_tests(
        "Suite 1: Memory Write Boundary (28 tests)",
        ["tests/test_memory_write_boundary.py"],
        verbose=True,
    )
    results.append(("Write Boundary", ok))

    # ---- Suite 2: Session search regression ----
    ok = run_tests(
        "Suite 2: Session Search (20 tests)",
        ["tests/test_session_search.py", "tests/test_session_search_tool.py"],
    )
    results.append(("Session Search", ok))

    # ---- Suite 3: Memory selectors ----
    ok = run_tests(
        "Suite 3: Memory Selectors + Lint + Skill (16 tests)",
        ["tests/test_memory_selector.py", "tests/test_memory_lint.py",
         "tests/test_skill_selector.py"],
    )
    results.append(("Selectors + Lint + Skill", ok))

    # ---- Suite 4: 5.3 verification ----
    ok = run_tests(
        "Suite 4: 5.3 Phase 1 Verification (34 tests)",
        ["tests/test_53_phase1_verification.py", "tests/test_exit_wiring.py"],
    )
    results.append(("5.3 Verification", ok))

    # ---- Suite 5: Memory core tests ----
    ok = run_tests(
        "Suite 5: Memory Core (49 tests)",
        ["tests/test_memory_service.py", "tests/test_memory_repository.py",
         "tests/test_user_profile_manager.py", "tests/test_skill_manager.py"],
    )
    results.append(("Memory Core", ok))

    # ---- Suite 6: Compile checks ----
    ok = run_compile_checks()
    results.append(("Compile Checks", ok))

    # ---- Summary ----
    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'=' * 60}")
    print(f"  VERDICT: {passed}/{total} suites passed")
    print(f"{'=' * 60}")
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
