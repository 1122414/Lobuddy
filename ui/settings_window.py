"""Settings window for Lobuddy - 设置小窝."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
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
        layout.setSpacing(12)

        layout.addWidget(QLabel("选择预设主题:"))

        self._theme_combo = QComboBox()
        theme_names = {
            ThemePreset.COZY_ORANGE: "温暖橙 (Cozy Orange)",
            ThemePreset.SAKURA_PINK: "樱花粉 (Sakura Pink)",
            ThemePreset.MINT_GREEN: "薄荷绿 (Mint Green)",
            ThemePreset.NIGHT_COMPANION: "夜间伙伴 (Night Companion)",
        }
        for preset, name in theme_names.items():
            self._theme_combo.addItem(name, preset.value)
        current_preset = self.settings.theme_preset
        for i in range(self._theme_combo.count()):
            if self._theme_combo.itemData(i) == current_preset:
                self._theme_combo.setCurrentIndex(i)
                break
        layout.addWidget(self._theme_combo)

        layout.addWidget(QLabel("自定义颜色 (可选):"))
        color_form = QFormLayout()

        self._custom_primary = QLineEdit(self.settings.theme_primary_color)
        self._custom_primary.setPlaceholderText("#FF8A3D")
        color_form.addRow("主色调:", self._custom_primary)

        self._custom_bg = QLineEdit(self.settings.theme_background_color)
        self._custom_bg.setPlaceholderText("#FFF8EF")
        color_form.addRow("背景色:", self._custom_bg)

        self._custom_accent = QLineEdit(self.settings.theme_accent_color)
        self._custom_accent.setPlaceholderText("#FF8A3D")
        color_form.addRow("强调色:", self._custom_accent)

        layout.addLayout(color_form)

        reset_theme_btn = QPushButton("恢复默认主题")
        reset_theme_btn.clicked.connect(self._on_reset_theme)
        layout.addWidget(reset_theme_btn)

        layout.addStretch()
        return w

    def _build_companion_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        layout.setSpacing(12)

        self._greeting_check = QCheckBox("主动问候")
        self._greeting_check.setChecked(self.settings.companion_greeting_enabled)
        layout.addRow("互动:", self._greeting_check)

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

        self.base_url_input = QLineEdit(self.settings.llm_base_url)
        adv_layout.addRow("LLM Base URL:", self.base_url_input)

        self.model_input = QLineEdit(self.settings.llm_model)
        adv_layout.addRow("LLM Model:", self.model_input)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(30, 600)
        self.timeout_spin.setValue(self.settings.task_timeout)
        adv_layout.addRow("任务超时 (秒):", self.timeout_spin)

        self.shell_check = QCheckBox("启用 Shell 工具 (危险)")
        self.shell_check.setChecked(self.settings.shell_enabled)
        adv_layout.addRow("工具:", self.shell_check)

        layout.addRow(self._advanced_container)
        return w

    def _refresh_ui(self):
        self.pet_name_input.setText(self.settings.pet_name)
        self.api_key_input.setText(self.settings.llm_api_key)
        self.base_url_input.setText(self.settings.llm_base_url)
        self.model_input.setText(self.settings.llm_model)
        self.timeout_spin.setValue(self.settings.task_timeout)
        self.shell_check.setChecked(self.settings.shell_enabled)
        self._greeting_check.setChecked(self.settings.companion_greeting_enabled)
        self._anim_check.setChecked(self.settings.pet_avatar_animation_enabled)
        self._top_check.setChecked(getattr(self._pet_appearance, "always_on_top", True))
        self._update_pet_preview()

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

    def _on_reset_theme(self):
        self._theme_combo.setCurrentIndex(0)
        self._custom_primary.clear()
        self._custom_bg.clear()
        self._custom_accent.clear()

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
            self.repo.set_setting("llm_api_key", api_key_to_save)
            self.repo.set_setting("llm_base_url", self.base_url_input.text().strip())
            self.repo.set_setting("llm_model", self.model_input.text().strip())
            self.repo.set_setting("task_timeout", str(self.timeout_spin.value()))
            self.repo.set_setting("shell_enabled", str(self.shell_check.isChecked()))
            self.repo.set_setting("companion_greeting_enabled",
                                   str(self._greeting_check.isChecked()))
            self.repo.set_setting("pet_avatar_animation_enabled",
                                   str(self._anim_check.isChecked()))

            theme_data = self._theme_combo.currentData()
            self.repo.set_setting("theme_preset", theme_data or "cozy_orange")
            self.repo.set_setting("theme_primary_color",
                                   self._custom_primary.text().strip())
            self.repo.set_setting("theme_background_color",
                                   self._custom_bg.text().strip())
            self.repo.set_setting("theme_accent_color",
                                   self._custom_accent.text().strip())

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

    def closeEvent(self, event):
        if self._preview_movie:
            self._preview_movie.stop()
            self._preview_movie.deleteLater()
            self._preview_movie = None
        super().closeEvent(event)
