"""Warm, evidence-backed view of Lobuddy's long-term relationship rhythm."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.companion.models import (
    companion_energy_label,
    companion_mood_label,
    companion_support_label,
    intervention_kind_label,
)
from core.personality.evolution import PersonalityEvolution
from core.relationship.models import RelationshipRhythmSnapshot
from core.relationship.rhythm_service import RelationshipRhythmService
from ui.styles import current_theme
from ui.theme import ThemeManager, generate_button_style, generate_card_style


class RelationshipRhythmDialog(QDialog):
    """Relationship control surface with no inferred emotion or synthetic score."""

    memory_requested = Signal()
    check_in_requested = Signal()

    def __init__(
        self,
        service: RelationshipRhythmService,
        parent=None,
        *,
        session_id_provider: Callable[[], str] | None = None,
        personality_evolution: PersonalityEvolution | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._personality_evolution = (
            personality_evolution or service.personality_evolution
        )
        self._session_id_provider = session_id_provider or (lambda: "")
        self._snapshot: RelationshipRhythmSnapshot | None = None
        self._init_ui()
        self._apply_theme(current_theme())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self.refresh()

    def _init_ui(self) -> None:
        self.setWindowTitle("我们的相处节奏")
        self.setMinimumSize(900, 680)
        self.resize(980, 790)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("relationshipScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root.addWidget(scroll)

        page = QWidget()
        page.setObjectName("relationshipPage")
        scroll.setWidget(page)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(26, 24, 26, 22)
        page_layout.setSpacing(16)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(3)
        title = QLabel("我们的相处节奏")
        title.setObjectName("pageTitle")
        heading.addWidget(title)
        subtitle = QLabel("只呈现你明确留下、确认过或可以随时撤销的陪伴证据。")
        subtitle.setObjectName("pageSubtitle")
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)
        self._privacy_chip = QLabel("本地关系视图")
        self._privacy_chip.setObjectName("privacyChip")
        self._privacy_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._privacy_chip)
        page_layout.addLayout(header)

        hero = QWidget()
        hero.setObjectName("heroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 17, 20, 17)
        hero_layout.setSpacing(5)
        self._headline_label = QLabel()
        self._headline_label.setObjectName("heroTitle")
        self._headline_label.setWordWrap(True)
        hero_layout.addWidget(self._headline_label)
        self._guidance_label = QLabel()
        self._guidance_label.setObjectName("heroBody")
        self._guidance_label.setWordWrap(True)
        hero_layout.addWidget(self._guidance_label)
        page_layout.addWidget(hero)

        columns = QHBoxLayout()
        columns.setSpacing(14)

        memory_card = QWidget()
        memory_card.setObjectName("card")
        memory_layout = QVBoxLayout(memory_card)
        memory_layout.setContentsMargins(18, 16, 18, 16)
        memory_layout.setSpacing(10)
        memory_header = QHBoxLayout()
        memory_heading = QVBoxLayout()
        memory_heading.setSpacing(2)
        memory_title = QLabel("你明确告诉我的")
        memory_title.setObjectName("sectionTitle")
        memory_heading.addWidget(memory_title)
        memory_subtitle = QLabel("偏好、共同瞬间与协作方式")
        memory_subtitle.setObjectName("mutedText")
        memory_heading.addWidget(memory_subtitle)
        memory_header.addLayout(memory_heading, 1)
        self._memory_summary = QLabel()
        self._memory_summary.setObjectName("summaryChip")
        memory_header.addWidget(self._memory_summary)
        memory_layout.addLayout(memory_header)
        self._memory_rows = QVBoxLayout()
        self._memory_rows.setSpacing(8)
        memory_layout.addLayout(self._memory_rows)
        memory_layout.addStretch(1)
        self._memory_button = QPushButton("主动告诉我 / 管理记忆")
        self._memory_button.clicked.connect(self.memory_requested.emit)
        memory_layout.addWidget(self._memory_button)
        columns.addWidget(memory_card, 3)

        care_card = QWidget()
        care_card.setObjectName("card")
        care_layout = QVBoxLayout(care_card)
        care_layout.setContentsMargins(18, 16, 18, 16)
        care_layout.setSpacing(10)
        care_title = QLabel("此刻与关怀边界")
        care_title.setObjectName("sectionTitle")
        care_layout.addWidget(care_title)
        self._checkin_label = QLabel()
        self._checkin_label.setObjectName("careState")
        self._checkin_label.setWordWrap(True)
        care_layout.addWidget(self._checkin_label)
        self._feedback_label = QLabel()
        self._feedback_label.setObjectName("mutedText")
        self._feedback_label.setWordWrap(True)
        care_layout.addWidget(self._feedback_label)
        care_layout.addStretch(1)
        self._checkin_button = QPushButton("更新当前状态")
        self._checkin_button.clicked.connect(self.check_in_requested.emit)
        care_layout.addWidget(self._checkin_button)
        self._clear_checkin_button = QPushButton("清除当前状态")
        self._clear_checkin_button.clicked.connect(self._clear_current_check_in)
        care_layout.addWidget(self._clear_checkin_button)
        self._restore_care_button = QPushButton("恢复默认主动关怀")
        self._restore_care_button.clicked.connect(self._restore_care_boundaries)
        care_layout.addWidget(self._restore_care_button)
        columns.addWidget(care_card, 2)
        page_layout.addLayout(columns)

        growth_card = QWidget()
        growth_card.setObjectName("card")
        growth_layout = QVBoxLayout(growth_card)
        growth_layout.setContentsMargins(18, 16, 18, 16)
        growth_layout.setSpacing(10)
        growth_header = QHBoxLayout()
        growth_heading = QVBoxLayout()
        growth_heading.setSpacing(2)
        growth_title = QLabel("Lobuddy 如何在协作中成长")
        growth_title.setObjectName("sectionTitle")
        growth_heading.addWidget(growth_title)
        growth_subtitle = QLabel("这些数值只来自成功任务，不代表你的情绪、人格或健康状态。")
        growth_subtitle.setObjectName("mutedText")
        growth_subtitle.setWordWrap(True)
        growth_heading.addWidget(growth_subtitle)
        growth_header.addLayout(growth_heading, 1)
        self._growth_history_button = QPushButton("查看成长版本")
        self._growth_history_button.clicked.connect(self._open_personality_history)
        growth_header.addWidget(self._growth_history_button)
        growth_layout.addLayout(growth_header)
        self._growth_rows = QVBoxLayout()
        self._growth_rows.setSpacing(8)
        growth_layout.addLayout(self._growth_rows)
        limitation = QLabel(
            "成长现在拥有逐次版本。恢复只改变五维倾向与证据计数，"
            "不会降低等级、经验、外观或已经解锁的能力。"
        )
        limitation.setObjectName("limitationText")
        limitation.setWordWrap(True)
        growth_layout.addWidget(limitation)
        page_layout.addWidget(growth_card)

        footer = QLabel(
            "关系节奏不是评分：屏幕观察只用于短时任务与克制关怀，"
            "不会被转换成你的情绪结论或长期关系标签。"
        )
        footer.setObjectName("footerText")
        footer.setWordWrap(True)
        page_layout.addWidget(footer)

    def refresh(self) -> None:
        self._snapshot = self._service.snapshot(
            session_id=self._session_id_provider(),
        )
        snapshot = self._snapshot
        self._privacy_chip.setText("隐私会话 · 只查看" if snapshot.privacy_active else "本地关系视图")
        self._headline_label.setText(snapshot.headline)
        guidance = snapshot.guidance
        if snapshot.privacy_active:
            guidance += " 当前隐私会话不会写入新的长期记忆，也不会调用旧记忆回答。"
        self._guidance_label.setText(guidance)
        self._memory_summary.setText(
            f"有效 {snapshot.active_memory_count} · 待确认 {snapshot.pending_review_count}"
        )
        self._render_memories(snapshot)
        self._render_care(snapshot)
        self._render_growth(snapshot)
        self._growth_history_button.setText(
            f"成长版本 · {snapshot.personality_version_count}"
        )

    def _render_memories(self, snapshot: RelationshipRhythmSnapshot) -> None:
        self._clear_layout(self._memory_rows)
        if not snapshot.memories:
            empty = QLabel("还没有适合展示的关系记忆。你可以从一项明确偏好开始。")
            empty.setObjectName("emptyState")
            empty.setWordWrap(True)
            self._memory_rows.addWidget(empty)
            return
        for evidence in snapshot.memories[:4]:
            row = QWidget()
            row.setObjectName("evidenceRow")
            layout = QVBoxLayout(row)
            layout.setContentsMargins(12, 9, 12, 9)
            layout.setSpacing(3)
            top = QHBoxLayout()
            title = QLabel(evidence.title)
            title.setObjectName("evidenceTitle")
            top.addWidget(title, 1)
            trust = QLabel(evidence.trust_label)
            trust.setObjectName(
                "reviewBadge" if evidence.trust_label == "等待你确认" else "evidenceBadge"
            )
            top.addWidget(trust)
            layout.addLayout(top)
            preview = QLabel(evidence.preview)
            preview.setObjectName("evidencePreview")
            preview.setWordWrap(True)
            layout.addWidget(preview)
            meta = QLabel(
                f"{evidence.kind_label} · {evidence.source_label} · {evidence.status_label}"
            )
            meta.setObjectName("evidenceMeta")
            meta.setWordWrap(True)
            layout.addWidget(meta)
            self._memory_rows.addWidget(row)

    def _render_care(self, snapshot: RelationshipRhythmSnapshot) -> None:
        check_in = snapshot.active_check_in
        if check_in is None:
            self._checkin_label.setText("你还没有填写当前状态。\nLobuddy 不会从屏幕推断你的情绪。")
            self._clear_checkin_button.setVisible(False)
        else:
            self._checkin_label.setText(
                f"{companion_mood_label(check_in.mood)} · "
                f"{companion_energy_label(check_in.energy)}\n"
                f"希望我：{companion_support_label(check_in.support_mode)}\n"
                f"有效至 {check_in.expires_at:%H:%M}"
            )
            self._clear_checkin_button.setVisible(True)

        summary = snapshot.preference_summary
        details = [f"你标记过 {summary.helpful_count} 次“有帮助”"]
        if summary.muted_kinds:
            muted = "、".join(intervention_kind_label(kind) for kind in summary.muted_kinds)
            details.append(f"不主动提醒：{muted}")
        if summary.snoozed_until is not None:
            details.append(f"安静至 {summary.snoozed_until:%H:%M}")
        if not summary.muted_kinds and summary.snoozed_until is None:
            details.append("当前没有静音或稍后提醒边界")
        self._feedback_label.setText("\n".join(details))
        self._restore_care_button.setVisible(
            bool(summary.muted_kinds or summary.snoozed_until)
        )

    def _render_growth(self, snapshot: RelationshipRhythmSnapshot) -> None:
        self._clear_layout(self._growth_rows)
        for trait in snapshot.growth_traits:
            row = QWidget()
            row.setObjectName("traitRow")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 1, 0, 1)
            layout.setSpacing(10)
            name = QLabel(trait.label)
            name.setObjectName("traitName")
            name.setFixedWidth(76)
            layout.addWidget(name)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(round(trait.value * 10))
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setToolTip(trait.explanation)
            layout.addWidget(bar, 1)
            delta = (
                f"+{trait.delta_from_baseline:g}"
                if trait.delta_from_baseline > 0
                else f"{trait.delta_from_baseline:g}"
            )
            value = QLabel(f"{trait.value:g}  ({delta})")
            value.setObjectName("traitValue")
            value.setFixedWidth(86)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(value)
            evidence = QLabel(trait.explanation)
            evidence.setObjectName("traitEvidence")
            evidence.setFixedWidth(270)
            layout.addWidget(evidence)
            self._growth_rows.addWidget(row)

    def _clear_current_check_in(self) -> None:
        reply = QMessageBox.question(
            self,
            "清除当前状态",
            "这会立即撤销当前 Check-in，之后不再影响 Lobuddy 的陪伴方式。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._service.clear_current_check_in()
        self.refresh()

    def _restore_care_boundaries(self) -> None:
        reply = QMessageBox.question(
            self,
            "恢复默认主动关怀",
            "这会清除“不再提醒”和“稍后再说”选择，"
            "但保留你标记过的“有帮助”反馈。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._service.restore_care_boundaries()
        self.refresh()

    def _open_personality_history(self) -> None:
        from ui.personality_evolution_dialog import PersonalityEvolutionDialog

        dialog = PersonalityEvolutionDialog(
            self._personality_evolution,
            parent=self,
        )
        dialog.restored.connect(lambda _revision_id: self.refresh())
        dialog.exec()
        self.refresh()

    def _apply_theme(self, theme) -> None:
        self.setStyleSheet(
            f"""
            QDialog, QWidget#relationshipPage {{
                background: {theme.background};
                color: {theme.text};
                font-size: 13px;
            }}
            QScrollArea#relationshipScroll {{
                background: {theme.background};
                border: none;
            }}
            QLabel#pageTitle {{
                color: {theme.text};
                font-size: 25px;
                font-weight: 700;
            }}
            QLabel#pageSubtitle, QLabel#mutedText {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QLabel#privacyChip, QLabel#summaryChip {{
                background: {theme.surface_soft};
                color: {theme.text_secondary};
                border: 1px solid {theme.border};
                border-radius: 12px;
                padding: 5px 9px;
                font-size: 11px;
                font-weight: 700;
            }}
            QWidget#heroCard {{
                background: {theme.primary_soft};
                border: 1px solid {theme.border_focus};
                border-radius: {theme.radius_md}px;
            }}
            QLabel#heroTitle {{
                color: {theme.text};
                font-size: 18px;
                font-weight: 700;
            }}
            QLabel#heroBody {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QLabel#sectionTitle {{
                color: {theme.text};
                font-size: 15px;
                font-weight: 700;
            }}
            QWidget#evidenceRow {{
                background: {theme.surface_soft};
                border: 1px solid {theme.divider};
                border-radius: {theme.radius_sm}px;
            }}
            QLabel#evidenceTitle {{
                color: {theme.text};
                font-weight: 700;
            }}
            QLabel#evidencePreview {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QLabel#evidenceMeta, QLabel#traitEvidence {{
                color: {theme.text_muted};
                font-size: 11px;
            }}
            QLabel#evidenceBadge {{
                color: {theme.success};
                background: {theme.surface};
                border-radius: 9px;
                padding: 2px 7px;
                font-size: 10px;
                font-weight: 700;
            }}
            QLabel#reviewBadge {{
                color: {theme.warning};
                background: {theme.surface};
                border-radius: 9px;
                padding: 2px 7px;
                font-size: 10px;
                font-weight: 700;
            }}
            QLabel#careState {{
                background: {theme.surface_soft};
                color: {theme.text};
                border-radius: {theme.radius_sm}px;
                padding: 12px;
                line-height: 1.4;
            }}
            QLabel#emptyState {{
                color: {theme.text_secondary};
                background: {theme.surface_soft};
                border: 1px dashed {theme.border};
                border-radius: {theme.radius_sm}px;
                padding: 16px;
            }}
            QLabel#traitName {{
                color: {theme.text};
                font-weight: 700;
            }}
            QLabel#traitValue {{
                color: {theme.primary_active};
                font-weight: 700;
            }}
            QProgressBar {{
                background: {theme.surface_soft};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: {theme.primary};
                border-radius: 4px;
            }}
            QLabel#limitationText {{
                color: {theme.warning};
                background: {theme.surface_soft};
                border-radius: {theme.radius_sm}px;
                padding: 8px 10px;
                font-size: 11px;
            }}
            QLabel#footerText {{
                color: {theme.text_muted};
                font-size: 11px;
                padding: 2px 4px;
            }}
            """
            + generate_card_style(theme)
        )
        self._memory_button.setStyleSheet(
            generate_button_style(theme, size="sm", variant="primary")
        )
        self._checkin_button.setStyleSheet(
            generate_button_style(theme, size="sm", variant="primary")
        )
        self._clear_checkin_button.setStyleSheet(
            generate_button_style(theme, size="sm", variant="ghost")
        )
        self._restore_care_button.setStyleSheet(
            generate_button_style(theme, size="sm", variant="secondary")
        )
        self._growth_history_button.setStyleSheet(
            generate_button_style(theme, size="sm", variant="secondary")
        )

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
