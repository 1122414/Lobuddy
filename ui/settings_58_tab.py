"""Settings tab for maintenance, work records, memory, and skill governance."""

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config import Settings


class Settings58Tab(QWidget):
    """Tab widget for 5.8 system optimization settings."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._init_ui()

    def _init_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(10)

        # Maintenance Scheduler
        maint_group = QGroupBox("维护调度器")
        maint_layout = QFormLayout()

        self._maint_start_delay_spin = QSpinBox()
        self._maint_start_delay_spin.setRange(0, 300)
        self._maint_start_delay_spin.setSuffix(" 秒")
        maint_layout.addRow("启动延迟:", self._maint_start_delay_spin)

        self._maint_poll_spin = QSpinBox()
        self._maint_poll_spin.setRange(1, 60)
        self._maint_poll_spin.setSuffix(" 秒")
        maint_layout.addRow("轮询间隔:", self._maint_poll_spin)

        self._maint_memory_spin = QSpinBox()
        self._maint_memory_spin.setRange(0, 168)
        self._maint_memory_spin.setSuffix(" 小时 (0=禁用)")
        maint_layout.addRow("Memory 清理间隔:", self._maint_memory_spin)

        self._maint_skill_spin = QSpinBox()
        self._maint_skill_spin.setRange(0, 168)
        self._maint_skill_spin.setSuffix(" 小时 (0=禁用)")
        maint_layout.addRow("Skill 评审间隔:", self._maint_skill_spin)

        self._maint_trace_spin = QSpinBox()
        self._maint_trace_spin.setRange(0, 168)
        self._maint_trace_spin.setSuffix(" 小时 (0=禁用)")
        maint_layout.addRow("Trace 清理间隔:", self._maint_trace_spin)

        self._maint_cache_spin = QSpinBox()
        self._maint_cache_spin.setRange(0, 720)
        self._maint_cache_spin.setSuffix(" 小时 (0=禁用)")
        maint_layout.addRow("缓存清理间隔:", self._maint_cache_spin)

        maint_group.setLayout(maint_layout)
        layout.addWidget(maint_group)

        # Work record
        obs_group = QGroupBox("工作记录与诊断")
        obs_layout = QFormLayout()

        self._obs_traces_spin = QSpinBox()
        self._obs_traces_spin.setRange(1, 100)
        obs_layout.addRow("最近工具记录:", self._obs_traces_spin)

        self._obs_hitl_spin = QSpinBox()
        self._obs_hitl_spin.setRange(1, 100)
        obs_layout.addRow("最近确认记录:", self._obs_hitl_spin)

        self._obs_token_spin = QSpinBox()
        self._obs_token_spin.setRange(1, 50)
        obs_layout.addRow("Token 会话数:", self._obs_token_spin)

        obs_group.setLayout(obs_layout)
        layout.addWidget(obs_group)

        mem_group = QGroupBox("记忆控制台")
        mem_layout = QFormLayout()

        self._mem_console_enabled = QCheckBox("启用记忆控制台")
        mem_layout.addRow(self._mem_console_enabled)

        self._mem_console_sensitive = QCheckBox("显示完整敏感内容")
        mem_layout.addRow(self._mem_console_sensitive)

        self._mem_console_page = QSpinBox()
        self._mem_console_page.setRange(5, 100)
        self._mem_console_page.setSuffix(" 条")
        mem_layout.addRow("每页显示:", self._mem_console_page)

        mem_group.setLayout(mem_layout)
        layout.addWidget(mem_group)

        priv_group = QGroupBox("隐私模式")
        priv_layout = QFormLayout()

        self._priv_mode_default = QCheckBox("新会话默认开启隐私模式")
        priv_layout.addRow(self._priv_mode_default)

        self._priv_allow_history = QCheckBox("允许保存聊天记录")
        priv_layout.addRow(self._priv_allow_history)

        self._priv_indicator = QCheckBox("显示状态指示器")
        priv_layout.addRow(self._priv_indicator)

        priv_group.setLayout(priv_layout)
        layout.addWidget(priv_group)

        conf_group = QGroupBox("冲突检测")
        conf_layout = QFormLayout()

        self._conf_enabled = QCheckBox("启用自动冲突检测")
        conf_layout.addRow(self._conf_enabled)

        self._conf_threshold_spin = QSpinBox()
        self._conf_threshold_spin.setRange(50, 100)
        self._conf_threshold_spin.setSuffix(" %")
        conf_layout.addRow("自动解决阈值:", self._conf_threshold_spin)

        self._conf_identity_input = QLineEdit()
        self._conf_identity_input.setPlaceholderText("user_name,pet_name,project_path")
        conf_layout.addRow("身份键 (逗号分隔):", self._conf_identity_input)

        conf_group.setLayout(conf_layout)
        layout.addWidget(conf_group)

        skill_group = QGroupBox("技能实验室 (5.8)")
        skill_layout = QFormLayout()

        self._skill_lab_enabled = QCheckBox("启用技能实验室")
        skill_layout.addRow(self._skill_lab_enabled)

        self._skill_review_enabled = QCheckBox("启用候选审核")
        skill_layout.addRow(self._skill_review_enabled)

        self._skill_validation_enabled = QCheckBox("启用静态校验")
        skill_layout.addRow(self._skill_validation_enabled)

        self._skill_evaluation_enabled = QCheckBox("新提案生成后自动评测")
        self._skill_evaluation_enabled.setToolTip(
            "批准前始终需要通过；此开关只控制是否在提案生成后立即评测"
        )
        skill_layout.addRow(self._skill_evaluation_enabled)

        self._skill_evaluation_score_spin = QSpinBox()
        self._skill_evaluation_score_spin.setRange(50, 100)
        self._skill_evaluation_score_spin.setSuffix(" 分")
        skill_layout.addRow(
            "评测最低通过分:",
            self._skill_evaluation_score_spin,
        )

        self._skill_min_confidence_spin = QSpinBox()
        self._skill_min_confidence_spin.setRange(0, 100)
        self._skill_min_confidence_spin.setSuffix(" %")
        skill_layout.addRow("候选最低置信度:", self._skill_min_confidence_spin)

        skill_group.setLayout(skill_layout)
        layout.addWidget(skill_group)

        layout.addStretch()
        scroll.setWidget(content)
        outer_layout.addWidget(scroll)
        self._refresh_ui()

    def _refresh_ui(self):
        self._maint_start_delay_spin.setValue(int(self.settings.maintenance_start_delay_seconds))
        self._maint_poll_spin.setValue(int(self.settings.maintenance_poll_interval_seconds))
        self._maint_memory_spin.setValue(
            int(self.settings.maintenance_memory_cleanup_interval_seconds / 3600)
        )
        self._maint_skill_spin.setValue(
            int(self.settings.maintenance_skill_review_interval_seconds / 3600)
        )
        self._maint_trace_spin.setValue(
            int(self.settings.maintenance_trace_cleanup_interval_seconds / 3600)
        )
        self._maint_cache_spin.setValue(
            int(self.settings.maintenance_asset_cache_cleanup_interval_seconds / 3600)
        )

        self._obs_traces_spin.setValue(self.settings.observability_max_traces)
        self._obs_hitl_spin.setValue(self.settings.observability_max_hitl_records)
        self._obs_token_spin.setValue(self.settings.observability_max_token_sessions)

        self._mem_console_enabled.setChecked(self.settings.memory_console_enabled)
        self._mem_console_sensitive.setChecked(self.settings.memory_console_show_sensitive_content)
        self._mem_console_page.setValue(self.settings.memory_console_items_per_page)

        self._priv_mode_default.setChecked(self.settings.privacy_mode_enabled)
        self._priv_allow_history.setChecked(self.settings.privacy_mode_allow_chat_history)
        self._priv_indicator.setChecked(self.settings.privacy_mode_show_indicator)

        self._conf_enabled.setChecked(self.settings.memory_conflict_detection_enabled)
        self._conf_threshold_spin.setValue(
            int(self.settings.memory_conflict_auto_resolve_threshold * 100)
        )
        self._conf_identity_input.setText(self.settings.memory_conflict_identity_keys)

        self._skill_lab_enabled.setChecked(self.settings.skill_lab_enabled)
        self._skill_review_enabled.setChecked(self.settings.skill_candidate_review_enabled)
        self._skill_validation_enabled.setChecked(self.settings.skill_validation_enabled)
        self._skill_evaluation_enabled.setChecked(
            self.settings.skill_evaluation_enabled
        )
        self._skill_evaluation_score_spin.setValue(
            self.settings.skill_evaluation_min_score
        )
        self._skill_min_confidence_spin.setValue(
            int(self.settings.skill_candidate_min_confidence * 100)
        )

    def save_settings(self, repo) -> None:
        """Save 5.8 settings to repository."""
        repo.set_setting(
            "maintenance_start_delay_seconds",
            str(self._maint_start_delay_spin.value()),
        )
        repo.set_setting(
            "maintenance_poll_interval_seconds",
            str(self._maint_poll_spin.value()),
        )
        repo.set_setting(
            "maintenance_memory_cleanup_interval_seconds",
            str(self._maint_memory_spin.value() * 3600),
        )
        repo.set_setting(
            "maintenance_skill_review_interval_seconds",
            str(self._maint_skill_spin.value() * 3600),
        )
        repo.set_setting(
            "maintenance_trace_cleanup_interval_seconds",
            str(self._maint_trace_spin.value() * 3600),
        )
        repo.set_setting(
            "maintenance_asset_cache_cleanup_interval_seconds",
            str(self._maint_cache_spin.value() * 3600),
        )
        repo.set_setting(
            "observability_max_traces",
            str(self._obs_traces_spin.value()),
        )
        repo.set_setting(
            "observability_max_hitl_records",
            str(self._obs_hitl_spin.value()),
        )
        repo.set_setting(
            "observability_max_token_sessions",
            str(self._obs_token_spin.value()),
        )
        repo.set_setting(
            "memory_console_enabled",
            str(self._mem_console_enabled.isChecked()).lower(),
        )
        repo.set_setting(
            "memory_console_show_sensitive_content",
            str(self._mem_console_sensitive.isChecked()).lower(),
        )
        repo.set_setting(
            "memory_console_items_per_page",
            str(self._mem_console_page.value()),
        )
        repo.set_setting(
            "privacy_mode_enabled",
            str(self._priv_mode_default.isChecked()).lower(),
        )
        repo.set_setting(
            "privacy_mode_allow_chat_history",
            str(self._priv_allow_history.isChecked()).lower(),
        )
        repo.set_setting(
            "privacy_mode_show_indicator",
            str(self._priv_indicator.isChecked()).lower(),
        )
        repo.set_setting(
            "memory_conflict_detection_enabled",
            str(self._conf_enabled.isChecked()).lower(),
        )
        repo.set_setting(
            "memory_conflict_auto_resolve_threshold",
            str(self._conf_threshold_spin.value() / 100),
        )
        repo.set_setting(
            "memory_conflict_identity_keys",
            self._conf_identity_input.text(),
        )
        repo.set_setting(
            "skill_lab_enabled",
            str(self._skill_lab_enabled.isChecked()).lower(),
        )
        repo.set_setting(
            "skill_candidate_review_enabled",
            str(self._skill_review_enabled.isChecked()).lower(),
        )
        repo.set_setting(
            "skill_validation_enabled",
            str(self._skill_validation_enabled.isChecked()).lower(),
        )
        repo.set_setting(
            "skill_evaluation_enabled",
            str(self._skill_evaluation_enabled.isChecked()).lower(),
        )
        repo.set_setting(
            "skill_evaluation_min_score",
            str(self._skill_evaluation_score_spin.value()),
        )
        repo.set_setting(
            "skill_candidate_min_confidence",
            str(self._skill_min_confidence_spin.value() / 100),
        )
