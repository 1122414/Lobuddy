"""Settings window for Lobuddy - 设置小窝."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import Settings, reload_settings, save_settings_to_env
from core.models.appearance import PetAppearance, get_appearance, save_appearance
from core.services.pet_asset_service import PetAssetService
from core.storage.settings_repo import SettingsRepository
from ui.theme import ThemeManager, ThemePreset, PRESET_THEMES


class SettingsWindow(QDialog):
    settings_saved = Signal(Settings)

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._original_api_key = settings.llm_api_key
        self.repo = SettingsRepository()
        self._pet_appearance = get_appearance()
        self._asset_service = PetAssetService()
        self._preview_movie = None
        self._init_ui()

    def showEvent(self, event):
        super().showEvent(event)
        self.settings = reload_settings()
        self._original_api_key = self.settings.llm_api_key
        self._pet_appearance = get_appearance()
        self._refresh_ui()

    def _init_ui(self):
        self.setWindowTitle("设置小窝")
        self.setMinimumWidth(520)
        self.setMinimumHeight(500)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        title = QLabel("🐱 设置小窝")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #FF8A3D;")
        main_layout.addWidget(title)

        tabs = QTabWidget()
        tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #F1D9C0; border-radius: 12px; "
            "background: #FFFFFF; padding: 12px; } "
            "QTabBar::tab { padding: 8px 16px; margin-right: 2px; "
            "border-top-left-radius: 8px; border-top-right-radius: 8px; } "
            "QTabBar::tab:selected { background: #FFF8EF; color: #FF8A3D; "
            "font-weight: bold; }"
        )
        tabs.addTab(self._build_basic_tab(), "基础设置")
        tabs.addTab(self._build_appearance_tab(), "外观装扮")
        tabs.addTab(self._build_theme_tab(), "主题设置")
        tabs.addTab(self._build_companion_tab(), "陪伴设置")
        tabs.addTab(self._build_advanced_tab(), "高级设置")
        tabs.addTab(self._build_4291_tab(), "4.29.1功能")
        tabs.addTab(self._build_52_tab(), "5.2记忆与技能")
        main_layout.addWidget(tabs)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.save_btn = QPushButton("保存")
        self.save_btn.setFixedSize(100, 36)
        self.save_btn.setStyleSheet(
            "QPushButton { background: #FF8A3D; color: white; border: none; "
            "border-radius: 10px; font-size: 13px; font-weight: bold; } "
            "QPushButton:hover { background: #EA580C; }"
        )
        self.save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedSize(100, 36)
        self.cancel_btn.setStyleSheet(
            "QPushButton { background: #FFF7ED; color: #4A2E1F; "
            "border: 1px solid #F1D9C0; border-radius: 10px; "
            "font-size: 13px; } "
            "QPushButton:hover { background: #FFF1DF; }"
        )
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        main_layout.addLayout(btn_layout)

    def _build_basic_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        layout.setSpacing(12)

        self.pet_name_input = QLineEdit(self.settings.pet_name)
        self.pet_name_input.setPlaceholderText("给你的小宠物起个名字吧")
        layout.addRow("宠物名字:", self.pet_name_input)

        self.user_name_input = QLineEdit(getattr(self.settings, "user_name", ""))
        self.user_name_input.setPlaceholderText("告诉我你的名字")
        layout.addRow("你的名字:", self.user_name_input)

        self._top_check = QCheckBox("窗口始终置顶")
        self._top_check.setChecked(getattr(self._pet_appearance, "always_on_top", True))
        layout.addRow("窗口:", self._top_check)

        return w

    def _build_appearance_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        preview_container = QWidget()
        preview_container.setFixedHeight(140)
        preview_container.setStyleSheet(
            "background: #FFF7ED; border: 1px solid #F1D9C0; border-radius: 12px;"
        )
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(16, 8, 16, 8)
        preview_layout.setSpacing(4)

        self._pet_preview_label = QLabel()
        self._pet_preview_label.setFixedSize(100, 100)
        self._pet_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self._pet_preview_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self._pet_preview_text = QLabel()
        self._pet_preview_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pet_preview_text.setStyleSheet("color: #A0846C; font-size: 11px;")
        preview_layout.addWidget(self._pet_preview_text)
        layout.addWidget(preview_container)

        upload_layout = QHBoxLayout()
        upload_btn = QPushButton("选择图片")
        upload_btn.clicked.connect(self._on_upload_pet_image)
        upload_layout.addWidget(upload_btn)
        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(self._on_reset_pet_image)
        upload_layout.addWidget(reset_btn)
        layout.addLayout(upload_layout)

        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("显示大小:"))
        self._scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._scale_slider.setRange(50, 200)
        self._scale_slider.setValue(int(self._pet_appearance.scale * 100))
        scale_layout.addWidget(self._scale_slider, stretch=1)
        self._scale_value = QLabel(f"{self._pet_appearance.scale:.1f}x")
        scale_layout.addWidget(self._scale_value)
        self._scale_slider.valueChanged.connect(
            lambda v: self._scale_value.setText(f"{v / 100:.1f}x")
        )
        layout.addLayout(scale_layout)

        self._anim_check = QCheckBox("启用宠物动画")
        self._anim_check.setChecked(self.settings.pet_avatar_animation_enabled)
        layout.addWidget(self._anim_check)

        self._update_pet_preview()
        return w

    def _build_theme_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(16)

        current_label = QLabel("当前主题")
        current_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(current_label)

        preset_group = QGroupBox("预制主题")
        preset_layout = QGridLayout()
        preset_layout.setSpacing(12)

        presets = [
            ("cozy_orange", "温馨橙", "#FF8A3D"),
            ("sakura_pink", "樱花粉", "#F48FB1"),
            ("mint_green", "薄荷绿", "#66BB6A"),
            ("night_companion", "夜伴", "#FF9E80"),
        ]

        self._preset_buttons = {}
        for i, (pid, name, color) in enumerate(presets):
            btn = QPushButton(name)
            btn.setFixedSize(100, 60)
            btn.setStyleSheet(
                f"QPushButton {{ background: {color}; color: white; "
                f"border: 2px solid transparent; border-radius: 8px; "
                f"font-weight: bold; font-size: 12px; }}"
                f"QPushButton:checked {{ border-color: #333; }}"
            )
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, p=pid: self._on_preset_selected(p))
            self._preset_buttons[pid] = btn
            preset_layout.addWidget(btn, i // 2, i % 2)

        preset_group.setLayout(preset_layout)
        layout.addWidget(preset_group)

        user_group = QGroupBox("我的主题")
        user_layout = QVBoxLayout()

        self._user_themes_list = QWidget()
        self._user_themes_layout = QVBoxLayout(self._user_themes_list)
        self._user_themes_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        user_layout.addWidget(self._user_themes_list)

        btn_row = QHBoxLayout()
        new_theme_btn = QPushButton("新建主题")
        new_theme_btn.clicked.connect(self._on_new_theme)
        btn_row.addWidget(new_theme_btn)

        from_pet_btn = QPushButton("从宠物生成")
        from_pet_btn.setToolTip("从当前宠物图片提取颜色生成主题")
        from_pet_btn.clicked.connect(self._on_generate_from_pet)
        btn_row.addWidget(from_pet_btn)

        user_layout.addLayout(btn_row)
        user_group.setLayout(user_layout)
        layout.addWidget(user_group)

        layout.addStretch()
        return w

    def _build_companion_tab(self) -> QWidget:
        w = QWidget()
        outer_layout = QVBoxLayout(w)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(w)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMaximumHeight(360)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        layout = QFormLayout(content)
        layout.setSpacing(10)

        section = QLabel("🐱 陪伴功能")
        section.setStyleSheet("color: #FF8A3D; font-weight: bold; font-size: 12px;")
        layout.addRow(section)

        self._greeting_check = QCheckBox("主动问候")
        self._greeting_check.setChecked(self.settings.companion_greeting_enabled)
        layout.addRow("互动:", self._greeting_check)

        self._daily_greet_check = QCheckBox("每日问候(默认关闭)")
        self._daily_greet_check.setChecked(self.settings.daily_greeting_enabled)
        layout.addRow("", self._daily_greet_check)

        self._daily_greet_max_spin = QSpinBox()
        self._daily_greet_max_spin.setRange(1, 10)
        self._daily_greet_max_spin.setValue(self.settings.daily_greeting_max_per_day)
        layout.addRow("每日问候上限:", self._daily_greet_max_spin)

        section2 = QLabel("🎯 宠物交互")
        section2.setStyleSheet("color: #FF8A3D; font-weight: bold; font-size: 12px; margin-top: 8px;")
        layout.addRow(section2)

        self._click_fb_check = QCheckBox("点击反馈")
        self._click_fb_check.setChecked(self.settings.pet_click_feedback_enabled)
        layout.addRow("", self._click_fb_check)

        self._click_cooldown_spin = QSpinBox()
        self._click_cooldown_spin.setRange(100, 5000)
        self._click_cooldown_spin.setSingleStep(100)
        self._click_cooldown_spin.setValue(self.settings.pet_click_cooldown_ms)
        layout.addRow("点击冷却(ms):", self._click_cooldown_spin)

        self._clock_check = QCheckBox("宠物时钟")
        self._clock_check.setChecked(self.settings.pet_clock_enabled)
        layout.addRow("", self._clock_check)

        self._clock_seconds_check = QCheckBox("显示秒")
        self._clock_seconds_check.setChecked(self.settings.pet_clock_show_seconds)
        layout.addRow("", self._clock_seconds_check)

        self._clock_refresh_spin = QSpinBox()
        self._clock_refresh_spin.setRange(1, 300)
        self._clock_refresh_spin.setValue(max(1, self.settings.pet_clock_refresh_ms // 1000))
        layout.addRow("时钟刷新(秒):", self._clock_refresh_spin)

        self._exp_bar_check = QCheckBox("显示经验条")
        self._exp_bar_check.setChecked(self.settings.pet_exp_bar_enabled)
        layout.addRow("", self._exp_bar_check)

        self._state_check = QCheckBox("宠物状态系统")
        self._state_check.setChecked(self.settings.pet_state_enabled)
        layout.addRow("", self._state_check)

        self._idle_after_spin = QSpinBox()
        self._idle_after_spin.setRange(1, 240)
        self._idle_after_spin.setValue(self.settings.pet_idle_after_minutes)
        layout.addRow("待机触发(分钟):", self._idle_after_spin)

        section3 = QLabel("💬 聊天增强")
        section3.setStyleSheet("color: #FF8A3D; font-weight: bold; font-size: 12px; margin-top: 8px;")
        layout.addRow(section3)

        self._msg_time_check = QCheckBox("消息时间显示")
        self._msg_time_check.setChecked(self.settings.chat_message_time_enabled)
        layout.addRow("", self._msg_time_check)

        self._divider_check = QCheckBox("时间分隔条")
        self._divider_check.setChecked(self.settings.chat_time_divider_enabled)
        layout.addRow("", self._divider_check)

        self._divider_gap_spin = QSpinBox()
        self._divider_gap_spin.setRange(1, 240)
        self._divider_gap_spin.setValue(self.settings.chat_time_divider_gap_minutes)
        layout.addRow("分隔间隔(分钟):", self._divider_gap_spin)

        self._timeline_check = QCheckBox("右侧对话时间线")
        self._timeline_check.setChecked(self.settings.conversation_timeline_enabled)
        layout.addRow("", self._timeline_check)

        self._timeline_gap_spin = QSpinBox()
        self._timeline_gap_spin.setRange(4, 48)
        self._timeline_gap_spin.setValue(self.settings.conversation_timeline_min_dot_gap_px)
        layout.addRow("时间线点间距(px):", self._timeline_gap_spin)

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)
        return w

    def _build_advanced_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        layout.setSpacing(12)

        self._advanced_container = QWidget()
        adv_layout = QFormLayout(self._advanced_container)
        adv_layout.setSpacing(12)

        api_key_layout = QHBoxLayout()
        self.api_key_input = QLineEdit(self.settings.llm_api_key)
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_toggle = QPushButton("显示")
        self.api_key_toggle.setCheckable(True)
        self.api_key_toggle.clicked.connect(self._toggle_api_key_visibility)
        api_key_layout.addWidget(self.api_key_input)
        api_key_layout.addWidget(self.api_key_toggle)
        adv_layout.addRow("LLM API Key:", api_key_layout)

        api_help = QLabel("API Key 是 AI 聊天必填项；图片分析模型可选，留空时不启用图片分析。")
        api_help.setWordWrap(True)
        api_help.setStyleSheet("color: #A0846C; font-size: 11px;")
        adv_layout.addRow("", api_help)

        self.base_url_input = QLineEdit(self.settings.llm_base_url)
        adv_layout.addRow("LLM Base URL:", self.base_url_input)

        self.model_input = QLineEdit(self.settings.llm_model)
        adv_layout.addRow("LLM Model:", self.model_input)

        self.multimodal_model_input = QLineEdit(self.settings.llm_multimodal_model)
        adv_layout.addRow("Image Model:", self.multimodal_model_input)

        self.multimodal_base_url_input = QLineEdit(self.settings.llm_multimodal_base_url or "")
        self.multimodal_base_url_input.setPlaceholderText("留空则使用 LLM Base URL")
        adv_layout.addRow("Image Base URL:", self.multimodal_base_url_input)

        self.multimodal_api_key_input = QLineEdit(self.settings.llm_multimodal_api_key or "")
        self.multimodal_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.multimodal_api_key_input.setPlaceholderText("留空则使用 LLM API Key")
        adv_layout.addRow("Image API Key:", self.multimodal_api_key_input)

        self.max_iterations_spin = QSpinBox()
        self.max_iterations_spin.setRange(1, 200)
        self.max_iterations_spin.setValue(self.settings.nanobot_max_iterations)
        adv_layout.addRow("最大工具轮次:", self.max_iterations_spin)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(30, 600)
        self.timeout_spin.setValue(self.settings.task_timeout)
        adv_layout.addRow("任务超时 (秒):", self.timeout_spin)

        self.shell_check = QCheckBox("启用 Shell 工具 (危险)")
        self.shell_check.setChecked(self.settings.shell_enabled)
        adv_layout.addRow("工具:", self.shell_check)

        self.guardrails_check = QCheckBox("启用安全护栏 (限制文件路径/命令/URL)")
        self.guardrails_check.setChecked(self.settings.guardrails_enabled)
        self.guardrails_check.setToolTip(
            "关闭后桌宠可访问电脑上任意位置、执行任意命令，不再受安全限制"
        )
        adv_layout.addRow("安全:", self.guardrails_check)

        layout.addRow(self._advanced_container)
        return w

    def _build_4291_tab(self) -> QWidget:
        w = QWidget()
        outer_layout = QVBoxLayout(w)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(w)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMaximumHeight(360)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)

        memory_group = QGroupBox("用户配置记忆")
        memory_layout = QFormLayout()
        memory_layout.setSpacing(8)

        self._memory_enabled_check = QCheckBox("启用AI记忆用户配置")
        memory_layout.addRow("启用:", self._memory_enabled_check)

        self._memory_inject_check = QCheckBox("将用户配置注入AI提示词")
        memory_layout.addRow("注入提示词:", self._memory_inject_check)

        self._memory_max_chars_spin = QSpinBox()
        self._memory_max_chars_spin.setRange(500, 5000)
        self._memory_max_chars_spin.setSingleStep(100)
        memory_layout.addRow("最大注入字符:", self._memory_max_chars_spin)

        self._memory_update_freq_spin = QSpinBox()
        self._memory_update_freq_spin.setRange(1, 50)
        memory_layout.addRow("每N条消息更新:", self._memory_update_freq_spin)

        self._memory_notice_check = QCheckBox("配置更新时显示通知")
        memory_layout.addRow("更新通知:", self._memory_notice_check)

        memory_group.setLayout(memory_layout)
        layout.addWidget(memory_group)

        focus_group = QGroupBox("专注模式")
        focus_layout = QFormLayout()
        focus_layout.setSpacing(8)

        self._focus_enabled_check = QCheckBox("启用专注模式")
        focus_layout.addRow("启用:", self._focus_enabled_check)

        self._focus_minutes_spin = QSpinBox()
        self._focus_minutes_spin.setRange(1, 120)
        self._focus_minutes_spin.setSuffix(" 分钟")
        focus_layout.addRow("专注时长:", self._focus_minutes_spin)

        self._focus_break_spin = QSpinBox()
        self._focus_break_spin.setRange(1, 30)
        self._focus_break_spin.setSuffix(" 分钟")
        focus_layout.addRow("休息时长:", self._focus_break_spin)

        self._focus_reminder_check = QCheckBox("专注结束时提醒")
        focus_layout.addRow("结束提醒:", self._focus_reminder_check)

        self._focus_mute_check = QCheckBox("专注时静音问候")
        focus_layout.addRow("静音问候:", self._focus_mute_check)

        self._focus_status_input = QLineEdit()
        self._focus_status_input.setPlaceholderText("Focusing")
        focus_layout.addRow("状态文本:", self._focus_status_input)

        self._focus_auto_check = QCheckBox("专注后自动开始休息")
        focus_layout.addRow("自动循环:", self._focus_auto_check)

        focus_group.setLayout(focus_layout)
        layout.addWidget(focus_group)

        skill_group = QGroupBox("技能面板")
        skill_layout = QFormLayout()
        skill_layout.setSpacing(8)

        self._skill_enabled_check = QCheckBox("启用技能面板")
        skill_layout.addRow("启用:", self._skill_enabled_check)

        self._skill_examples_check = QCheckBox("显示示例提示词")
        skill_layout.addRow("显示示例:", self._skill_examples_check)

        self._skill_fill_check = QCheckBox("点击示例填充输入框")
        skill_layout.addRow("点击填充:", self._skill_fill_check)

        self._skill_badge_check = QCheckBox("显示权限标签")
        skill_layout.addRow("权限标签:", self._skill_badge_check)

        skill_group.setLayout(skill_layout)
        layout.addWidget(skill_group)

        layout.addStretch()

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)
        return w

    def _build_52_tab(self) -> QWidget:
        w = QWidget()
        outer_layout = QVBoxLayout(w)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(w)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMaximumHeight(360)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)

        memory_group = QGroupBox("记忆系统 V2")
        memory_layout = QFormLayout()
        memory_layout.setSpacing(8)

        self._52_memory_fts5_check = QCheckBox("启用 FTS5 全文搜索")
        memory_layout.addRow("全文搜索:", self._52_memory_fts5_check)

        self._52_memory_budget_chars_spin = QSpinBox()
        self._52_memory_budget_chars_spin.setRange(1000, 10000)
        self._52_memory_budget_chars_spin.setSingleStep(500)
        memory_layout.addRow("Prompt 记忆预算(字符):", self._52_memory_budget_chars_spin)

        self._52_memory_budget_percent_spin = QSpinBox()
        self._52_memory_budget_percent_spin.setRange(5, 50)
        self._52_memory_budget_percent_spin.setSuffix(" %")
        memory_layout.addRow("Prompt 记忆占比上限:", self._52_memory_budget_percent_spin)

        self._52_memory_episodic_spin = QSpinBox()
        self._52_memory_episodic_spin.setRange(1, 20)
        memory_layout.addRow("最大 episodic 召回数:", self._52_memory_episodic_spin)

        self._52_memory_summary_turns_spin = QSpinBox()
        self._52_memory_summary_turns_spin.setRange(2, 50)
        memory_layout.addRow("对话摘要触发轮数:", self._52_memory_summary_turns_spin)

        self._52_memory_summary_chars_spin = QSpinBox()
        self._52_memory_summary_chars_spin.setRange(500, 5000)
        self._52_memory_summary_chars_spin.setSingleStep(100)
        memory_layout.addRow("摘要最大字符数:", self._52_memory_summary_chars_spin)

        self._52_memory_migration_check = QCheckBox("启用旧版 USER.md 自动迁移")
        memory_layout.addRow("迁移:", self._52_memory_migration_check)

        memory_group.setLayout(memory_layout)
        layout.addWidget(memory_group)

        # Skill V2
        skill_group = QGroupBox("技能系统 V2")
        skill_layout = QFormLayout()
        skill_layout.setSpacing(8)

        self._52_skill_auto_candidate_check = QCheckBox("启用自动 skill candidate 生成")
        skill_layout.addRow("自动候选:", self._52_skill_auto_candidate_check)

        self._52_skill_min_tools_spin = QSpinBox()
        self._52_skill_min_tools_spin.setRange(0, 10)
        skill_layout.addRow("最小工具调用数:", self._52_skill_min_tools_spin)

        self._52_skill_auto_approve_spin = QSpinBox()
        self._52_skill_auto_approve_spin.setRange(50, 100)
        self._52_skill_auto_approve_spin.setSuffix(" %")
        skill_layout.addRow("自动批准阈值:", self._52_skill_auto_approve_spin)

        self._52_skill_maint_hours_spin = QSpinBox()
        self._52_skill_maint_hours_spin.setRange(1, 168)
        self._52_skill_maint_hours_spin.setSuffix(" 小时")
        skill_layout.addRow("维护间隔:", self._52_skill_maint_hours_spin)

        self._52_skill_stale_review_spin = QSpinBox()
        self._52_skill_stale_review_spin.setRange(7, 180)
        self._52_skill_stale_review_spin.setSuffix(" 天")
        skill_layout.addRow("陈旧标记天数:", self._52_skill_stale_review_spin)

        self._52_skill_stale_disable_spin = QSpinBox()
        self._52_skill_stale_disable_spin.setRange(7, 365)
        self._52_skill_stale_disable_spin.setSuffix(" 天")
        skill_layout.addRow("自动禁用天数:", self._52_skill_stale_disable_spin)

        self._52_skill_max_lines_spin = QSpinBox()
        self._52_skill_max_lines_spin.setRange(100, 2000)
        self._52_skill_max_lines_spin.setSingleStep(50)
        skill_layout.addRow("Skill 文件最大行数:", self._52_skill_max_lines_spin)

        self._52_skill_failure_threshold_spin = QSpinBox()
        self._52_skill_failure_threshold_spin.setRange(10, 90)
        self._52_skill_failure_threshold_spin.setSuffix(" %")
        skill_layout.addRow("失败率阈值:", self._52_skill_failure_threshold_spin)

        self._52_skill_failure_min_uses_spin = QSpinBox()
        self._52_skill_failure_min_uses_spin.setRange(1, 50)
        skill_layout.addRow("失败率最小使用次数:", self._52_skill_failure_min_uses_spin)

        skill_group.setLayout(skill_layout)
        layout.addWidget(skill_group)

        # Memory 5.3
        mem53_group = QGroupBox("记忆系统 5.3 · 统一记忆网关")
        mem53_layout = QFormLayout()
        mem53_layout.setSpacing(8)

        self._53_session_search_check = QCheckBox(
            "允许 agent 搜索历史聊天记录（会向 LLM 发送历史片段）"
        )
        mem53_layout.addRow("会话搜索:", self._53_session_search_check)

        self._53_block_dream_check = QCheckBox("拦截 nanobot Dream 记忆命令")
        mem53_layout.addRow("禁用 Dream:", self._53_block_dream_check)

        self._53_gateway_confidence_spin = QSpinBox()
        self._53_gateway_confidence_spin.setRange(50, 100)
        self._53_gateway_confidence_spin.setSuffix(" %")
        self._53_gateway_confidence_spin.setToolTip("低于此置信度的记忆 patch 会被网关拒绝")
        mem53_layout.addRow("网关最低置信度:", self._53_gateway_confidence_spin)

        self._53_hot_user_spin = QSpinBox()
        self._53_hot_user_spin.setRange(100, 1000)
        self._53_hot_user_spin.setSingleStep(50)
        self._53_hot_user_spin.setSuffix(" tokens")
        self._53_hot_user_spin.setToolTip("始终注入的用户热记忆预算")
        mem53_layout.addRow("用户热记忆预算:", self._53_hot_user_spin)

        self._53_hot_system_spin = QSpinBox()
        self._53_hot_system_spin.setRange(100, 600)
        self._53_hot_system_spin.setSingleStep(50)
        self._53_hot_system_spin.setSuffix(" tokens")
        mem53_layout.addRow("系统热记忆预算:", self._53_hot_system_spin)

        self._53_hot_project_spin = QSpinBox()
        self._53_hot_project_spin.setRange(200, 1500)
        self._53_hot_project_spin.setSingleStep(100)
        self._53_hot_project_spin.setSuffix(" tokens")
        mem53_layout.addRow("项目热记忆预算:", self._53_hot_project_spin)

        self._53_lint_enabled_check = QCheckBox("启动时运行记忆体检")
        mem53_layout.addRow("记忆体检:", self._53_lint_enabled_check)

        mem53_group.setLayout(mem53_layout)
        layout.addWidget(mem53_group)

        layout.addStretch()
        scroll.setWidget(content)
        outer_layout.addWidget(scroll)
        return w

    def _refresh_ui(self):
        self.pet_name_input.setText(self.settings.pet_name)
        self.api_key_input.setText(self.settings.llm_api_key)
        self.base_url_input.setText(self.settings.llm_base_url)
        self.model_input.setText(self.settings.llm_model)
        self.multimodal_model_input.setText(self.settings.llm_multimodal_model)
        self.multimodal_base_url_input.setText(self.settings.llm_multimodal_base_url or "")
        self.multimodal_api_key_input.setText(self.settings.llm_multimodal_api_key or "")
        self.max_iterations_spin.setValue(self.settings.nanobot_max_iterations)
        self.timeout_spin.setValue(self.settings.task_timeout)
        self.shell_check.setChecked(self.settings.shell_enabled)
        self.guardrails_check.setChecked(self.settings.guardrails_enabled)
        self._greeting_check.setChecked(self.settings.companion_greeting_enabled)
        self._anim_check.setChecked(self.settings.pet_avatar_animation_enabled)
        self._top_check.setChecked(getattr(self._pet_appearance, "always_on_top", True))
        self._click_fb_check.setChecked(self.settings.pet_click_feedback_enabled)
        self._click_cooldown_spin.setValue(self.settings.pet_click_cooldown_ms)
        self._clock_check.setChecked(self.settings.pet_clock_enabled)
        self._clock_seconds_check.setChecked(self.settings.pet_clock_show_seconds)
        self._clock_refresh_spin.setValue(max(1, self.settings.pet_clock_refresh_ms // 1000))
        self._exp_bar_check.setChecked(self.settings.pet_exp_bar_enabled)
        self._state_check.setChecked(self.settings.pet_state_enabled)
        self._idle_after_spin.setValue(self.settings.pet_idle_after_minutes)
        self._msg_time_check.setChecked(self.settings.chat_message_time_enabled)
        self._divider_check.setChecked(self.settings.chat_time_divider_enabled)
        self._divider_gap_spin.setValue(self.settings.chat_time_divider_gap_minutes)
        self._timeline_check.setChecked(self.settings.conversation_timeline_enabled)
        self._timeline_gap_spin.setValue(self.settings.conversation_timeline_min_dot_gap_px)
        self._daily_greet_check.setChecked(self.settings.daily_greeting_enabled)
        self._daily_greet_max_spin.setValue(self.settings.daily_greeting_max_per_day)

        self._memory_enabled_check.setChecked(self.settings.memory_profile_enabled)
        self._memory_inject_check.setChecked(self.settings.memory_profile_inject_enabled)
        self._memory_max_chars_spin.setValue(self.settings.memory_profile_max_inject_chars)
        self._memory_update_freq_spin.setValue(
            self.settings.memory_profile_update_every_n_user_messages
        )
        self._memory_notice_check.setChecked(self.settings.memory_profile_show_update_notice)

        self._focus_enabled_check.setChecked(self.settings.focus_mode_enabled)
        self._focus_minutes_spin.setValue(self.settings.focus_default_minutes)
        self._focus_break_spin.setValue(self.settings.focus_break_minutes)
        self._focus_reminder_check.setChecked(self.settings.focus_end_reminder_enabled)
        self._focus_mute_check.setChecked(self.settings.focus_mute_greeting)
        self._focus_status_input.setText(self.settings.focus_status_text)
        self._focus_auto_check.setChecked(self.settings.focus_auto_loop)

        self._skill_enabled_check.setChecked(self.settings.skill_panel_enabled)
        self._skill_examples_check.setChecked(self.settings.skill_panel_show_examples)
        self._skill_fill_check.setChecked(self.settings.skill_panel_click_to_fill_input)
        self._skill_badge_check.setChecked(self.settings.skill_panel_show_permission_badge)

        self._52_memory_fts5_check.setChecked(self.settings.memory_use_fts5)
        self._52_memory_budget_chars_spin.setValue(self.settings.memory_prompt_budget_chars)
        self._52_memory_budget_percent_spin.setValue(int(self.settings.memory_prompt_budget_percent * 100))
        self._52_memory_episodic_spin.setValue(self.settings.memory_max_episodic_results)
        self._52_memory_summary_turns_spin.setValue(self.settings.memory_summary_trigger_turns)
        self._52_memory_summary_chars_spin.setValue(self.settings.memory_summary_max_chars)
        self._52_memory_migration_check.setChecked(self.settings.memory_enable_migration)

        self._52_skill_auto_candidate_check.setChecked(self.settings.skill_auto_candidate_enabled)
        self._52_skill_min_tools_spin.setValue(self.settings.skill_candidate_min_tools_used)
        self._52_skill_auto_approve_spin.setValue(int(self.settings.skill_candidate_auto_approve_threshold * 100))
        self._52_skill_maint_hours_spin.setValue(self.settings.skill_maintenance_interval_hours)
        self._52_skill_stale_review_spin.setValue(self.settings.skill_stale_review_days)
        self._52_skill_stale_disable_spin.setValue(self.settings.skill_stale_disable_days)
        self._52_skill_max_lines_spin.setValue(self.settings.skill_max_file_lines)
        self._52_skill_failure_threshold_spin.setValue(int(self.settings.skill_failure_rate_threshold * 100))
        self._52_skill_failure_min_uses_spin.setValue(self.settings.skill_failure_rate_min_uses)

        self._53_session_search_check.setChecked(self.settings.memory_session_search_enabled)
        self._53_block_dream_check.setChecked(self.settings.memory_block_dream_commands)
        self._53_gateway_confidence_spin.setValue(int(self.settings.memory_gateway_min_confidence * 100))
        self._53_hot_user_spin.setValue(self.settings.memory_hot_user_profile_tokens)
        self._53_hot_system_spin.setValue(self.settings.memory_hot_system_profile_tokens)
        self._53_hot_project_spin.setValue(self.settings.memory_hot_project_context_tokens)
        self._53_lint_enabled_check.setChecked(self.settings.memory_lint_enabled)

        self._update_pet_preview()
        self._refresh_theme_buttons()
        self._refresh_user_themes_list()

    def _toggle_api_key_visibility(self):
        if self.api_key_toggle.isChecked():
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.api_key_toggle.setText("隐藏")
        else:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.api_key_toggle.setText("显示")

    def _on_upload_pet_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择宠物图片", "",
            "宠物图片 (*.png *.jpg *.jpeg *.webp *.gif)"
        )
        if not file_path:
            return

        path = Path(file_path)
        result = self._asset_service.validate_asset(path)
        if not result.valid:
            QMessageBox.warning(self, "无效文件", result.error)
            return

        asset_type = self._asset_service.detect_asset_type(path)
        dest_path = self._asset_service.copy_to_app_data(path)

        if self._pet_appearance.custom_asset_path:
            old = Path(self._pet_appearance.custom_asset_path)
            self._asset_service.remove_asset(old)

        self._pet_appearance.custom_asset_path = str(dest_path)
        self._pet_appearance.custom_asset_type = asset_type
        self._update_pet_preview()

    def _on_reset_pet_image(self):
        if self._pet_appearance.custom_asset_path:
            old = Path(self._pet_appearance.custom_asset_path)
            self._asset_service.remove_asset(old)
        self._pet_appearance.custom_asset_path = None
        self._pet_appearance.custom_asset_type = "default"
        self._update_pet_preview()

    def _update_pet_preview(self):
        self._pet_preview_label.clear()
        if self._preview_movie:
            self._preview_movie.stop()
            self._preview_movie.deleteLater()
            self._preview_movie = None

        path = self._pet_appearance.custom_asset_path
        if path and Path(path).exists():
            suffix = Path(path).suffix.lower()
            name = Path(path).name
            if len(name) > 24:
                name = name[:12] + "..." + name[-12:]
            self._pet_preview_text.setText(name)

            if suffix == ".gif":
                from PySide6.QtGui import QMovie
                movie = QMovie(path)
                if movie.isValid():
                    movie.setScaledSize(self._pet_preview_label.size())
                    self._pet_preview_label.setMovie(movie)
                    movie.start()
                    self._preview_movie = movie
                    return
                movie.deleteLater()

            pixmap = QPixmap(path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    self._pet_preview_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._pet_preview_label.setPixmap(pixmap)
                return

        self._pet_preview_text.setText("默认宠物形象")
        pixmap = QPixmap(100, 100)
        pixmap.fill(Qt.GlobalColor.lightGray)
        self._pet_preview_label.setPixmap(pixmap)

    def _validate_settings(self) -> str | None:
        pet_name = self.pet_name_input.text().strip()
        if not pet_name:
            return "宠物名字不能为空。"
        if len(pet_name) > 50:
            return "宠物名字不能超过50个字符。"

        base_url = self.base_url_input.text().strip()
        if base_url:
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return f"无效的 URL 格式: {base_url}"

        multimodal_base_url = self.multimodal_base_url_input.text().strip()
        if multimodal_base_url:
            from urllib.parse import urlparse
            parsed = urlparse(multimodal_base_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return f"无效的图片模型 URL 格式: {multimodal_base_url}"

        model = self.model_input.text().strip()
        if not model:
            return "LLM Model 不能为空。"

        return None

    def _on_save(self):
        error = self._validate_settings()
        if error:
            QMessageBox.warning(self, "验证错误", error)
            return

        try:
            api_key_input = self.api_key_input.text().strip()
            if not api_key_input or api_key_input == self._original_api_key:
                api_key_to_save = self._original_api_key
            else:
                api_key_to_save = api_key_input

            self.repo.set_setting("pet_name", self.pet_name_input.text().strip())
            self.repo.set_setting("user_name", self.user_name_input.text().strip())
            self.repo.set_setting("llm_api_key", api_key_to_save)
            self.repo.set_setting("llm_base_url", self.base_url_input.text().strip())
            self.repo.set_setting("llm_model", self.model_input.text().strip())
            self.repo.set_setting("llm_multimodal_model",
                                  self.multimodal_model_input.text().strip())
            self.repo.set_setting("llm_multimodal_base_url",
                                  self.multimodal_base_url_input.text().strip())
            self.repo.set_setting("llm_multimodal_api_key",
                                  self.multimodal_api_key_input.text().strip())
            self.repo.set_setting("nanobot_max_iterations",
                                  str(self.max_iterations_spin.value()))
            self.repo.set_setting("task_timeout", str(self.timeout_spin.value()))
            self.repo.set_setting("shell_enabled", str(self.shell_check.isChecked()))
            self.repo.set_setting("guardrails_enabled", str(self.guardrails_check.isChecked()))
            self.repo.set_setting("companion_greeting_enabled",
                                   str(self._greeting_check.isChecked()))
            self.repo.set_setting("pet_avatar_animation_enabled",
                                   str(self._anim_check.isChecked()))
            self.repo.set_setting("pet_click_feedback_enabled",
                                   str(self._click_fb_check.isChecked()))
            self.repo.set_setting("pet_click_cooldown_ms",
                                   str(self._click_cooldown_spin.value()))
            self.repo.set_setting("pet_clock_enabled",
                                   str(self._clock_check.isChecked()))
            self.repo.set_setting("pet_clock_show_seconds",
                                   str(self._clock_seconds_check.isChecked()))
            self.repo.set_setting("pet_clock_refresh_ms",
                                   str(self._clock_refresh_spin.value() * 1000))
            self.repo.set_setting("pet_exp_bar_enabled",
                                   str(self._exp_bar_check.isChecked()))
            self.repo.set_setting("pet_state_enabled",
                                   str(self._state_check.isChecked()))
            self.repo.set_setting("pet_idle_after_minutes",
                                   str(self._idle_after_spin.value()))
            self.repo.set_setting("chat_message_time_enabled",
                                   str(self._msg_time_check.isChecked()))
            self.repo.set_setting("chat_time_divider_enabled",
                                   str(self._divider_check.isChecked()))
            self.repo.set_setting("chat_time_divider_gap_minutes",
                                   str(self._divider_gap_spin.value()))
            self.repo.set_setting("conversation_timeline_enabled",
                                   str(self._timeline_check.isChecked()))
            self.repo.set_setting("conversation_timeline_min_dot_gap_px",
                                   str(self._timeline_gap_spin.value()))
            self.repo.set_setting("daily_greeting_enabled",
                                   str(self._daily_greet_check.isChecked()))
            self.repo.set_setting("daily_greeting_max_per_day",
                                   str(self._daily_greet_max_spin.value()))

            self.repo.set_setting("memory_profile_enabled",
                                   str(self._memory_enabled_check.isChecked()))
            self.repo.set_setting("memory_profile_inject_enabled",
                                   str(self._memory_inject_check.isChecked()))
            self.repo.set_setting("memory_profile_max_inject_chars",
                                   str(self._memory_max_chars_spin.value()))
            self.repo.set_setting("memory_profile_update_every_n_user_messages",
                                   str(self._memory_update_freq_spin.value()))
            self.repo.set_setting("memory_profile_show_update_notice",
                                   str(self._memory_notice_check.isChecked()))

            self.repo.set_setting("focus_mode_enabled",
                                   str(self._focus_enabled_check.isChecked()))
            self.repo.set_setting("focus_default_minutes",
                                   str(self._focus_minutes_spin.value()))
            self.repo.set_setting("focus_break_minutes",
                                   str(self._focus_break_spin.value()))
            self.repo.set_setting("focus_end_reminder_enabled",
                                   str(self._focus_reminder_check.isChecked()))
            self.repo.set_setting("focus_mute_greeting",
                                   str(self._focus_mute_check.isChecked()))
            self.repo.set_setting("focus_status_text",
                                   self._focus_status_input.text())
            self.repo.set_setting("focus_auto_loop",
                                   str(self._focus_auto_check.isChecked()))

            self.repo.set_setting("skill_panel_enabled",
                                   str(self._skill_enabled_check.isChecked()))
            self.repo.set_setting("skill_panel_show_examples",
                                   str(self._skill_examples_check.isChecked()))
            self.repo.set_setting("skill_panel_click_to_fill_input",
                                   str(self._skill_fill_check.isChecked()))
            self.repo.set_setting("skill_panel_show_permission_badge",
                                   str(self._skill_badge_check.isChecked()))

            self.repo.set_setting("memory_use_fts5",
                                   str(self._52_memory_fts5_check.isChecked()))
            self.repo.set_setting("memory_prompt_budget_chars",
                                   str(self._52_memory_budget_chars_spin.value()))
            self.repo.set_setting("memory_prompt_budget_percent",
                                   str(self._52_memory_budget_percent_spin.value() / 100))
            self.repo.set_setting("memory_max_episodic_results",
                                   str(self._52_memory_episodic_spin.value()))
            self.repo.set_setting("memory_summary_trigger_turns",
                                   str(self._52_memory_summary_turns_spin.value()))
            self.repo.set_setting("memory_summary_max_chars",
                                   str(self._52_memory_summary_chars_spin.value()))
            self.repo.set_setting("memory_enable_migration",
                                   str(self._52_memory_migration_check.isChecked()))

            self.repo.set_setting("skill_auto_candidate_enabled",
                                   str(self._52_skill_auto_candidate_check.isChecked()))
            self.repo.set_setting("skill_candidate_min_tools_used",
                                   str(self._52_skill_min_tools_spin.value()))
            self.repo.set_setting("skill_candidate_auto_approve_threshold",
                                   str(self._52_skill_auto_approve_spin.value() / 100))
            self.repo.set_setting("skill_maintenance_interval_hours",
                                   str(self._52_skill_maint_hours_spin.value()))
            self.repo.set_setting("skill_stale_review_days",
                                   str(self._52_skill_stale_review_spin.value()))
            self.repo.set_setting("skill_stale_disable_days",
                                   str(self._52_skill_stale_disable_spin.value()))
            self.repo.set_setting("skill_max_file_lines",
                                   str(self._52_skill_max_lines_spin.value()))
            self.repo.set_setting("skill_failure_rate_threshold",
                                   str(self._52_skill_failure_threshold_spin.value() / 100))
            self.repo.set_setting("skill_failure_rate_min_uses",
                                   str(self._52_skill_failure_min_uses_spin.value()))

            # 5.3 Memory System
            self.repo.set_setting("memory_session_search_enabled",
                                   str(self._53_session_search_check.isChecked()))
            self.repo.set_setting("memory_block_dream_commands",
                                   str(self._53_block_dream_check.isChecked()))
            self.repo.set_setting("memory_gateway_min_confidence",
                                   str(self._53_gateway_confidence_spin.value() / 100))
            self.repo.set_setting("memory_hot_user_profile_tokens",
                                   str(self._53_hot_user_spin.value()))
            self.repo.set_setting("memory_hot_system_profile_tokens",
                                   str(self._53_hot_system_spin.value()))
            self.repo.set_setting("memory_hot_project_context_tokens",
                                   str(self._53_hot_project_spin.value()))
            self.repo.set_setting("memory_lint_enabled",
                                   str(self._53_lint_enabled_check.isChecked()))

            from ui.theme import ThemeManager
            mgr = ThemeManager.instance()
            self.repo.set_setting("theme_preset", mgr.preset.value)

            self._pet_appearance.scale = self._scale_slider.value() / 100.0
            self._pet_appearance.always_on_top = self._top_check.isChecked()
            save_appearance(self._pet_appearance)

            updated = reload_settings()
            self.settings = updated

            try:
                save_settings_to_env(updated)
            except Exception as env_err:
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to write .env: {env_err}")

            self.settings_saved.emit(updated)
            QMessageBox.information(self, "成功", "设置已保存！")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")

    def _on_preset_selected(self, preset_id: str):
        from ui.theme import ThemePreset, ThemeManager
        mgr = ThemeManager.instance()
        preset = ThemePreset(preset_id)
        mgr.set_preset(preset)
        self.repo.set_setting("theme_preset", preset_id)
        self.repo.set_setting("active_user_theme_id", "")
        self._refresh_theme_buttons()

    def _on_new_theme(self):
        from ui.theme_editor import ThemeEditorDialog
        from ui.theme import ThemeManager
        from core.storage.theme_repo import ThemeRepository

        mgr = ThemeManager.instance()
        initial = mgr.current.__dict__

        dialog = ThemeEditorDialog(ThemeRepository(), initial_colors=initial, parent=self)
        dialog.theme_saved.connect(self._on_theme_saved)
        dialog.exec()

    def _on_generate_from_pet(self):
        from PySide6.QtWidgets import QFileDialog
        from core.services.theme_generator import ThemeGenerator
        from ui.theme_editor import ThemeEditorDialog
        from core.storage.theme_repo import ThemeRepository

        appearance = self._pet_appearance
        image_path = None

        if appearance.custom_asset_path and Path(appearance.custom_asset_path).exists():
            image_path = appearance.custom_asset_path
        else:
            default_path = Path("ui/assets/pet_idle.gif")
            if default_path.exists():
                image_path = str(default_path)

        if not image_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "选择宠物图片", "",
                "图片文件 (*.png *.jpg *.jpeg *.webp *.gif)"
            )
            if not file_path:
                return
            image_path = file_path

        try:
            generator = ThemeGenerator()
            palette = generator.extract_palette(image_path)

            if not palette or len(palette) < 3:
                QMessageBox.warning(self, "提示", "无法从图片中提取足够的颜色")
                return

            theme_data = generator.generate_theme(palette, "宠物主题")

            dialog = ThemeEditorDialog(
                ThemeRepository(),
                initial_colors=theme_data,
                theme_name="宠物主题",
                parent=self
            )
            dialog.theme_saved.connect(self._on_theme_saved)
            dialog.exec()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成主题失败: {e}")

    def _on_theme_saved(self, theme_id: str):
        from ui.theme import ThemeManager
        mgr = ThemeManager.instance()
        mgr.load_user_theme(theme_id)
        self.repo.set_setting("theme_preset", "custom")
        self.repo.set_setting("active_user_theme_id", theme_id)
        self._refresh_theme_buttons()
        self._refresh_user_themes_list()

    def _refresh_theme_buttons(self):
        from ui.theme import ThemeManager
        mgr = ThemeManager.instance()
        current_preset = mgr.preset.value if mgr.preset else "cozy_orange"

        for pid, btn in self._preset_buttons.items():
            btn.setChecked(pid == current_preset)

    def _refresh_user_themes_list(self):
        while self._user_themes_layout.count():
            item = self._user_themes_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        from ui.theme import ThemeManager
        mgr = ThemeManager.instance()
        themes = mgr.get_user_themes()

        if not themes:
            empty = QLabel("暂无自定义主题")
            empty.setStyleSheet("color: #9CA3AF; padding: 20px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._user_themes_layout.addWidget(empty)
            return

        for theme in themes:
            card = self._create_user_theme_card(theme)
            self._user_themes_layout.addWidget(card)

    def _create_user_theme_card(self, theme: dict[str, object]) -> QWidget:
        import json
        from PySide6.QtWidgets import QMenu

        card = QWidget()
        card.setStyleSheet(
            "QWidget { background: white; border: 1px solid #E5E7EB; "
            "border-radius: 8px; padding: 8px; }"
            "QWidget:hover { border-color: #F97316; }"
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)

        colors_json = str(theme.get("colors_json", "{}"))
        colors = json.loads(colors_json)
        primary = str(colors.get("primary", "#808080"))

        color_label = QLabel()
        color_label.setFixedSize(24, 24)
        color_label.setStyleSheet(
            f"background: {primary}; border-radius: 12px; "
            f"border: 1px solid #ccc;"
        )
        layout.addWidget(color_label)

        name = str(theme.get("name", "未命名"))
        name_label = QLabel(name)
        name_label.setFont(QFont("Microsoft YaHei", 10))
        layout.addWidget(name_label, stretch=1)

        source = str(theme.get("source", "manual"))
        if source == "pet-ui-generated":
            badge = QLabel("宠物生成")
            badge.setStyleSheet(
                "background: #FEF3C7; color: #92400E; "
                "padding: 2px 6px; border-radius: 4px; font-size: 10px;"
            )
            layout.addWidget(badge)

        actions_btn = QPushButton("...")
        actions_btn.setFixedSize(28, 28)
        actions_btn.setStyleSheet(
            "QPushButton { border: none; border-radius: 14px; }"
            "QPushButton:hover { background: #F3F4F6; }"
        )

        theme_id = str(theme.get("id", ""))

        def show_menu():
            menu = QMenu(card)
            menu.addAction("启用", lambda: self._activate_user_theme(theme_id))
            menu.addAction("编辑", lambda: self._edit_user_theme(theme_id))
            menu.addAction("删除", lambda: self._delete_user_theme(theme_id))
            menu.exec(actions_btn.mapToGlobal(actions_btn.rect().bottomRight()))

        actions_btn.clicked.connect(show_menu)
        layout.addWidget(actions_btn)

        return card

    def _activate_user_theme(self, theme_id: str):
        from ui.theme import ThemeManager
        mgr = ThemeManager.instance()
        if mgr.load_user_theme(theme_id):
            self.repo.set_setting("theme_preset", "custom")
            self.repo.set_setting("active_user_theme_id", theme_id)
            self._refresh_theme_buttons()

    def _edit_user_theme(self, theme_id: str):
        from ui.theme_editor import ThemeEditorDialog
        from core.storage.theme_repo import ThemeRepository
        import json

        theme_repo = ThemeRepository()
        theme_data = theme_repo.get_by_id(theme_id)

        if theme_data:
            colors = json.loads(theme_data.get("colors_json", "{}"))
            name = theme_data.get("name", "")

            dialog = ThemeEditorDialog(
                theme_repo,
                theme_id=theme_id,
                initial_colors=colors,
                theme_name=name,
                parent=self
            )
            dialog.theme_saved.connect(self._on_theme_saved)
            dialog.exec()

    def _delete_user_theme(self, theme_id: str):
        reply = QMessageBox.question(
            self, "确认删除", "确定要删除这个主题吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            from ui.theme import ThemeManager
            mgr = ThemeManager.instance()
            if mgr.delete_user_theme(theme_id):
                if mgr.user_theme_id == theme_id:
                    from ui.theme import ThemePreset
                    mgr.set_preset(ThemePreset.COZY_ORANGE)
                    self.repo.set_setting("theme_preset", "cozy_orange")
                    self.repo.set_setting("active_user_theme_id", "")
                self._refresh_theme_buttons()
                self._refresh_user_themes_list()

    def closeEvent(self, event):
        if self._preview_movie:
            self._preview_movie.stop()
            self._preview_movie.deleteLater()
            self._preview_movie = None
        super().closeEvent(event)
