"""Explainable review shown before creating a retry Task Run."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.models.task_recovery import RecoveryEvidence, TaskRecoveryReview
from ui.styles import current_theme
from ui.theme import ThemeManager, generate_button_style


class TaskRecoveryDialog(QDialog):
    """Warm recovery review; evidence is visible before explicit confirmation."""

    def __init__(
        self,
        review: TaskRecoveryReview,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.review = review
        self._init_ui()
        self._apply_theme(current_theme())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    def _init_ui(self) -> None:
        self.setWindowTitle("继续这项工作")
        self.setMinimumSize(700, 540)
        self.resize(740, 570)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        heading = QVBoxLayout()
        heading.setSpacing(3)
        title = QLabel("继续这项工作")
        title.setObjectName("pageTitle")
        heading.addWidget(title)
        subtitle = QLabel("先看清上一次做到哪里，再决定是否创建新的 Task Run。")
        subtitle.setObjectName("pageSubtitle")
        heading.addWidget(subtitle)
        root.addLayout(heading)

        hero = QWidget()
        hero.setObjectName("recoveryHero")
        hero.setProperty("eligible", "true" if self.review.eligible else "false")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(17, 14, 17, 14)
        hero_layout.setSpacing(7)
        headline = QLabel(self.review.headline)
        headline.setObjectName("recoveryHeadline")
        headline.setWordWrap(True)
        hero_layout.addWidget(headline)
        summary = QLabel(self.review.summary)
        summary.setObjectName("recoverySummary")
        summary.setWordWrap(True)
        hero_layout.addWidget(summary)
        self._progress = QProgressBar()
        self._progress.setObjectName("recoveryProgress")
        self._progress.setRange(0, 100)
        self._progress.setValue(round(self.review.progress * 100))
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(5)
        self._progress.setVisible(self.review.progress > 0)
        hero_layout.addWidget(self._progress)
        root.addWidget(hero)

        evidence_title = QLabel("上一次留下的证据")
        evidence_title.setObjectName("sectionTitle")
        root.addWidget(evidence_title)
        evidence_row = QHBoxLayout()
        evidence_row.setSpacing(10)
        for evidence in self.review.evidence:
            evidence_row.addWidget(self._evidence_card(evidence), 1)
        root.addLayout(evidence_row)

        if self.review.possible_side_effects:
            warning = QLabel(
                "上一次可能已经改变了外部状态。新尝试会重新观察和确认，"
                "不会假设旧动作可以安全重复。"
            )
            warning.setObjectName("attentionBanner")
            warning.setWordWrap(True)
            root.addWidget(warning)

        safeguard = QWidget()
        safeguard.setObjectName("safeguardCard")
        safeguard_layout = QVBoxLayout(safeguard)
        safeguard_layout.setContentsMargins(15, 12, 15, 12)
        safeguard_layout.setSpacing(6)
        safeguard_title = QLabel("新的尝试会怎样保护你")
        safeguard_title.setObjectName("safeguardTitle")
        safeguard_layout.addWidget(safeguard_title)
        for item in self.review.safeguards:
            row = QLabel(f"•  {item}")
            row.setObjectName("safeguardItem")
            row.setWordWrap(True)
            safeguard_layout.addWidget(row)
        root.addWidget(safeguard)
        root.addSpacing(2)

        self._acknowledgement = QCheckBox(
            "我了解：这会创建新的尝试，而不是继续或重放旧执行。"
        )
        self._acknowledgement.setObjectName("acknowledgement")
        self._acknowledgement.setVisible(self.review.eligible)
        root.addWidget(self._acknowledgement)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("暂不继续")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self._cancel_btn = cancel
        self._confirm_btn = QPushButton(
            f"开始第 {self.review.next_attempt_no} 次尝试"
            if self.review.eligible
            else "返回对话"
        )
        if self.review.eligible:
            self._confirm_btn.setEnabled(False)
            self._acknowledgement.toggled.connect(self._confirm_btn.setEnabled)
            self._confirm_btn.clicked.connect(self.accept)
        else:
            self._confirm_btn.clicked.connect(self.reject)
        actions.addWidget(self._confirm_btn)
        root.addLayout(actions)

    @staticmethod
    def _evidence_card(evidence: RecoveryEvidence) -> QWidget:
        card = QWidget()
        card.setObjectName("evidenceCard")
        card.setProperty("tone", evidence.tone.value)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(13, 11, 13, 11)
        layout.setSpacing(4)
        label = QLabel(evidence.label)
        label.setObjectName("evidenceLabel")
        layout.addWidget(label)
        value = QLabel(evidence.value)
        value.setObjectName("evidenceValue")
        value.setWordWrap(True)
        layout.addWidget(value)
        detail = QLabel(evidence.detail)
        detail.setObjectName("evidenceDetail")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        layout.addStretch(1)
        return card

    def _apply_theme(self, theme) -> None:
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {theme.background};
                color: {theme.text};
                font-family: "Microsoft YaHei UI";
                font-size: 13px;
            }}
            QLabel#pageTitle {{
                color: {theme.text};
                font-size: 24px;
                font-weight: 700;
            }}
            QLabel#pageSubtitle {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QWidget#recoveryHero {{
                background: {theme.surface};
                border: 1px solid {theme.success};
                border-radius: {theme.radius_lg}px;
            }}
            QWidget#recoveryHero[eligible="false"] {{
                background: {theme.surface_soft};
                border: 1px solid {theme.warning};
            }}
            QLabel#recoveryHeadline {{
                color: {theme.text};
                font-size: 16px;
                font-weight: 700;
            }}
            QLabel#recoverySummary {{
                color: {theme.text_secondary};
                font-size: 12px;
            }}
            QProgressBar#recoveryProgress {{
                background: {theme.surface_soft};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar#recoveryProgress::chunk {{
                background: {theme.success};
                border-radius: 2px;
            }}
            QLabel#sectionTitle {{
                color: {theme.text_secondary};
                font-size: 12px;
                font-weight: 700;
            }}
            QWidget#evidenceCard {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_md}px;
            }}
            QWidget#evidenceCard[tone="attention"] {{
                border: 1px solid {theme.warning};
            }}
            QLabel#evidenceLabel {{
                color: {theme.text_muted};
                font-size: 10px;
                font-weight: 700;
            }}
            QLabel#evidenceValue {{
                color: {theme.text};
                font-size: 13px;
                font-weight: 700;
            }}
            QLabel#evidenceDetail {{
                color: {theme.text_secondary};
                font-size: 11px;
            }}
            QLabel#attentionBanner {{
                background: {theme.surface_soft};
                color: {theme.warning};
                border: 1px solid {theme.warning};
                border-radius: {theme.radius_sm}px;
                padding: 9px 12px;
                font-size: 11px;
                font-weight: 600;
            }}
            QWidget#safeguardCard {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: {theme.radius_md}px;
            }}
            QLabel#safeguardTitle {{
                color: {theme.text};
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#safeguardItem {{
                color: {theme.text_secondary};
                font-size: 11px;
            }}
            QCheckBox#acknowledgement {{
                color: {theme.text_secondary};
                spacing: 8px;
                font-size: 11px;
            }}
            QCheckBox#acknowledgement::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {theme.border};
                border-radius: 5px;
                background: {theme.surface};
            }}
            QCheckBox#acknowledgement::indicator:checked {{
                background: {theme.primary};
                border-color: {theme.primary};
            }}
            """
        )
        self._cancel_btn.setStyleSheet(
            generate_button_style(theme, size="sm", variant="secondary")
        )
        self._confirm_btn.setStyleSheet(
            generate_button_style(theme, size="sm", variant="primary")
            + (
                f" QPushButton:disabled {{"
                f" background: {theme.surface_soft};"
                f" color: {theme.text_muted};"
                f" border: 1px solid {theme.border};"
                f"}}"
            )
        )
