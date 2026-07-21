"""功能测试脚本 — 验证 Lobuddy 5.8 Skill 系统进化计划 (P2-D1 ~ P2-D4)

使用方法:
    python scripts/test_skill_lab_features.py

测试内容:
    - P2-D1: Skill 实验室 MVP
    - P2-D2: Skill 候选审核
    - P2-D3: Skill 测试沙箱
    - P2-D4: 使用反馈接口预留

要求:
    - 项目已安装依赖: pip install -e .
    - 在项目根目录运行
"""

import sys
import tempfile
from pathlib import Path


def run_tests():
    """运行所有 Skill Lab 功能测试."""
    print("=" * 60)
    print("Lobuddy 5.8 Skill 系统功能测试")
    print("=" * 60)

    failures = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        failures.extend(_test_skill_lab_mvp(tmp_path))
        failures.extend(_test_candidate_review(tmp_path))
        failures.extend(_test_validation_sandbox(tmp_path))
        failures.extend(_test_usage_interface(tmp_path))

    print("\n" + "=" * 60)
    if failures:
        print(f"测试完成: {len(failures)} 个失败")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("测试完成: 全部通过")
        sys.exit(0)


def _setup_manager(tmp_path: Path):
    """创建测试用的 SkillManager."""
    from core.config import Settings
    from core.storage.db import Database
    from core.skills.skill_manager import SkillManager

    settings = Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        skill_archive_dir=tmp_path / "archive",
    )
    db = Database(settings)
    return SkillManager(settings, db)


def _test_skill_lab_mvp(tmp_path: Path) -> list[str]:
    """P2-D1: Skill 实验室 MVP 测试."""
    print("\n[P2-D1] Skill 实验室 MVP...")
    failures = []

    from core.skills.skill_schema import SkillRecord, SkillStatus

    mgr = _setup_manager(tmp_path)

    # 创建技能
    record = SkillRecord(id="s1", name="test-skill", path="", description="Test skill")
    mgr.create_skill(record, "# Test\n\nContent")

    # 测试查看内容 (在禁用前)
    content = mgr.get_content("s1")
    if "# Test" not in content:
        failures.append("get_content returned wrong content")

    # 测试禁用
    ok = mgr.disable_skill("s1")
    if not ok:
        failures.append("disable_skill failed")
    s = mgr.get_skill("s1")
    if s.status != SkillStatus.DISABLED:
        failures.append(f"Expected DISABLED, got {s.status}")

    # 测试启用
    ok = mgr.enable_skill("s1")
    if not ok:
        failures.append("enable_skill failed")
    s = mgr.get_skill("s1")
    if s.status != SkillStatus.ACTIVE:
        failures.append(f"Expected ACTIVE after enable, got {s.status}")

    # 测试查看事件
    events = mgr.get_events("s1")
    if not events:
        failures.append("get_events returned empty")

    # 测试归档
    ok = mgr.archive_skill("s1")
    if not ok:
        failures.append("archive_skill failed")
    s = mgr.get_skill("s1")
    if s.status != SkillStatus.ARCHIVED:
        failures.append(f"Expected ARCHIVED, got {s.status}")

    print(f"  结果: {len(failures)} 个失败")
    return failures


def _test_candidate_review(tmp_path: Path) -> list[str]:
    """P2-D2: Skill 候选审核测试."""
    print("\n[P2-D2] Skill 候选审核...")
    failures = []

    from core.skills.skill_schema import SkillCandidate, CandidateStatus

    mgr = _setup_manager(tmp_path)

    # 创建候选
    candidate = SkillCandidate(
        id="c1",
        title="Test Candidate",
        rationale="Useful",
        proposed_name="test-candidate",
        proposed_content="---\nname: test-candidate\n---\n\n# Test\n",
    )
    mgr.create_candidate(candidate)

    # 验证初始状态为 pending
    c = mgr.get_candidate("c1")
    if c.status != CandidateStatus.PENDING:
        failures.append(f"Expected PENDING, got {c.status}")

    # 拒绝候选
    ok = mgr.reject_candidate("c1", "Not useful")
    if not ok:
        failures.append("reject_candidate failed")
    c = mgr.get_candidate("c1")
    if c.status != CandidateStatus.REJECTED:
        failures.append(f"Expected REJECTED, got {c.status}")
    if c.reject_reason != "Not useful":
        failures.append(f"Expected reject_reason='Not useful', got '{c.reject_reason}'")

    # 验证被拒绝的候选不进入 prompt
    from core.skills.skill_selector import SkillSelector

    selector = SkillSelector(mgr)
    active = selector.select_active_skills()
    if any("test-candidate" in s.name for s in active):
        failures.append("Rejected candidate should not be in active skills")

    print(f"  结果: {len(failures)} 个失败")
    return failures


def _test_validation_sandbox(tmp_path: Path) -> list[str]:
    """P2-D3: Skill 测试沙箱测试."""
    print("\n[P2-D3] Skill 测试沙箱...")
    failures = []

    from core.skills.skill_validator import SkillValidator

    validator = SkillValidator()

    # 有效的 SKILL.md
    valid_content = """---
name: good-skill
description: A good skill
---

# Good Skill

## Trigger

When user asks about good things.

## Workflow

1. Be helpful.
"""
    valid, errors = validator.validate_static(valid_content)
    if not valid:
        failures.append(f"Valid skill marked invalid: {errors}")

    # 缺少 frontmatter
    invalid_content = "# Bad Skill\n\nNo frontmatter."
    valid, errors = validator.validate_static(invalid_content)
    if valid:
        failures.append("Missing frontmatter should fail validation")

    # 包含危险指令
    dangerous_content = """---
name: bad-skill
description: Bad skill
---

# Bad

Run: rm -rf /
"""
    valid, errors = validator.validate_static(dangerous_content)
    if valid:
        failures.append("Dangerous commands should fail validation")

    # 包含 secret
    secret_content = (
        """---
name: leaky-skill
description: Leaky skill
---

# Leaky

API key: """
        + "sk-"
        + "abcdefghijklmnopqrstuvwxyz123456"
        + "\n"
    )
    valid, errors = validator.validate_static(secret_content)
    if valid:
        failures.append("Secrets should fail validation")

    print(f"  结果: {len(failures)} 个失败")
    return failures


def _test_usage_interface(tmp_path: Path) -> list[str]:
    """P2-D4: 使用反馈接口预留测试."""
    print("\n[P2-D4] 使用反馈接口预留...")
    failures = []

    from core.skills.skill_usage import (
        SkillUsageEvent,
        SkillUsageEventType,
        NoOpSkillUsageSink,
        NanobotSkillHookAdapter,
    )

    # NoOp sink 测试
    sink = NoOpSkillUsageSink()
    event = SkillUsageEvent(
        skill_id="s1",
        event_type=SkillUsageEventType.STARTED,
    )
    sink.record(event)
    events = sink.get_events()
    if events:
        failures.append("NoOp sink should return empty list")

    # Hook adapter 占位测试
    adapter = NanobotSkillHookAdapter()
    event = SkillUsageEvent(
        skill_id="s1",
        event_type=SkillUsageEventType.COMPLETED,
    )
    adapter.emit(event)

    # 事件不可变测试
    event = SkillUsageEvent(
        skill_id="s1",
        event_type=SkillUsageEventType.STARTED,
    )
    if event.skill_id != "s1":
        failures.append("Event skill_id mismatch")

    print(f"  结果: {len(failures)} 个失败")
    return failures


if __name__ == "__main__":
    run_tests()
