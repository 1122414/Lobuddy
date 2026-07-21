#!/usr/bin/env python
"""功能测试脚本 - 验证 Lobuddy 5.8 Skill Lab 功能。

运行方式:
    python tests/test_skill_lab_functional.py

此脚本执行以下验证:
1. P2-D1: Skill 实验室 MVP
   - 技能创建、启用、禁用、归档
   - 内容查看、事件查看
   - 按状态列出技能
2. P2-D2: Skill 候选审核
   - 候选创建、批准、拒绝
   - 状态转换验证
   - 低置信度自动拒绝
3. P2-D3: Skill 测试沙箱
   - 静态校验（frontmatter、触发规则、危险指令、secret）
4. P2-D4: 使用反馈接口预留
   - 事件定义和空 sink 验证
"""

import tempfile
from pathlib import Path


def setup_test_env():
    """创建临时测试环境."""
    tmp = Path(tempfile.mkdtemp(prefix="lobuddy_skill_test_"))
    return tmp


def test_skill_lab_mvp():
    """P2-D1: Skill 实验室 MVP 功能测试."""
    print("\n=== P2-D1: Skill 实验室 MVP ===")
    tmp = setup_test_env()

    from core.config import Settings
    from core.storage.db import Database
    from core.skills.skill_manager import SkillManager
    from core.skills.skill_schema import SkillRecord, SkillStatus

    settings = Settings(
        llm_api_key="test",
        data_dir=tmp / "data",
        logs_dir=tmp / "logs",
        workspace_path=tmp / "workspace",
        skill_archive_dir=tmp / "archive",
    )
    db = Database(settings)
    mgr = SkillManager(settings, db)

    # 创建技能
    print("1. 创建技能...")
    record = SkillRecord(id="s1", name="test-skill", path="", description="Test skill")
    created = mgr.create_skill(record, "# Test Skill\n\nThis is a test skill.")
    assert created.name == "test-skill", "技能创建失败"
    print("   ✓ 技能创建成功")

    # 查看内容
    print("2. 查看技能内容...")
    content = mgr.get_content("s1")
    assert "# Test Skill" in content, "内容查看失败"
    print("   ✓ 内容查看成功")

    # 查看事件
    print("3. 查看技能事件...")
    events = mgr.get_events("s1")
    assert len(events) >= 1, "事件记录失败"
    assert events[0].event_type == "create", "事件类型错误"
    print(f"   ✓ 事件查看成功 (共 {len(events)} 条事件)")

    # 禁用技能
    print("4. 禁用技能...")
    ok = mgr.disable_skill("s1")
    assert ok, "禁用失败"
    skill = mgr.get_skill("s1")
    assert skill.status == SkillStatus.DISABLED, "状态未变为 DISABLED"
    print("   ✓ 技能禁用成功")

    # 启用技能
    print("5. 启用技能...")
    ok = mgr.enable_skill("s1")
    assert ok, "启用失败"
    skill = mgr.get_skill("s1")
    assert skill.status == SkillStatus.ACTIVE, "状态未变为 ACTIVE"
    print("   ✓ 技能启用成功")

    # 归档技能
    print("6. 归档技能...")
    ok = mgr.archive_skill("s1")
    assert ok, "归档失败"
    skill = mgr.get_skill("s1")
    assert skill.status == SkillStatus.ARCHIVED, "状态未变为 ARCHIVED"
    print("   ✓ 技能归档成功")

    # 按状态列出
    print("7. 按状态列出技能...")
    archived = mgr.list_skills(status=SkillStatus.ARCHIVED)
    assert len(archived) == 1, "列出归档技能失败"
    print("   ✓ 状态过滤列出成功")

    print("✅ P2-D1 所有测试通过")


def test_candidate_review():
    """P2-D2: Skill 候选审核功能测试."""
    print("\n=== P2-D2: Skill 候选审核 ===")
    tmp = setup_test_env()

    from core.config import Settings
    from core.storage.db import Database
    from core.skills.skill_manager import SkillManager
    from core.skills.skill_schema import SkillCandidate, CandidateStatus

    settings = Settings(
        llm_api_key="test",
        data_dir=tmp / "data",
        logs_dir=tmp / "logs",
        workspace_path=tmp / "workspace",
        skill_archive_dir=tmp / "archive",
    )
    db = Database(settings)
    mgr = SkillManager(settings, db)

    # 创建候选
    print("1. 创建候选...")
    candidate = SkillCandidate(
        id="c1",
        title="Test Candidate",
        rationale="Useful skill",
        proposed_name="test-candidate",
        proposed_content=(
            "---\nname: test-candidate\ndescription: A test skill\n---\n\n"
            "# Test\n\n## Trigger\n\nWhen user asks about testing.\n"
        ),
        confidence=0.8,
    )
    mgr.create_candidate(candidate)
    loaded = mgr.get_candidate("c1")
    assert loaded.status == CandidateStatus.PENDING, "候选状态应为 PENDING"
    print("   ✓ 候选创建成功")

    # 拒绝候选
    print("2. 拒绝候选...")
    ok = mgr.reject_candidate("c1", "Not useful enough")
    assert ok, "拒绝失败"
    loaded = mgr.get_candidate("c1")
    assert loaded.status == CandidateStatus.REJECTED, "状态未变为 REJECTED"
    assert loaded.reject_reason == "Not useful enough", "拒绝原因未保存"
    print("   ✓ 候选拒绝成功")

    # 创建新候选并批准
    print("3. 创建并批准候选...")
    candidate2 = SkillCandidate(
        id="c2",
        title="Good Candidate",
        rationale="Good skill",
        proposed_name="good-skill",
        proposed_content=(
            "---\nname: good-skill\ndescription: A good skill\n---\n\n"
            "# Good\n\n## Trigger\n\nWhen the user requests this workflow.\n\n"
            "## Workflow\n\n1. Inspect the request.\n2. Verify the result.\n"
        ),
        confidence=0.8,
    )
    mgr.create_candidate(candidate2)
    created = mgr.approve_candidate("c2")
    assert created is not None, "批准失败"
    assert created.status.value == "active", "技能未激活"
    print("   ✓ 候选批准成功")

    # 低置信度候选自动拒绝
    print("4. 低置信度候选自动拒绝...")
    candidate3 = SkillCandidate(
        id="c3",
        title="Low Confidence",
        rationale="Low confidence",
        proposed_name="low-conf",
        proposed_content="---\nname: low-conf\n---\n\n# Low\n",
        confidence=0.1,
    )
    mgr.create_candidate(candidate3)
    result = mgr.approve_candidate("c3")
    assert result is None, "低置信度候选不应被批准"
    print("   ✓ 低置信度候选正确被拒绝")

    # 统计
    print("5. 候选统计...")
    stats = mgr.get_candidate_stats()
    assert stats["approved"] == 1, "批准计数错误"
    assert stats["rejected"] == 1, "拒绝计数错误"
    print(f"   ✓ 统计正确: {stats}")

    print("✅ P2-D2 所有测试通过")


def test_validation_sandbox():
    """P2-D3: Skill 测试沙箱功能测试."""
    print("\n=== P2-D3: Skill 测试沙箱 ===")

    from core.skills.skill_validator import SkillValidator

    validator = SkillValidator()

    # 有效技能
    print("1. 验证有效技能...")
    valid_skill = """---
name: good-skill
description: A good skill
---

# Good Skill

## Trigger

When user asks about good things.

## Workflow

1. Do something good.
"""
    valid, errors = validator.validate_static(valid_skill)
    assert valid, f"有效技能验证失败: {errors}"
    print("   ✓ 有效技能通过验证")

    # 缺少 frontmatter
    print("2. 验证缺少 frontmatter...")
    invalid_skill = "# Bad Skill\n\nNo frontmatter here."
    valid, errors = validator.validate_static(invalid_skill)
    assert not valid, "缺少 frontmatter 应失败"
    assert any("frontmatter" in e.lower() for e in errors), "错误信息应包含 frontmatter"
    print("   ✓ 正确检测到缺少 frontmatter")

    # 缺少触发规则
    print("3. 验证缺少触发规则...")
    invalid_skill2 = """---
name: no-trigger
description: No trigger
---

# No Trigger

Just some content.
"""
    valid, errors = validator.validate_static(invalid_skill2)
    assert not valid, "缺少触发规则应失败"
    assert any("trigger" in e.lower() for e in errors), "错误信息应包含 trigger"
    print("   ✓ 正确检测到缺少触发规则")

    # 危险指令
    print("4. 验证危险指令...")
    dangerous_skill = """---
name: dangerous
description: Dangerous
---

# Dangerous

Run: rm -rf /
"""
    valid, errors = validator.validate_static(dangerous_skill)
    assert not valid, "危险指令应失败"
    assert any("dangerous" in e.lower() for e in errors), "错误信息应包含 dangerous"
    print("   ✓ 正确检测到危险指令")

    # Secret
    print("5. 验证 secret...")
    secret_skill = (
        """---
name: leaky
description: Leaky
---

# Leaky

API key: """
        + "sk-"
        + "abcdefghijklmnopqrstuvwxyz123456"
        + "\n"
    )
    valid, errors = validator.validate_static(secret_skill)
    assert not valid, "包含 secret 应失败"
    assert any("secret" in e.lower() or "sensitive" in e.lower() for e in errors), "错误信息应包含 secret"
    print("   ✓ 正确检测到 secret")

    print("✅ P2-D3 所有测试通过")


def test_usage_feedback_interface():
    """P2-D4: 使用反馈接口预留测试."""
    print("\n=== P2-D4: 使用反馈接口预留 ===")

    from core.skills.skill_usage import (
        SkillUsageEvent,
        SkillUsageEventType,
        NoOpSkillUsageSink,
        NanobotSkillHookAdapter,
    )

    # 事件创建
    print("1. 创建使用事件...")
    event = SkillUsageEvent(
        skill_id="s1",
        event_type=SkillUsageEventType.STARTED,
    )
    assert event.skill_id == "s1"
    assert event.event_type == SkillUsageEventType.STARTED
    print("   ✓ 事件创建成功")

    # No-op sink
    print("2. 测试 NoOpSink...")
    sink = NoOpSkillUsageSink()
    sink.record(event)
    events = sink.get_events()
    assert events == [], "NoOpSink 应返回空列表"
    print("   ✓ NoOpSink 正确无操作")

    # Hook adapter
    print("3. 测试 Hook Adapter...")
    adapter = NanobotSkillHookAdapter()
    adapter.emit(event)
    print("   ✓ Hook Adapter 占位符正常工作")

    print("✅ P2-D4 所有测试通过")


def run_all_tests():
    """运行所有功能测试."""
    print("=" * 60)
    print("Lobuddy 5.8 Skill Lab 功能测试")
    print("=" * 60)

    results = []
    try:
        results.append(("P2-D1", test_skill_lab_mvp()))
    except Exception as e:
        results.append(("P2-D1", False))
        print(f"❌ P2-D1 失败: {e}")

    try:
        results.append(("P2-D2", test_candidate_review()))
    except Exception as e:
        results.append(("P2-D2", False))
        print(f"❌ P2-D2 失败: {e}")

    try:
        results.append(("P2-D3", test_validation_sandbox()))
    except Exception as e:
        results.append(("P2-D3", False))
        print(f"❌ P2-D3 失败: {e}")

    try:
        results.append(("P2-D4", test_usage_feedback_interface()))
    except Exception as e:
        results.append(("P2-D4", False))
        print(f"❌ P2-D4 失败: {e}")

    print("\n" + "=" * 60)
    print("测试结果汇总:")
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {name}: {status}")

    all_passed = all(passed for _, passed in results)
    if all_passed:
        print("\n🎉 所有测试通过!")
    else:
        print("\n⚠️ 部分测试失败，请检查上方错误信息。")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
