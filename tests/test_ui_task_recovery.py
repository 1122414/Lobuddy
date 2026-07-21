"""Offscreen UI tests for explicit Task Recovery review."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from core.models.task_recovery import (
    RecoveryEvidence,
    RecoveryTone,
    TaskRecoveryReview,
)
from ui.task_recovery_dialog import TaskRecoveryDialog


def _ensure_qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _review(*, eligible: bool = True) -> TaskRecoveryReview:
    return TaskRecoveryReview(
        task_id="run-1",
        eligible=eligible,
        fingerprint="a" * 64,
        headline=(
            "可以安全开始第 2 次尝试"
            if eligible
            else "这项工作暂时不能直接重试"
        ),
        summary="旧证据只用于解释，不会成为自动重放指令。",
        reason="" if eligible else "图片需要重新选择。",
        next_attempt_no=2,
        progress=0.46,
        possible_side_effects=True,
        evidence=[
            RecoveryEvidence(
                label="上次进展",
                value="约 46%",
                detail="已经进入设置页面",
                tone=RecoveryTone.SAFE,
            ),
            RecoveryEvidence(
                label="电脑操作",
                value="1 个已记录动作",
                detail="所有授权都要重新确认",
                tone=RecoveryTone.ATTENTION,
            ),
            RecoveryEvidence(
                label="工具证据",
                value="2 次工具调用",
                detail="不会作为重放脚本",
            ),
        ],
        safeguards=[
            "旧 Task Run 与 Run Update 保持不变",
            "不会重放旧点击、输入、命令或临时屏幕像素",
            "新 Task Run 会重新申请所有必要授权",
        ],
    )


def test_recovery_dialog_requires_explicit_acknowledgement():
    _ensure_qapp()
    dialog = TaskRecoveryDialog(_review())

    assert dialog._confirm_btn.text() == "开始第 2 次尝试"
    assert dialog._confirm_btn.isEnabled() is False
    labels = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "上一次留下的证据" in labels
    assert "可能已经改变了外部状态" in labels
    assert "不会重放旧点击" in labels

    dialog._acknowledgement.setChecked(True)
    assert dialog._confirm_btn.isEnabled() is True
    dialog._confirm_btn.click()
    assert dialog.result() == TaskRecoveryDialog.DialogCode.Accepted


def test_ineligible_review_has_no_confirmation_checkbox():
    _ensure_qapp()
    dialog = TaskRecoveryDialog(_review(eligible=False))

    assert dialog._acknowledgement.isHidden()
    assert dialog._confirm_btn.text() == "返回对话"
    dialog.close()
