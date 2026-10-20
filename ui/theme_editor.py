"""Theme editor dialog for Lobuddy."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.storage.theme_repo import ThemeRepository
from core.utils.color_utils import contrast_ratio, get_contrast_level, is_readable
from ui.theme import ThemeColors, ThemeManager


SIMPLE_FIELDS = [
    ("primary", "主色", "按钮、链接、重点标签"),
    ("background", "背景色", "页面底色"),
    ("surface", "卡片色", "卡片、容器背景"),
    ("text", "文字色", "主要文字颜色"),
    ("border", "边框色", "输入框、卡片边框"),
    ("success", "成功色", "成功提示"),
    ("warning", "警告色", "警告提示"),
    ("danger", "错误色", "错误提示"),
    ("accent", "强调色", "特殊强调元素"),
]


class ThemeEditorDialog(QDialog):
    theme_saved = Signal(str)

    def __init__(self, theme_repo: ThemeRepository, theme_id: str | None = None,
                 initial_colors: dict[str, str] | None = None, theme_name: str = "", parent=None):
        super().__init__(parent)
        self.theme_repo = theme_repo
        self.theme_id = theme_id
        self.theme_name = theme_name
        self._original_colors = dict(initial_colors) if initial_colors else {}
        self._current_colors = dict(initial_colors) if initial_colors else {}
        self._color_buttons = {}
        self._preview_labels = {}
        self._contrast_labels = {}

        self._init_ui()
        self._update_all_previews()

    def _init_ui(self):
        self.setWindowTitle("主题编辑器")
        self.setMinimumSize(700, 600)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        name_layout = QHBoxLayout()
        name_label = QLabel("主题名称:")
        name_label.setFont(QFont("Microsoft YaHei", 11))
        self.name_input = QLineEdit(self.theme_name)
        self.name_input.setPlaceholderText("输入主题名称")
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input)
        main_layout.addLayout(name_layout)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(16)

        left_panel = self._create_editor_panel()
        content_layout.addWidget(left_panel, stretch=1)

        right_panel = self._create_preview_panel()
        content_layout.addWidget(right_panel, stretch=1)

        main_layout.addLayout(content_layout, stretch=1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        reset_btn = QPushButton("重置")
        reset_btn.clicked.connect(self._on_reset)
        btn_layout.addWidget(reset_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        main_layout.addLayout(btn_layout)

    def _create_editor_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(8)

        group = QGroupBox("颜色配置")
        group_layout = QGridLayout()
        group_layout.setSpacing(8)

        for i, (key, label, tooltip) in enumerate(SIMPLE_FIELDS):
            row = i // 2
            col = (i % 2) * 3

            lbl = QLabel(label)
            lbl.setToolTip(tooltip)
            lbl.setFixedWidth(60)
            group_layout.addWidget(lbl, row, col)

            btn = QPushButton()
            btn.setFixedSize(36, 36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, k=key: self._pick_color(k))
            self._color_buttons[key] = btn
            group_layout.addWidget(btn, row, col + 1)

            contrast = QLabel()
            contrast.setFixedWidth(50)
            contrast.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._contrast_labels[key] = contrast
            group_layout.addWidget(contrast, row, col + 2)

        group.setLayout(group_layout)
        layout.addWidget(group)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _create_preview_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("header")
        header_layout = QVBoxLayout(header)
        title = QLabel("聊天预览")
        title.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        header_layout.addWidget(title)
        self._preview_labels["header"] = header
        layout.addWidget(header)

        msg_user = QLabel("用户消息示例")
        msg_user.setObjectName("msg_user")
        msg_user.setWordWrap(True)
        msg_user.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._preview_labels["msg_user"] = msg_user
        layout.addWidget(msg_user)

        msg_bot = QLabel("机器人回复示例，这是一条较长的消息用于测试换行效果。")
        msg_bot.setObjectName("msg_bot")
        msg_bot.setWordWrap(True)
        self._preview_labels["msg_bot"] = msg_bot
        layout.addWidget(msg_bot)

        input_frame = QFrame()
        input_frame.setObjectName("input")
        input_layout = QHBoxLayout(input_frame)
        input_edit = QLineEdit()
        input_edit.setPlaceholderText("输入消息...")
        input_layout.addWidget(input_edit)
        send_btn = QPushButton("发送")
        send_btn.setObjectName("send_btn")
        input_layout.addWidget(send_btn)
        self._preview_labels["input"] = input_frame
        layout.addWidget(input_frame)

        btn_row = QHBoxLayout()
        for name, text in [("success_btn", "成功"), ("warning_btn", "警告"), ("danger_btn", "错误")]:
            btn = QPushButton(text)
            btn.setObjectName(name)
            btn_row.addWidget(btn)
            self._preview_labels[name] = btn
        layout.addLayout(btn_row)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _pick_color(self, key: str):
        current = self._current_colors.get(key, "#FFFFFF")
        color = QColorDialog.getColor(QColor(current), self, f"选择 {key} 颜色")
        if color.isValid():
            hex_color = color.name()
            self._current_colors[key] = hex_color
            self._update_color_button(key)
            self._update_contrast(key)
            self._update_preview_style(key)

    def _update_color_button(self, key: str):
        btn = self._color_buttons.get(key)
        if btn:
            color = self._current_colors.get(key, "#808080")
            btn.setStyleSheet(f"background-color: {color}; border: 1px solid #ccc; border-radius: 4px;")

    def _update_contrast(self, key: str):
        label = self._contrast_labels.get(key)
        if not label:
            return

        bg = self._current_colors.get("background", "#FFFFFF")
        fg = self._current_colors.get(key, "#000000")

        if key in ("primary", "accent"):
            on_key = f"on_{key}"
            fg = self._current_colors.get(on_key, "#FFFFFF")
            bg = self._current_colors.get(key, "#000000")
        elif key in ("background", "surface", "border"):
            fg = self._current_colors.get("text", "#000000")
        else:
            fg = self._current_colors.get(key, "#000000")

        ratio = contrast_ratio(fg, bg)
        level = get_contrast_level(ratio)

        label.setText(f"{ratio:.1f}:1")
        if level == "AAA":
            label.setStyleSheet("color: #2E7D32; font-weight: bold;")
        elif level == "AA":
            label.setStyleSheet("color: #F57F17;")
        else:
            label.setStyleSheet("color: #C62828; font-weight: bold;")

    def _update_all_previews(self):
        for key, _label, _tooltip in SIMPLE_FIELDS:
            self._update_color_button(key)
            self._update_contrast(key)
            self._update_preview_style(key)

    def _update_preview_style(self, key: str):
        colors = self._current_colors

        header = self._preview_labels.get("header")
        if header:
            header.setStyleSheet(
                f"QFrame {{ background: {colors.get('primary', '#FF8A3D')}; "
                f"color: {colors.get('on_primary', '#FFFFFF')}; "
                f"padding: 12px; border-radius: 8px; }}"
            )
            for child in header.findChildren(QLabel):
                child.setStyleSheet(f"color: {colors.get('on_primary', '#FFFFFF')};")

        msg_user = self._preview_labels.get("msg_user")
        if msg_user:
            msg_user.setStyleSheet(
                f"QLabel {{ background: {colors.get('primary', '#FF8A3D')}; "
                f"color: {colors.get('on_primary', '#FFFFFF')}; "
                f"padding: 10px 14px; border-radius: 10px; "
                f"border-bottom-right-radius: 4px; }}"
            )

        msg_bot = self._preview_labels.get("msg_bot")
        if msg_bot:
            msg_bot.setStyleSheet(
                f"QLabel {{ background: {colors.get('surface', '#FFFFFF')}; "
                f"color: {colors.get('text', '#4A2E1F')}; "
                f"padding: 10px 14px; border-radius: 10px; "
                f"border-bottom-left-radius: 4px; "
                f"border: 1px solid {colors.get('border', '#F1D9C0')}; }}"
            )

        input_frame = self._preview_labels.get("input")
        if input_frame:
            input_frame.setStyleSheet(
                f"QFrame {{ background: {colors.get('background', '#FFF8EF')}; "
                f"border: 1px solid {colors.get('border', '#F1D9C0')}; "
                f"border-radius: 8px; padding: 8px; }}"
            )

        for btn_name in ("success_btn", "warning_btn", "danger_btn"):
            btn = self._preview_labels.get(btn_name)
            if btn:
                color_key = btn_name.replace("_btn", "")
                btn.setStyleSheet(
                    f"QPushButton {{ background: {colors.get(color_key, '#8BCF7A')}; "
                    f"color: white; border: none; padding: 8px 16px; "
                    f"border-radius: 6px; font-weight: bold; }}"
                )

    def _on_reset(self):
        self._current_colors = dict(self._original_colors)
        self._update_all_previews()

    def _on_save(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入主题名称")
            return

        try:
            if self.theme_id:
                self.theme_repo.save(self.theme_id, name, self._current_colors)
            else:
                import uuid
                theme_id = f"user_{uuid.uuid4().hex[:8]}"
                self.theme_repo.save(theme_id, name, self._current_colors)
                self.theme_id = theme_id

            self.theme_saved.emit(self.theme_id)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")
