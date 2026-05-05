#!/usr/bin/env python
"""HITL 功能测试脚本 — 验证危险命令人工确认端到端链路。

运行方式:
    python test_hitl_feature.py

测试内容:
    1. ToolPolicy 三态分类 (ALLOW/HITL_REQUIRED/DENY)
    2. SafetyGuardrails 路径级判定
    3. HITL 审批协议 (DenyAll 默认拒绝 + 超时)
    4. 向后兼容性 (旧 API 不变)
    5. 模块可导入性

输出: 每个测试的 PASS/FAIL 状态，最终统计。
"""

import asyncio
import sys
import os
import tempfile
from pathlib import Path

TESTS_PASSED = 0
TESTS_FAILED = 0


def check(condition, name):
    global TESTS_PASSED, TESTS_FAILED
    if condition:
        TESTS_PASSED += 1
        print(f"  PASS {name}")
    else:
        TESTS_FAILED += 1
        print(f"  FAIL {name}")


def run_async(coro):
    return asyncio.run(coro)


def main():
    global TESTS_PASSED, TESTS_FAILED
    print("=" * 60)
    print("Lobuddy 5.5 HITL 功能测试")
    print("=" * 60)

    # ---- Test 1: 模块可导入 ----
    print("\n[1] 模块可导入性")
    try:
        from core.safety.command_risk import (
            CommandRiskAction,
            CommandRiskAssessment,
            HumanApprovalDenied,
        )
        from core.tools.tool_policy import ToolPolicy
        from core.safety.guardrails import SafetyGuardrails
        from core.safety.hitl_approval import (
            DenyAllHitlApprovalProvider,
            HitlApprovalDecision,
            HitlApprovalRequest,
            request_approval_with_timeout,
        )
        check(True, "所有核心模块可导入")
    except Exception as e:
        check(False, f"模块导入失败: {e}")

    # ---- Test 2: ToolPolicy 三态分类 ----
    print("\n[2] ToolPolicy 三态分类")
    policy = ToolPolicy()

    check(policy.assess_command_risk("ls -la").action == CommandRiskAction.ALLOW, "ls -la → ALLOW")
    check(policy.assess_command_risk("cat README.md").action == CommandRiskAction.ALLOW, "cat README.md → ALLOW")
    check(policy.assess_command_risk("rm temp.txt").action == CommandRiskAction.HITL_REQUIRED, "rm temp.txt → HITL_REQUIRED")
    check(policy.assess_command_risk("rm -r temp_dir").action == CommandRiskAction.HITL_REQUIRED, "rm -r temp_dir → HITL_REQUIRED")
    check(policy.assess_command_risk("del /q temp.txt").action == CommandRiskAction.HITL_REQUIRED, "del /q temp.txt → HITL_REQUIRED")
    check(policy.assess_command_risk("format C:").action == CommandRiskAction.DENY, "format C: → DENY")
    check(policy.assess_command_risk("shutdown -h now").action == CommandRiskAction.DENY, "shutdown -h now → DENY")
    check(policy.assess_command_risk("powershell -enc abc").action == CommandRiskAction.DENY, "powershell -enc abc → DENY")
    check(policy.assess_command_risk('python -c "print(1)"').action == CommandRiskAction.DENY, 'python -c → DENY')
    check(policy.assess_command_risk("echo ok && rm temp.txt").action == CommandRiskAction.DENY, "echo && rm → DENY")

    # ---- Test 3: SafetyGuardrails 路径判定 ----
    print("\n[3] SafetyGuardrails 路径判定")
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        guardrails = SafetyGuardrails(ws)

        safe_file = ws / "temp.txt"
        safe_file.write_text("test")

        check(guardrails.assess_shell_command(f"rm {safe_file}").action == CommandRiskAction.HITL_REQUIRED,
              "workspace 内文件删除 → HITL_REQUIRED")
        check(guardrails.assess_shell_command("rm /etc/passwd").action == CommandRiskAction.DENY,
              "workspace 外文件删除 → DENY")
        check(guardrails.assess_shell_command("ls -la").action == CommandRiskAction.ALLOW,
              "安全命令 → ALLOW")

        result = guardrails.assess_shell_command(f"rm -rf {ws}")
        check(result.action == CommandRiskAction.DENY,
              f"workspace 根目录删除 → DENY")

    # ---- Test 4: HITL 审批协议 ----
    print("\n[4] HITL 审批协议")
    provider = DenyAllHitlApprovalProvider()
    request = HitlApprovalRequest.create(
        session_id="test",
        tool_name="exec",
        command="rm temp.txt",
        reason="delete command",
    )
    decision = run_async(provider.request_approval(request))
    check(decision.approved is False, "DenyAll 默认拒绝")
    check("not available" in decision.reason, "拒绝原因正确")

    class StubProvider:
        async def request_approval(self, req):
            await asyncio.sleep(2)

    slow_req = HitlApprovalRequest.create(
        session_id="test",
        tool_name="exec",
        command="rm tmp.txt",
        timeout_seconds=1,
    )
    timeout_decision = run_async(request_approval_with_timeout(StubProvider(), slow_req))
    check(timeout_decision.approved is False, "超时自动拒绝")
    check("timed out" in timeout_decision.reason, "超时原因正确")

    # ---- Test 5: 向后兼容性 ----
    print("\n[5] 向后兼容性")
    check(policy.is_command_dangerous("rm -rf /") is True, "is_command_dangerous 不变")
    check(policy.is_command_dangerous("format C:") is True, "format C: 仍为危险")
    check(policy.is_command_dangerous("ls -la") is False, "ls -la 仍为安全")

    allowed, reason = policy.validate_command("git status")
    check(allowed is True, "validate_command git status 允许")
    blocked, reason = policy.validate_command("rm -rf /")
    check(blocked is False, "validate_command rm -rf 阻断")

    # ---- Test 6: 异常处理 ----
    print("\n[6] 异常处理")
    try:
        raise HumanApprovalDenied("user rejected")
    except HumanApprovalDenied as e:
        check(isinstance(e, RuntimeError), "HumanApprovalDenied 是 RuntimeError")
        check("rejected" in str(e).lower(), "异常信息正确")

    # ---- 总结 ----
    print("\n" + "=" * 60)
    total = TESTS_PASSED + TESTS_FAILED
    print(f"总计: {total} | 通过: {TESTS_PASSED} | 失败: {TESTS_FAILED}")
    if TESTS_FAILED == 0:
        print("[SUCCESS] All tests passed!")
        print("\n手动验证清单:")
        print("  1. 启动 Lobuddy: python -m app.main")
        print("  2. 输入任务: 请删除 workspace/temp_test.txt")
        print("  3. 预期: 弹出确认框，显示命令和路径")
        print("  4. 点击'取消执行': 命令不应运行")
        print("  5. 再试一次，点击'确认执行': 命令应执行")
        print("  6. 输入: 请执行 format C:")
        print("  7. 预期: 直接阻断，不弹框")
        return 0
    else:
        print("❌ 有测试失败，请检查！")
        return 1


if __name__ == "__main__":
    sys.exit(main())
