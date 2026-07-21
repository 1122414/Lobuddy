"""Auditable Skill Lab for Lobuddy's governed capability evolution."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.skills.skill_manager import SkillManager
from core.skills.skill_schema import (
    BehaviorSimulationStatus,
    CandidateSource,
    EvaluationCheckStatus,
    EvaluationStatus,
    ProvenanceStatus,
    SkillCandidate,
    SkillEvaluationReport,
    SkillRecord,
    SkillStatus,
)
from ui.theme import ThemeManager


class SkillLabPanel(QDialog):
    """Review proposals and control active, disabled, or archived skills."""

    skill_activated = Signal(str)
    proposals_changed = Signal(int)

    def __init__(
        self,
        manager: SkillManager,
        settings,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._manager = manager
        self._settings = settings
        self._cards: list[QFrame] = []
        self._tab_layouts: dict[object, QVBoxLayout] = {}
        self._init_ui()
        self._load_all()
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        self.refresh_theme()

    def _init_ui(self):
        self.setWindowTitle("能力进化实验室")
        self.setMinimumSize(720, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self._title = QLabel("能力进化实验室")
        self._title.setFont(QFont("Microsoft YaHei UI", 16, QFont.Weight.Bold))
        layout.addWidget(self._title)

        self._subtitle = QLabel("Lobuddy 只会把成功、安全的流程整理成提案；任何新能力都要经过你的审核才会启用。")
        self._subtitle.setWordWrap(True)
        layout.addWidget(self._subtitle)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("按名称搜索能力或提案…")
        self._search_input.textChanged.connect(self._on_search)
        layout.addWidget(self._search_input)

        self._tabs = QTabWidget()
        self._candidate_tab = self._create_tab("candidates")
        self._active_tab = self._create_tab(SkillStatus.ACTIVE)
        self._review_tab = self._create_tab(SkillStatus.NEEDS_REVIEW)
        self._disabled_tab = self._create_tab(SkillStatus.DISABLED)
        self._archived_tab = self._create_tab(SkillStatus.ARCHIVED)

        self._tabs.addTab(self._candidate_tab, "待审提案")
        self._tabs.addTab(self._active_tab, "已启用")
        self._tabs.addTab(self._review_tab, "待复核")
        self._tabs.addTab(self._disabled_tab, "已禁用")
        self._tabs.addTab(self._archived_tab, "已归档")
        layout.addWidget(self._tabs)

    def _create_tab(self, key: object) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName("skillLabScrollContent")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(8, 8, 8, 8)
        container_layout.setSpacing(8)
        self._tab_layouts[key] = container_layout
        scroll.setWidget(container)
        outer.addWidget(scroll)
        return tab

    def _load_all(self):
        self._cards.clear()
        candidates = self._manager.get_pending_candidates(limit=100)
        self._populate_candidates(candidates)
        for status in (
            SkillStatus.ACTIVE,
            SkillStatus.NEEDS_REVIEW,
            SkillStatus.DISABLED,
            SkillStatus.ARCHIVED,
        ):
            self._populate_skills(
                status,
                self._manager.list_skills(status=status, limit=100),
            )
        self._tabs.setTabText(0, f"待审提案 ({len(candidates)})")
        self.proposals_changed.emit(len(candidates))
        self._on_search(self._search_input.text())

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _populate_candidates(self, candidates: list[SkillCandidate]) -> None:
        layout = self._tab_layouts["candidates"]
        self._clear_layout(layout)
        if not candidates:
            layout.addWidget(self._empty_label("暂无待审提案。完成安全的多步骤任务后会在这里出现。"))
        for candidate in candidates:
            card = self._create_candidate_card(candidate)
            layout.addWidget(card)
            self._cards.append(card)
        layout.addStretch()

    def _populate_skills(
        self,
        status: SkillStatus,
        skills: list[SkillRecord],
    ) -> None:
        layout = self._tab_layouts[status]
        self._clear_layout(layout)
        if not skills:
            layout.addWidget(self._empty_label("这里暂时没有能力。"))
        for skill in skills:
            card = self._create_skill_card(skill, status)
            layout.addWidget(card)
            self._cards.append(card)
        layout.addStretch()

    @staticmethod
    def _empty_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("skillLabEmpty")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumHeight(100)
        return label

    def _create_candidate_card(self, candidate: SkillCandidate) -> QFrame:
        card = self._new_card(candidate.proposed_name)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        header = QHBoxLayout()
        name = QLabel(candidate.title)
        name.setObjectName("skillLabCardTitle")
        header.addWidget(name)
        header.addStretch()
        high_confidence = (
            candidate.confidence >= self._settings.skill_candidate_auto_approve_threshold
        )
        confidence = QLabel(
            f"{'高可信证据 · ' if high_confidence else '生成证据 '}" f"{candidate.confidence:.0%}"
        )
        confidence.setObjectName("skillLabBadge")
        header.addWidget(confidence)
        revision_badge = QLabel(f"提案 v{candidate.revision}")
        revision_badge.setObjectName("skillLabBadge")
        revision_badge.setProperty("candidate_revision_badge", True)
        header.addWidget(revision_badge)
        report = self._manager.get_latest_candidate_evaluation(
            candidate.id,
            current_content_only=True,
        )
        if report is not None:
            evaluation_badge = QLabel(f"隔离评测 {report.score}/100")
            evaluation_badge.setObjectName(
                "skillLabPassedBadge"
                if report.status == EvaluationStatus.PASSED
                else "skillLabBlockedBadge"
            )
            header.addWidget(evaluation_badge)
            behavior_badge = QLabel(f"行为模拟 {report.behavior.scenario_count} 场景")
            behavior_badge.setObjectName(
                "skillLabPassedBadge"
                if (report.behavior.status == BehaviorSimulationStatus.PASSED)
                else "skillLabBlockedBadge"
            )
            behavior_badge.setProperty("behavior_badge", True)
            header.addWidget(behavior_badge)
        provenance_badge = QLabel(self._provenance_badge_text(candidate, report))
        provenance_badge.setObjectName(
            "skillLabBlockedBadge"
            if (
                candidate.source_kind == CandidateSource.SUCCESSFUL_TASK
                and (report is None or report.provenance.status != ProvenanceStatus.VERIFIED)
            )
            else "skillLabPassedBadge"
        )
        provenance_badge.setProperty("provenance_badge", True)
        header.addWidget(provenance_badge)
        layout.addLayout(header)

        rationale = QLabel(candidate.rationale)
        rationale.setObjectName("skillLabDescription")
        rationale.setWordWrap(True)
        layout.addWidget(rationale)

        tools = candidate.evidence.get("tools", [])
        source_text = (
            "自动进化" if candidate.source_kind == CandidateSource.SUCCESSFUL_TASK else "手动 / 导入"
        )
        task_text = (
            f" · Task Run {candidate.source_task_id[:8]}" if candidate.source_task_id else ""
        )
        evidence = QLabel(
            f"来源：{source_text}{task_text} · 声明 {len(tools)} 种工具"
            + (f" · {', '.join(tools)}" if tools else "")
        )
        evidence.setObjectName("skillLabMeta")
        evidence.setWordWrap(True)
        layout.addWidget(evidence)

        diff = self._manager.get_candidate_diff(candidate.id)
        if diff is not None and diff.changed:
            diff_summary = QLabel(
                f"版本差异：v{diff.from_revision} → v{diff.to_revision}"
                f" · +{diff.added_lines} / -{diff.removed_lines} 行"
            )
            diff_summary.setObjectName("skillLabMeta")
            diff_summary.setProperty("candidate_diff_summary", True)
            layout.addWidget(diff_summary)

        if report is None:
            evaluation = QLabel("尚无与当前内容匹配的隔离评测报告。")
            evaluation.setObjectName("skillLabWarning")
            permission_text = "权限：尚未分析"
        else:
            passed_checks = sum(
                check.status == EvaluationCheckStatus.PASSED for check in report.checks
            )
            warning_checks = sum(
                check.status == EvaluationCheckStatus.WARNING for check in report.checks
            )
            evaluation = QLabel(
                f"{report.summary} · {passed_checks}/{len(report.checks)} 项通过"
                + (f" · {warning_checks} 项提示" if warning_checks else "")
            )
            evaluation.setObjectName(
                "skillLabSafe" if report.status == EvaluationStatus.PASSED else "skillLabWarning"
            )
            permission_text = (
                "权限："
                + " · ".join(report.permissions.capabilities)
                + (" · 使用时仍需确认" if report.permissions.requires_confirmation else "")
            )
        evaluation.setWordWrap(True)
        evaluation.setProperty("evaluation_summary", True)
        layout.addWidget(evaluation)

        provenance = QLabel(self._provenance_detail_text(candidate, report))
        provenance.setObjectName(
            "skillLabWarning"
            if (
                candidate.source_kind == CandidateSource.SUCCESSFUL_TASK
                and (report is None or report.provenance.status != ProvenanceStatus.VERIFIED)
            )
            else "skillLabSafe"
        )
        provenance.setWordWrap(True)
        provenance.setProperty("provenance_summary", True)
        layout.addWidget(provenance)

        behavior = QLabel(self._behavior_detail_text(report))
        behavior.setObjectName(
            "skillLabSafe"
            if (report is not None and report.behavior.status == BehaviorSimulationStatus.PASSED)
            else "skillLabWarning"
        )
        behavior.setWordWrap(True)
        behavior.setProperty("behavior_summary", True)
        layout.addWidget(behavior)

        permissions = QLabel(permission_text)
        permissions.setObjectName("skillLabMeta")
        permissions.setWordWrap(True)
        permissions.setProperty("permission_summary", True)
        layout.addWidget(permissions)

        validation = QLabel(
            "静态检查通过；评测不会执行候选命令，也不会联网。"
            if not candidate.validation_errors
            else "检查发现：" + "；".join(candidate.validation_errors)
        )
        validation.setObjectName(
            "skillLabSafe" if not candidate.validation_errors else "skillLabWarning"
        )
        validation.setWordWrap(True)
        layout.addWidget(validation)

        actions = QHBoxLayout()
        view_btn = QPushButton("查看评测与提案")
        view_btn.clicked.connect(
            lambda _checked=False, item=candidate, evidence=report: self._view_candidate(
                item,
                evidence,
            )
        )
        actions.addWidget(view_btn)

        edit_btn = QPushButton("编辑提案")
        edit_btn.clicked.connect(lambda _checked=False, item=candidate: self._edit_candidate(item))
        actions.addWidget(edit_btn)

        evaluate_btn = QPushButton("重新评测")
        evaluate_btn.clicked.connect(
            lambda _checked=False, candidate_id=candidate.id: self._evaluate_candidate(candidate_id)
        )
        actions.addWidget(evaluate_btn)
        actions.addStretch()

        reject_btn = QPushButton("拒绝")
        reject_btn.setObjectName("skillLabDanger")
        reject_btn.clicked.connect(
            lambda _checked=False, candidate_id=candidate.id: self._reject_candidate(candidate_id)
        )
        actions.addWidget(reject_btn)

        approve_btn = QPushButton("批准并启用")
        approve_btn.setObjectName("skillLabPrimary")
        evaluation_passed = (
            report is not None
            and report.status == EvaluationStatus.PASSED
            and report.score >= self._settings.skill_evaluation_min_score
            and report.candidate_revision == candidate.revision
            and report.behavior.status == BehaviorSimulationStatus.PASSED
        )
        approve_btn.setEnabled(not candidate.validation_errors and evaluation_passed)
        if not evaluation_passed:
            if candidate.source_kind == CandidateSource.SUCCESSFUL_TASK and (
                report is None or report.provenance.status != ProvenanceStatus.VERIFIED
            ):
                approve_btn.setToolTip("来源 Task Run、成功结果和已完成工具轨迹尚未全部核验")
            else:
                approve_btn.setToolTip("需要当前修订通过隔离包、来源和受限行为模拟")
        approve_btn.clicked.connect(
            lambda _checked=False, candidate_id=candidate.id: self._approve_candidate(candidate_id)
        )
        actions.addWidget(approve_btn)
        layout.addLayout(actions)
        return card

    def _create_skill_card(self, skill: SkillRecord, status: SkillStatus) -> QFrame:
        card = self._new_card(skill.name)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        header = QHBoxLayout()
        name_label = QLabel(skill.name)
        name_label.setObjectName("skillLabCardTitle")
        header.addWidget(name_label)
        status_label = QLabel(self._status_text(status))
        status_label.setObjectName("skillLabBadge")
        header.addWidget(status_label)
        header.addStretch()
        layout.addLayout(header)

        desc_label = QLabel(skill.description)
        desc_label.setObjectName("skillLabDescription")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        total_uses = skill.success_count + skill.failure_count
        meta = QLabel(
            f"版本 {skill.version} · 来源 {skill.source} · 成功 {skill.success_count}/{total_uses}"
        )
        meta.setObjectName("skillLabMeta")
        layout.addWidget(meta)

        actions = QHBoxLayout()
        view_btn = QPushButton("查看内容")
        view_btn.clicked.connect(
            lambda _checked=False, skill_id=skill.id: self._view_content(skill_id)
        )
        actions.addWidget(view_btn)

        if status in (SkillStatus.ACTIVE, SkillStatus.NEEDS_REVIEW):
            disable_btn = QPushButton("禁用（可恢复）")
            disable_btn.clicked.connect(
                lambda _checked=False, skill_id=skill.id: self._disable_skill(skill_id)
            )
            actions.addWidget(disable_btn)
            archive_btn = QPushButton("归档")
            archive_btn.clicked.connect(
                lambda _checked=False, skill_id=skill.id: self._archive_skill(skill_id)
            )
            actions.addWidget(archive_btn)
        elif status == SkillStatus.DISABLED:
            enable_btn = QPushButton("重新启用")
            enable_btn.clicked.connect(
                lambda _checked=False, skill_id=skill.id: self._enable_skill(skill_id)
            )
            actions.addWidget(enable_btn)
            archive_btn = QPushButton("归档")
            archive_btn.clicked.connect(
                lambda _checked=False, skill_id=skill.id: self._archive_skill(skill_id)
            )
            actions.addWidget(archive_btn)

        actions.addStretch()
        layout.addLayout(actions)
        return card

    @staticmethod
    def _new_card(search_text: str) -> QFrame:
        card = QFrame()
        card.setObjectName("skillLabCard")
        card.setProperty("skill_name", search_text.lower())
        return card

    @staticmethod
    def _status_text(status: SkillStatus) -> str:
        return {
            SkillStatus.ACTIVE: "已启用",
            SkillStatus.NEEDS_REVIEW: "待复核",
            SkillStatus.DISABLED: "已禁用",
            SkillStatus.ARCHIVED: "已归档",
        }.get(status, status.value)

    def _view_candidate(
        self,
        candidate: SkillCandidate,
        report: Optional[SkillEvaluationReport],
    ) -> None:
        evaluation_lines = ["隔离评测：暂无当前报告"]
        if report is not None:
            behavior_lines = [
                (f"行为模拟：{report.behavior.summary}" f" · 指纹 {report.behavior.fingerprint[:12]}"),
                *[
                    (
                        f"[合成{self._simulation_outcome_text(receipt.outcome.value)}] "
                        f"场景 {receipt.scenario} · 第 {receipt.step_index} 步"
                        f" · {receipt.tool_name} · {receipt.detail}"
                    )
                    for receipt in report.behavior.receipts
                ],
            ]
            evaluation_lines = [
                (
                    f"隔离评测：提案 v{report.candidate_revision}"
                    f" · {report.score}/100 · {report.summary}"
                ),
                "权限：" + " · ".join(report.permissions.capabilities),
                ("来源证明：" + self._provenance_detail_text(candidate, report)),
                *behavior_lines,
                "",
                *[
                    (f"[{self._check_status_text(check.status)}] " f"{check.title}：{check.detail}")
                    for check in report.checks
                ],
            ]
        diff = self._manager.get_candidate_diff(candidate.id)
        diff_lines: list[str] = []
        if diff is not None and diff.changed:
            diff_lines = [
                "",
                (f"—— 版本差异 v{diff.from_revision} → " f"v{diff.to_revision} ——"),
                f"+{diff.added_lines} / -{diff.removed_lines} 行",
                "",
                diff.unified_diff,
            ]
        self._show_content_dialog(
            f"能力提案 · {candidate.proposed_name}",
            "\n".join(
                [
                    *evaluation_lines,
                    *diff_lines,
                    "",
                    "—— 只读提案内容 ——",
                    "",
                    candidate.proposed_content,
                ]
            ),
        )

    def _edit_candidate(self, candidate: SkillCandidate) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"编辑能力提案 · {candidate.proposed_name}")
        dialog.setMinimumSize(680, 520)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            f"当前为提案 v{candidate.revision}。保存会创建不可变的 " f"v{candidate.revision + 1}，保留版本差异并重新评测。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        editor = QTextEdit()
        editor.setPlainText(candidate.proposed_content)
        editor.setProperty("candidate_editor", True)
        layout.addWidget(editor)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = self._manager.update_candidate_content(
            candidate.id,
            editor.toPlainText(),
        )
        if updated is None:
            QMessageBox.warning(
                self,
                "未能保存",
                "提案状态已经变化，请刷新后再试。",
            )
            return
        self._load_all()

    @staticmethod
    def _provenance_badge_text(
        candidate: SkillCandidate,
        report: Optional[SkillEvaluationReport],
    ) -> str:
        if candidate.source_kind != CandidateSource.SUCCESSFUL_TASK:
            return "非自动学习"
        if report is not None and report.provenance.status == ProvenanceStatus.VERIFIED:
            return "来源已核验"
        return "来源待核验"

    @staticmethod
    def _provenance_detail_text(
        candidate: SkillCandidate,
        report: Optional[SkillEvaluationReport],
    ) -> str:
        if candidate.source_kind != CandidateSource.SUCCESSFUL_TASK:
            return "来源证明：该提案不宣称来自自动学习"
        if report is None:
            return "来源证明：等待核验 Task Run、成功结果和工具轨迹"
        provenance = report.provenance
        observed = "、".join(provenance.observed_tools) or "无"
        return (
            f"来源证明：{provenance.detail} · " f"已观测工具 {len(provenance.observed_tools)} 种（{observed}）"
        )

    @staticmethod
    def _behavior_detail_text(
        report: Optional[SkillEvaluationReport],
    ) -> str:
        if report is None:
            return "行为模拟：等待当前修订的合成工具回归"
        behavior = report.behavior
        if behavior.status == BehaviorSimulationStatus.NOT_EVALUATED:
            return "行为模拟：旧评测没有行为证据，需要重新评测"
        tools = "、".join(behavior.simulated_tools) or "纯推理流程"
        return f"行为模拟：{behavior.summary} · 工具 {tools}" " · 未读写文件、未运行命令、未访问网络"

    @staticmethod
    def _simulation_outcome_text(outcome: str) -> str:
        return "允许" if outcome == "permitted" else "拒绝"

    @staticmethod
    def _check_status_text(status: EvaluationCheckStatus) -> str:
        return {
            EvaluationCheckStatus.PASSED: "通过",
            EvaluationCheckStatus.WARNING: "提示",
            EvaluationCheckStatus.FAILED: "阻止",
        }[status]

    def _evaluate_candidate(self, candidate_id: str) -> None:
        report = self._manager.evaluate_candidate(candidate_id)
        if report is None:
            QMessageBox.warning(self, "无法评测", "能力提案不存在或已被移除。")
            return
        self._load_all()

    def _view_content(self, skill_id: str):
        self._show_content_dialog("能力内容", self._manager.get_content(skill_id))

    def _show_content_dialog(self, title: str, content: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(600, 460)
        layout = QVBoxLayout(dialog)
        note = QLabel("内容只读。批准提案后仍可随时禁用或归档该能力。")
        note.setWordWrap(True)
        layout.addWidget(note)
        text_edit = QTextEdit()
        text_edit.setPlainText(content)
        text_edit.setReadOnly(True)
        layout.addWidget(text_edit)
        dialog.exec()

    def _approve_candidate(self, candidate_id: str) -> None:
        answer = QMessageBox.question(
            self,
            "批准新能力",
            "批准后该能力会写入工作区并立即可用。之后仍可禁用或归档。继续吗？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        created = self._manager.approve_candidate(candidate_id)
        if created is None:
            QMessageBox.warning(self, "未能批准", "提案未通过校验，或同名能力已经存在。")
            return
        self.skill_activated.emit(created.id)
        self._load_all()

    def _reject_candidate(self, candidate_id: str) -> None:
        reason, accepted = QInputDialog.getText(
            self,
            "拒绝能力提案",
            "可选：告诉 Lobuddy 为什么不需要这个能力",
        )
        if not accepted:
            return
        self._manager.reject_candidate(candidate_id, reason.strip())
        self._load_all()

    def _disable_skill(self, skill_id: str):
        if (
            QMessageBox.question(
                self,
                "禁用能力",
                "禁用会移除工作区投影，但保留记录，之后可以恢复。继续吗？",
            )
            == QMessageBox.StandardButton.Yes
        ):
            self._manager.disable_skill(skill_id)
            self._load_all()

    def _enable_skill(self, skill_id: str):
        if self._manager.enable_skill(skill_id):
            self.skill_activated.emit(skill_id)
        self._load_all()

    def _archive_skill(self, skill_id: str):
        if (
            QMessageBox.question(
                self,
                "归档能力",
                "归档会保留快照并移除当前工作区投影。继续吗？",
            )
            == QMessageBox.StandardButton.Yes
        ):
            self._manager.archive_skill(skill_id)
            self._load_all()

    def _on_search(self, query: str):
        normalized = query.strip().lower()
        for card in self._cards:
            name = card.property("skill_name") or ""
            card.setVisible(normalized in name)

    def _on_theme_changed(self, _theme) -> None:
        self.refresh_theme()

    def refresh_theme(self) -> None:
        theme = ThemeManager.instance().current
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {theme.background};
                color: {theme.text};
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
            }}
            QLabel {{
                color: {theme.text_secondary};
            }}
            QLabel#skillLabCardTitle {{
                color: {theme.text};
                font-size: 13px;
                font-weight: 700;
            }}
            QLabel#skillLabDescription {{
                color: {theme.text_secondary};
                font-size: 11px;
            }}
            QLabel#skillLabMeta,
            QLabel#skillLabEmpty {{
                color: {theme.text_muted};
                font-size: 10px;
            }}
            QLabel#skillLabBadge {{
                background: {theme.surface_soft};
                color: {theme.primary};
                border: 1px solid {theme.border};
                border-radius: 8px;
                padding: 2px 7px;
                font-size: 9px;
            }}
            QLabel#skillLabPassedBadge {{
                background: {theme.surface_soft};
                color: {theme.success};
                border: 1px solid {theme.border};
                border-radius: 8px;
                padding: 2px 7px;
                font-size: 9px;
                font-weight: 700;
            }}
            QLabel#skillLabBlockedBadge {{
                background: {theme.surface_soft};
                color: {theme.warning};
                border: 1px solid {theme.border};
                border-radius: 8px;
                padding: 2px 7px;
                font-size: 9px;
                font-weight: 700;
            }}
            QLabel#skillLabSafe {{
                color: {theme.success};
                font-size: 10px;
            }}
            QLabel#skillLabWarning {{
                color: {theme.warning};
                font-size: 10px;
            }}
            QFrame#skillLabCard {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_md}px;
            }}
            QLineEdit, QTextEdit {{
                background: {theme.surface};
                color: {theme.text};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
                padding: 7px 9px;
            }}
            QLineEdit:focus, QTextEdit:focus {{
                border-color: {theme.primary};
            }}
            QTabWidget::pane {{
                background: {theme.surface_soft};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_md}px;
                padding: 6px;
            }}
            QTabBar::tab {{
                color: {theme.text_muted};
                padding: 8px 12px;
                border: none;
            }}
            QTabBar::tab:selected {{
                color: {theme.primary};
                border-bottom: 2px solid {theme.primary};
                font-weight: 700;
            }}
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QWidget#skillLabScrollContent {{
                background: {theme.surface_soft};
            }}
            QPushButton {{
                background: {theme.surface_soft};
                color: {theme.text_secondary};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_sm}px;
                padding: 6px 10px;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background: {theme.primary_soft};
                border-color: {theme.primary};
                color: {theme.text};
            }}
            QPushButton#skillLabPrimary {{
                background: {theme.primary};
                color: {theme.primary_text};
                border: none;
                font-weight: 700;
            }}
            QPushButton#skillLabDanger {{
                color: {theme.danger};
            }}
            """
        )
        self._title.setStyleSheet(f"color: {theme.text};")
        self._subtitle.setStyleSheet(f"color: {theme.text_muted}; font-size: 11px;")
