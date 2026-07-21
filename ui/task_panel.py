"""Chat panel with conversation management and image support."""

import uuid
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QPoint
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QFont, QMovie, QPixmap
import markdown
from ui.styles import (
    TASKPANEL_TRANSPARENT,
    TASKPANEL_CONTAINER,
    TASKPANEL_HEADER,
    TASKPANEL_TITLE,
    TASKPANEL_SCROLL,
    TASKPANEL_CHAT_BG,
    TASKPANEL_INPUT_CONTAINER,
    TASKPANEL_IMAGE_PREVIEW,
    TASKPANEL_IMAGE_BTN,
    TASKPANEL_INPUT,
    TASKPANEL_SEND_BTN,
    TASKPANEL_USER_MSG,
    TASKPANEL_BOT_MSG,
    TASKPANEL_HTML_WRAPPER,
)
from ui.theme import (
    ThemeManager,
    generate_chat_bubble_style,
    generate_input_style,
    generate_tooltip_style,
)
from ui.widgets.conversation_timeline import ConversationTimelineWidget
from core.skills.skill_registry import SkillRegistry
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import MemoryType, MemoryStatus
from core.screen_region.models import ScreenRegionCapture


class HTMLSanitizer(HTMLParser):
    ALLOWED_TAGS = {
        "p",
        "br",
        "strong",
        "b",
        "em",
        "i",
        "code",
        "pre",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "a",
        "blockquote",
        "span",
        "div",
    }
    ALLOWED_ATTRS = {"href": ["a"], "title": ["a"]}

    def __init__(self):
        super().__init__()
        self.result = []
        self.skip = False

    def _escape_attr(self, value):
        return (
            value.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def handle_starttag(self, tag, attrs):
        if tag in self.ALLOWED_TAGS:
            if tag in self.ALLOWED_ATTRS.get("href", []):
                attrs_dict = dict(attrs)
                href = (attrs_dict.get("href", "") or "").strip()
                allowed_schemes = {"http:", "https:", "mailto:"}
                if not any(href.lower().startswith(s) for s in allowed_schemes):
                    return
                safe_href = self._escape_attr(href)
                self.result.append(f'<{tag} href="{safe_href}">')
            else:
                self.result.append(f"<{tag}>")
        else:
            self.skip = True

    def handle_endtag(self, tag):
        if tag in self.ALLOWED_TAGS and not self.skip:
            self.result.append(f"</{tag}>")
        self.skip = False

    def handle_data(self, data):
        if not self.skip:
            import html

            self.result.append(html.escape(data))

    def get_clean_html(self):
        return "".join(self.result)


def sanitize_html(html_str: str) -> str:
    sanitizer = HTMLSanitizer()
    sanitizer.feed(html_str)
    return sanitizer.get_clean_html()


class TaskPanel(QDialog):
    """Chat dialog with compact layout, history hidden by default."""

    task_submitted = Signal(str, str, str)
    history_requested = Signal()
    settings_requested = Signal()
    skill_lab_requested = Signal()
    data_control_requested = Signal()
    screen_region_requested = Signal()
    memory_context_requested = Signal(str)
    attachment_cleared = Signal(str)

    STYLE_INPUT = TASKPANEL_INPUT
    STYLE_SEND_BTN = TASKPANEL_SEND_BTN
    STYLE_USER_MSG = TASKPANEL_USER_MSG
    STYLE_BOT_MSG = TASKPANEL_BOT_MSG
    STYLE_HTML_WRAPPER = TASKPANEL_HTML_WRAPPER

    @staticmethod
    def _load_image_to_label(label: QLabel, image_path: str, size: QSize) -> None:
        label.clear()
        movie = getattr(label, "_movie", None)
        if movie is not None:
            movie.stop()
            movie.deleteLater()
            label._movie = None

        suffix = Path(image_path).suffix.lower()
        if suffix == ".gif":
            m = QMovie(image_path)
            if m.isValid():
                m.setScaledSize(size)
                m.setParent(label)
                label.setMovie(m)
                m.start()
                label._movie = m
                return
            m.deleteLater()

        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(
                size.width(),
                size.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            label.setPixmap(pixmap)
        else:
            label.setText("📷 Image")

    def __init__(self, chat_repo, parent=None):
        super().__init__(parent)
        self.chat_repo = chat_repo
        self.current_session_id = "default"
        self.messages = []
        self._msg_data = []
        self.drag_pos = None
        self.current_image_path = None
        self._current_image_is_screen_region = False
        self._settings = None
        self._focus_active = False
        self._skill_registry = SkillRegistry()
        self._skill_panel = None
        self._memory_repo = MemoryRepository()
        self._mem_info_label: QLabel | None = None
        self._agent_status_tone = "idle"
        self._init_ui()
        self._load_header_avatar()
        self.refresh_theme()

    def _init_ui(self):
        self.setMinimumSize(460, 580)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(TASKPANEL_TRANSPARENT)
        self.setAutoFillBackground(False)

        container = QWidget(self)
        self._container = container
        container.setObjectName("container")
        container.setStyleSheet(TASKPANEL_CONTAINER)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(container)

        main_layout = QVBoxLayout(container)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        header = QWidget()
        self._header = header
        header.setFixedHeight(108)
        header.setStyleSheet(TASKPANEL_HEADER)

        header_vlayout = QVBoxLayout(header)
        header_vlayout.setContentsMargins(16, 12, 16, 10)
        header_vlayout.setSpacing(8)

        id_row = QHBoxLayout()
        id_row.setSpacing(8)

        self._header_avatar = QLabel()
        self._header_avatar.setFixedSize(38, 38)
        self._header_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        id_row.addWidget(self._header_avatar)

        identity = QVBoxLayout()
        identity.setSpacing(1)
        self.title_label = QLabel("Lobuddy")
        self.title_label.setFont(QFont("Microsoft YaHei UI", 13, QFont.Weight.Bold))
        self.title_label.setStyleSheet(TASKPANEL_TITLE)
        identity.addWidget(self.title_label)

        self._header_mood = QLabel("在你身边，也能替你把事情做完")
        identity.addWidget(self._header_mood)
        id_row.addLayout(identity, stretch=1)

        history_btn = QPushButton("记录")
        history_btn.setToolTip("查看聊天记录")
        history_btn.clicked.connect(self.history_requested.emit)
        id_row.addWidget(history_btn)

        settings_btn = QPushButton("设置")
        settings_btn.setToolTip("打开设置")
        settings_btn.clicked.connect(self.settings_requested.emit)
        id_row.addWidget(settings_btn)

        close_btn = QPushButton("收起")
        close_btn.setToolTip("收起对话面板")
        close_btn.clicked.connect(self.hide)
        id_row.addWidget(close_btn)
        self._header_buttons = (history_btn, settings_btn, close_btn)
        header_vlayout.addLayout(id_row)

        qa_row = QHBoxLayout()
        qa_row.setSpacing(8)
        self._agent_status = QLabel("●  随时可以开始")
        self._agent_status.setObjectName("agentStatus")
        qa_row.addWidget(self._agent_status)

        self._agent_status_detail = QLabel("倾听中")
        self._agent_status_detail.setObjectName("agentStatusDetail")
        qa_row.addWidget(self._agent_status_detail)

        self._memory_context_badge = QPushButton("记忆 · 0")
        self._memory_context_badge.setObjectName("memoryContextBadge")
        self._memory_context_badge.setToolTip("本次任务尚未准备记忆上下文")
        self._memory_context_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self._memory_context_badge.clicked.connect(self._request_memory_context_review)
        self._memory_context_badge.setEnabled(False)
        self._memory_context_badge.hide()
        self._memory_context_tone = "empty"
        self._memory_context_task_id = ""
        qa_row.addWidget(self._memory_context_badge)
        qa_row.addStretch(1)

        self._new_chat_btn = QPushButton("新对话")
        self._new_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_chat_btn.clicked.connect(self._on_new_chat)
        qa_row.addWidget(self._new_chat_btn)
        header_vlayout.addLayout(qa_row)

        main_layout.addWidget(header)

        scroll = QScrollArea()
        self._chat_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(TASKPANEL_SCROLL)

        self.chat_widget = QWidget()
        self.chat_widget.setStyleSheet(TASKPANEL_CHAT_BG)
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_layout.setSpacing(12)
        self.chat_layout.setContentsMargins(16, 16, 16, 16)
        self.chat_layout.addStretch()

        scroll.setWidget(self.chat_widget)

        self._timeline = ConversationTimelineWidget(self)
        self._timeline.dot_clicked.connect(self._on_timeline_dot_clicked)

        chat_timeline_layout = QHBoxLayout()
        chat_timeline_layout.setContentsMargins(0, 0, 0, 0)
        chat_timeline_layout.setSpacing(0)
        chat_timeline_layout.addWidget(scroll, stretch=1)
        chat_timeline_layout.addWidget(self._timeline)
        main_layout.addLayout(chat_timeline_layout, 1)

        cards_widget = QWidget()
        self._capability_bar = cards_widget
        cards_widget.setFixedHeight(54)
        cards_layout = QHBoxLayout(cards_widget)
        cards_layout.setContentsMargins(16, 6, 16, 6)
        cards_layout.setSpacing(8)

        mem_btn = QPushButton("我的记忆")
        mem_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mem_btn.clicked.connect(self._on_show_memory)
        cards_layout.addWidget(mem_btn)

        skill_btn = QPushButton("我会的技能")
        skill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        skill_btn.clicked.connect(self._on_show_skills)
        cards_layout.addWidget(skill_btn)

        self._evolution_btn = QPushButton("能力进化")
        self._evolution_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._evolution_btn.setToolTip("查看 Lobuddy 从成功任务中提出的待审能力")
        self._evolution_btn.clicked.connect(self.skill_lab_requested.emit)
        cards_layout.addWidget(self._evolution_btn)

        data_btn = QPushButton("数据与权限")
        data_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        data_btn.setToolTip("查看当前对话的数据使用状态并随时撤销")
        data_btn.clicked.connect(self.data_control_requested.emit)
        cards_layout.addWidget(data_btn)
        self._capability_buttons = (
            mem_btn,
            skill_btn,
            self._evolution_btn,
            data_btn,
        )

        self._mem_info_label = QLabel("暂无记忆数据")
        self._mem_info_label.setWordWrap(True)
        cards_layout.addWidget(self._mem_info_label, stretch=1)
        main_layout.addWidget(cards_widget)

        input_container = QWidget()
        self._input_container = input_container
        input_container.setStyleSheet(TASKPANEL_INPUT_CONTAINER)
        input_container_layout = QVBoxLayout(input_container)
        input_container_layout.setContentsMargins(16, 8, 16, 8)
        input_container_layout.setSpacing(4)

        self.image_preview = QWidget()
        self.image_preview.setFixedHeight(60)
        self.image_preview.setStyleSheet(TASKPANEL_IMAGE_PREVIEW)
        self.image_preview.hide()
        preview_layout = QHBoxLayout(self.image_preview)
        preview_layout.setContentsMargins(8, 4, 8, 4)
        preview_layout.setSpacing(8)
        self.image_preview_label = QLabel()
        self.image_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.image_preview_label)

        preview_copy = QVBoxLayout()
        preview_copy.setSpacing(1)
        self.image_preview_title = QLabel()
        self.image_preview_title.setObjectName("imagePreviewTitle")
        preview_copy.addWidget(self.image_preview_title)
        self.image_preview_text = QLabel()
        self.image_preview_text.setObjectName("imagePreviewMeta")
        self.image_preview_text.setWordWrap(True)
        preview_copy.addWidget(self.image_preview_text)
        preview_layout.addLayout(preview_copy, stretch=1)

        self._clear_image_btn = QPushButton("移除")
        self._clear_image_btn.setObjectName("clearImageButton")
        self._clear_image_btn.setToolTip("移除这次图片或屏幕选区")
        self._clear_image_btn.clicked.connect(lambda: self._clear_image_preview())
        preview_layout.addWidget(self._clear_image_btn)
        input_container_layout.addWidget(self.image_preview)

        input_area = QWidget()
        input_area.setFixedHeight(50)
        input_layout = QHBoxLayout(input_area)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)

        image_btn = QPushButton("＋")
        self._image_btn = image_btn
        image_btn.setFixedSize(36, 36)
        image_btn.setStyleSheet(TASKPANEL_IMAGE_BTN)
        image_btn.setToolTip("添加图片，让 Lobuddy 看一看")
        image_btn.clicked.connect(self._on_select_image)
        input_layout.addWidget(image_btn)

        self._screen_region_btn = QPushButton("选区")
        self._screen_region_btn.setObjectName("screenRegionButton")
        self._screen_region_btn.setFixedSize(48, 36)
        self._screen_region_btn.setToolTip("只框选需要 Lobuddy 看见的屏幕区域")
        self._screen_region_btn.clicked.connect(self.screen_region_requested.emit)
        input_layout.addWidget(self._screen_region_btn)

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("说说你的感受，或交给我一个任务…")
        self.input_box.setFont(QFont("Microsoft YaHei", 11))
        self.input_box.setStyleSheet(self.STYLE_INPUT)
        self.input_box.returnPressed.connect(self._on_send)
        input_layout.addWidget(self.input_box)

        send_btn = QPushButton("发送")
        self._send_btn = send_btn
        send_btn.setFixedSize(70, 36)
        send_btn.setStyleSheet(self.STYLE_SEND_BTN)
        send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(send_btn)

        input_container_layout.addWidget(input_area)
        main_layout.addWidget(input_container)

        grip_layout = QHBoxLayout()
        grip_layout.setContentsMargins(0, 0, 0, 0)
        grip_layout.addStretch()
        self.size_grip = QSizeGrip(container)
        self.size_grip.setFixedSize(16, 16)
        grip_layout.addWidget(self.size_grip)
        main_layout.addLayout(grip_layout)

    def _on_select_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.gif *.webp *.svg)",
        )
        if file_path:
            from core.agent.image_validation import inspect_image_file

            try:
                inspect_image_file(file_path)
            except ValueError as exc:
                QMessageBox.warning(self, "无法使用这张图片", str(exc))
                return
            self._clear_image_preview()
            self.current_image_path = file_path
            self._update_image_preview(file_path)

    def attach_screen_region(self, capture: ScreenRegionCapture) -> None:
        """Show one managed crop without exposing its temporary file name."""
        self._clear_image_preview()
        self.current_image_path = str(capture.path)
        self._current_image_is_screen_region = True
        self._update_image_preview(
            str(capture.path),
            title="临时屏幕选区",
            meta=f"{capture.display_size} · 任务结束后自动删除",
        )
        self.input_box.setPlaceholderText("问这个区域，或告诉我接下来要怎么做…")
        self.input_box.setFocus()

    def _update_image_preview(
        self,
        image_path: str,
        *,
        title: str = "",
        meta: str = "",
    ) -> None:
        self.image_preview_label.clear()
        self.image_preview_title.clear()
        self.image_preview_text.clear()
        self._load_image_to_label(self.image_preview_label, image_path, QSize(50, 50))
        settings = getattr(self, "_settings", None)
        vision_ready = bool(settings and getattr(settings, "llm_multimodal_model", "").strip())
        status = "视觉模型已就绪" if vision_ready else "需先配置视觉模型"
        self.image_preview_title.setText(title or Path(image_path).name)
        self.image_preview_text.setText(meta or status)
        self.image_preview.show()

    def _stop_image_preview_movie(self):
        if getattr(self.image_preview_label, "_movie", None) is not None:
            self.image_preview_label._movie.stop()
            self.image_preview_label._movie.deleteLater()
            self.image_preview_label._movie = None

    def _clear_image_preview(self, *, notify: bool = True):
        previous_path = self.current_image_path
        self.current_image_path = None
        self._current_image_is_screen_region = False
        self._stop_image_preview_movie()
        self.image_preview_label.clear()
        self.image_preview_title.clear()
        self.image_preview_text.clear()
        self.image_preview.hide()
        self.input_box.setPlaceholderText("说说你的感受，或交给我一个任务…")
        if notify and previous_path:
            self.attachment_cleared.emit(previous_path)

    def _on_new_chat(self):
        session_id = f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.current_session_id = session_id
        from core.models.chat import ChatSession

        session = ChatSession(id=session_id, title="新对话")
        self.chat_repo.save_session(session)
        self._clear_chat_display()
        self._clear_image_preview()
        self._timeline.clear()
        self.title_label.setText("Lobuddy")
        self.clear_memory_context()
        self.set_agent_status("随时可以开始", "倾听中", tone="idle")

    def _on_show_skills(self):
        if not self._settings or not self._settings.skill_panel_enabled:
            return
        if self._skill_panel is None:
            from ui.skill_panel import SkillPanel

            self._skill_panel = SkillPanel(self._skill_registry, self._settings, parent=self)
            self._skill_panel.example_selected.connect(self._on_skill_example_selected)
        self._skill_panel.show()
        self._skill_panel.raise_()
        self._skill_panel.activateWindow()

    def update_skill_candidate_count(self, pending_count: int) -> None:
        count = max(0, int(pending_count))
        self._evolution_btn.setText(f"能力进化 · {count}" if count else "能力进化")
        self._evolution_btn.setToolTip(f"有 {count} 个能力提案等待审核" if count else "暂无待审提案；成功的安全流程会出现在这里")

    def _on_skill_example_selected(self, example: str):
        self.input_box.setText(example)
        self.input_box.setFocus()

    def _on_show_memory(self):
        """Fetch memories from MemoryRepository and show in themed dialog."""
        user_memories = self._memory_repo.list_by_type(
            memory_type=MemoryType.USER_PROFILE,
            status=MemoryStatus.ACTIVE,
            limit=20,
        )
        system_memories: list = []
        for mem_type, limit in [
            (MemoryType.SYSTEM_PROFILE, 10),
            (MemoryType.EPISODIC_MEMORY, 10),
            (MemoryType.PROCEDURAL_MEMORY, 10),
            (MemoryType.PROJECT_MEMORY, 10),
        ]:
            items = self._memory_repo.list_by_type(
                memory_type=mem_type,
                status=MemoryStatus.ACTIVE,
                limit=limit,
            )
            system_memories.extend(items)

        user_count = len(user_memories)
        system_count = len(system_memories)
        total = user_count + system_count

        if self._mem_info_label:
            if total > 0:
                self._mem_info_label.setText(f"已有 {total} 条记忆，包括 {user_count} 条对你的了解")
            else:
                self._mem_info_label.setText("暂无记忆数据")

        if total == 0:
            msg = QMessageBox(self)
            msg.setWindowTitle("系统记忆")
            msg.setText("暂无记忆数据，多和我聊天吧～")
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            t = ThemeManager.instance().current
            msg.setStyleSheet(
                f"QMessageBox {{ background: {t.background}; color: {t.text}; }}"
                f"QPushButton {{ background: {t.primary}; color: {t.primary_text}; "
                f"border: none; border-radius: {t.radius_sm}px; padding: 6px 20px; }}"
            )
            msg.exec()
            return

        self._show_memory_dialog(user_memories, system_memories)

    def _show_memory_dialog(self, user_memories: list, system_memories: list):
        """Show a themed dialog with memory cards for user profile and system memories."""
        t = ThemeManager.instance().current

        dialog = QDialog(self)
        dialog.setWindowTitle("系统记忆")
        dialog.setMinimumSize(420, 520)
        dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        dialog.setStyleSheet(f"QDialog {{ background: {t.background}; }}")

        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {t.background}; }}"
            f"QScrollBar:vertical {{ width: 8px; background: transparent; }}"
            f"QScrollBar::handle:vertical {{ background: {t.border}; "
            f"border-radius: 4px; min-height: 30px; }}"
        )

        content_widget = QWidget()
        content_widget.setStyleSheet(f"background: {t.background};")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        # --- Section: 对你的了解 (User Profile) ---
        if user_memories:
            section_header = QLabel("🧑 对你的了解")
            section_header.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
            section_header.setStyleSheet(f"color: {t.text}; padding: 4px 0;")
            content_layout.addWidget(section_header)

            for mem in user_memories:
                card = self._build_memory_card(mem, t, "🧑")
                content_layout.addWidget(card)

        # --- Section: 长期记忆 (System) ---
        if system_memories:
            section_header = QLabel("🧠 长期记忆")
            section_header.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
            section_header.setStyleSheet(f"color: {t.text}; padding: 4px 0;")
            content_layout.addWidget(section_header)

            for mem in system_memories:
                card = self._build_memory_card(mem, t, "🧠")
                content_layout.addWidget(card)

        content_layout.addStretch()
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

        close_btn = QPushButton("关闭")
        close_btn.setFixedHeight(36)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {t.surface_soft}; color: {t.text}; "
            f"border: 1px solid {t.border}; border-radius: {t.radius_sm}px; "
            f"font-size: 13px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {t.border}; }}"
        )
        close_btn.clicked.connect(dialog.accept)
        main_layout.addWidget(close_btn)

        dialog.exec()

    def _build_memory_card(self, mem, t, icon: str) -> QFrame:
        """Build a single memory card QFrame."""
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {t.surface}; border: 1px solid {t.border}; "
            f"border-radius: {t.radius_md}px; padding: 10px; margin: 2px 0; }}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Title row with icon
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        icon_label = QLabel(icon)
        icon_label.setFont(QFont("Segoe UI Emoji", 14))
        title_row.addWidget(icon_label)

        title_text = QLabel(mem.title or "(无标题)")
        title_text.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        title_text.setStyleSheet(f"color: {t.text}; background: transparent; border: none;")
        title_text.setWordWrap(True)
        title_row.addWidget(title_text, stretch=1)

        # Memory type badge (Chinese labels)
        _MEM_TYPE_LABELS = {
            "user_profile": "对你的了解",
            "system_profile": "系统信息",
            "episodic_memory": "事件记忆",
            "procedural_memory": "操作习惯",
            "project_memory": "项目记忆",
        }
        raw_type = (
            mem.memory_type.value if hasattr(mem.memory_type, "value") else str(mem.memory_type)
        )
        badge_text = _MEM_TYPE_LABELS.get(raw_type, raw_type)
        badge = QLabel(badge_text)
        badge.setStyleSheet(
            f"QLabel {{ background: {t.primary_soft}; color: {t.primary}; "
            f"padding: 2px 8px; border-radius: {t.radius_sm - 4}px; font-size: 10px; "
            f"border: none; }}"
        )
        badge.setFixedHeight(20)
        title_row.addWidget(badge)
        layout.addLayout(title_row)

        # Content
        content_label = QLabel(mem.content)
        content_label.setWordWrap(True)
        content_label.setFont(QFont("Microsoft YaHei", 11))
        content_label.setStyleSheet(
            f"color: {t.text_secondary}; background: transparent; border: none;"
        )
        layout.addWidget(content_label)

        return card

    def _load_session_messages(self, session_id: str):
        self._clear_chat_display()
        self._clear_image_preview()
        self.clear_memory_context()
        self._timeline.clear()
        session = self.chat_repo.get_session(session_id)
        if session:
            self.title_label.setText(session.title or "Chat")
            for msg in session.messages:
                is_user = msg.role == "user"
                self._add_message_to_display(
                    msg.content,
                    is_user=is_user,
                    is_markdown=not is_user,
                    image_path=msg.image_path,
                    created_at=msg.created_at,
                    msg_id=msg.id,
                )
            # Scroll to bottom after all messages are loaded (layout needs time to settle)
            QTimer.singleShot(200, self._scroll_bottom)

    def _clear_chat_display(self):
        for msg_widget in self.messages:
            for label in msg_widget.findChildren(QLabel):
                movie = getattr(label, "_movie", None)
                if movie is not None:
                    movie.stop()
                    movie.deleteLater()
                    label._movie = None
            msg_widget.deleteLater()
        self.messages.clear()
        self._msg_data.clear()

    def set_settings(self, settings):
        self._settings = settings
        tl_enabled = getattr(settings, "conversation_timeline_enabled", True)
        self._timeline.set_enabled(tl_enabled)
        gap = getattr(settings, "conversation_timeline_min_dot_gap_px", 8)
        preview = getattr(settings, "conversation_timeline_preview_max_chars", 32)
        tooltip = getattr(settings, "conversation_timeline_tooltip_enabled", True)
        self._timeline.set_config(gap, preview, tooltip)
        ws_skills_dir = settings.workspace_path / "skills"
        self._skill_registry.discover_workspace_skills(ws_skills_dir)

    def _add_message_to_display(
        self,
        text: str,
        is_user: bool = True,
        is_markdown: bool = False,
        image_path: str = None,
        created_at: datetime = None,
        msg_id: str = None,
    ):
        bubble = QWidget()
        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if image_path:
            img_label = QLabel()
            img_label.setFixedSize(200, 150)
            img_label.setStyleSheet(TASKPANEL_IMAGE_PREVIEW)
            img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._load_image_to_label(img_label, image_path, QSize(200, 150))

            if is_user:
                img_layout = QHBoxLayout()
                img_layout.addStretch()
                img_layout.addWidget(img_label)
                layout.addLayout(img_layout)
            else:
                layout.addWidget(img_label)

        msg_layout = QHBoxLayout()
        msg_layout.setContentsMargins(0, 0, 0, 0)
        msg_label = QLabel()
        msg_label.setWordWrap(True)
        msg_label.setFont(QFont("Microsoft YaHei", 11))
        msg_label.setMaximumWidth(480)
        msg_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        if is_user:
            msg_label.setText(text)
            msg_label.setStyleSheet(self.STYLE_USER_MSG)
            msg_layout.addStretch()
            msg_layout.addWidget(msg_label)
        else:
            if is_markdown:
                md = markdown.Markdown(extensions=["nl2br"])
                html = md.convert(text)
                clean_html = sanitize_html(html)
                styled_html = f'<div style="{self.STYLE_HTML_WRAPPER}">{clean_html}</div>'
                msg_label.setTextFormat(Qt.TextFormat.RichText)
                msg_label.setText(styled_html)
            else:
                msg_label.setText(text)
            msg_label.setStyleSheet(self.STYLE_BOT_MSG)
            msg_layout.addWidget(msg_label)
            msg_layout.addStretch()

        layout.addLayout(msg_layout)

        if (
            created_at
            and self._settings
            and getattr(self._settings, "chat_message_time_enabled", True)
        ):
            from core.time_format import format_message_time

            time_fmt = getattr(self._settings, "chat_time_format", "HH:mm")
            time_text = format_message_time(created_at, time_fmt)
            time_label = QLabel(time_text)
            time_label.setStyleSheet("color: #A0846C; font-size: 10px; padding: 1px 4px;")
            time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addWidget(time_label)

        if msg_id:
            bubble.setProperty("msg_id", msg_id)
            self._msg_data.append(
                {"widget": bubble, "msg_id": msg_id, "created_at": created_at, "content": text}
            )
            if (
                is_user
                and self._settings
                and getattr(self._settings, "conversation_timeline_enabled", True)
            ):
                self._timeline.add_dot(msg_id, text, created_at, bubble)

        self._insert_time_divider(created_at)

        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        self.messages.append(bubble)
        QTimer.singleShot(50, self._scroll_bottom)

    def _insert_time_divider(self, created_at: datetime = None):
        if not created_at or not self._settings:
            return
        if not getattr(self._settings, "chat_time_divider_enabled", True):
            return
        gap = getattr(self._settings, "chat_time_divider_gap_minutes", 5)
        last = None
        for d in reversed(self._msg_data[:-1]):
            if d.get("created_at"):
                last = d["created_at"]
                break
        if last:
            diff = abs((created_at - last).total_seconds() / 60.0)
            if diff < gap:
                return
        from core.time_format import format_time_divider_label

        divider = QLabel(format_time_divider_label(created_at))
        divider.setAlignment(Qt.AlignmentFlag.AlignCenter)
        divider.setStyleSheet("color: #A0846C; font-size: 10px; padding: 4px 12px; margin: 4px 0;")
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, divider)
        self.messages.append(divider)

    def _scroll_bottom(self):
        bar = self._chat_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_timeline_dot_clicked(self, msg_id: str):
        for item in self._msg_data:
            if item.get("msg_id") == msg_id and item.get("widget"):
                bubble = item["widget"]
                target_y = bubble.mapTo(self.chat_widget, QPoint(0, 0)).y()
                bar = self._chat_scroll.verticalScrollBar()
                bar.setValue(max(0, target_y - 24))
                break

    def _on_send(self):
        text = self.input_box.text().strip()
        if text or self.current_image_path:
            self.clear_memory_context()
            if not text and self.current_image_path:
                text = (
                    "请分析我刚刚框选的屏幕区域，说明可见信息，并给出下一步建议。"
                    if self._current_image_is_screen_region
                    else "请帮我看看这张图片，并告诉我最重要的信息。"
                )
            self.set_agent_status("正在理解你的需要", "准备开始处理", tone="listening")
            session = self.chat_repo.get_session(self.current_session_id)
            is_first_message = session is None or len(session.messages) == 0

            import uuid

            now = datetime.now()
            display_image_path = (
                None if self._current_image_is_screen_region else self.current_image_path
            )
            self._add_message_to_display(
                text,
                is_user=True,
                image_path=display_image_path,
                created_at=now,
                msg_id=str(uuid.uuid4()),
            )
            self.task_submitted.emit(text, self.current_session_id, self.current_image_path or "")

            self.input_box.clear()
            self._clear_image_preview(notify=False)

            if is_first_message and text:
                title = text[:30] + "..." if len(text) > 30 else text
                self.chat_repo.update_session_title(self.current_session_id, title)
                self.title_label.setText(title)

    def add_pet_response(
        self, text: str, session_id: str = None, created_at: datetime = None, msg_id: str = None
    ):
        if session_id is None or session_id == self.current_session_id:
            self._add_message_to_display(
                text, is_user=False, is_markdown=True, created_at=created_at, msg_id=msg_id
            )

    def set_position_near(self, x: int, y: int):
        self.move(x + 140, y)

    def _pause_all_message_movies(self):
        for msg_widget in self.messages:
            for label in msg_widget.findChildren(QLabel):
                movie = getattr(label, "_movie", None)
                if movie is not None:
                    movie.stop()

    def _resume_all_message_movies(self):
        for msg_widget in self.messages:
            for label in msg_widget.findChildren(QLabel):
                movie = getattr(label, "_movie", None)
                if movie is not None:
                    movie.start()

    def hideEvent(self, event):
        self._stop_image_preview_movie()
        self._pause_all_message_movies()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._stop_image_preview_movie()
        for msg_widget in self.messages:
            for label in msg_widget.findChildren(QLabel):
                movie = getattr(label, "_movie", None)
                if movie is not None:
                    movie.stop()
                    movie.deleteLater()
                    label._movie = None
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.input_box.setFocus()
        self._resume_all_message_movies()
        QTimer.singleShot(100, self._scroll_bottom)

    def _load_header_avatar(self):
        from core.models.appearance import get_appearance

        app = get_appearance()
        path = getattr(app, "custom_asset_path", None)
        avatar_path = (
            Path(path)
            if path and Path(path).exists()
            else (Path(__file__).parent / "assets" / "lobuddy_mascot.png")
        )
        if avatar_path.exists():
            pixmap = QPixmap(str(avatar_path))
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    34,
                    34,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._header_avatar.setPixmap(pixmap)
                return
        self._header_avatar.setText("LO")

    def set_agent_status(
        self,
        text: str,
        detail: str = "",
        *,
        tone: str = "idle",
    ) -> None:
        """Expose the companion's current state without adding a chat message."""
        self._agent_status_tone = tone
        self._agent_status.setText(f"●  {text}")
        self._agent_status_detail.setText(detail)
        self._agent_status_detail.setVisible(bool(detail))
        self.refresh_theme()

    def clear_memory_context(self) -> None:
        """Clear evidence from the previous task or session."""
        self._memory_context_tone = "empty"
        self._memory_context_task_id = ""
        self._memory_context_badge.setText("记忆 · 0")
        self._memory_context_badge.setToolTip("本次任务尚未准备记忆上下文")
        self._memory_context_badge.setEnabled(False)
        self._memory_context_badge.hide()

    def update_memory_context(self, event) -> None:
        """Show content-minimized evidence for the current task's memory use."""
        if getattr(event, "session_id", "") != self.current_session_id:
            return

        count = max(0, int(getattr(event, "selected_count", 0)))
        reviewable_value = getattr(event, "reviewable_count", None)
        reviewable_count = count if reviewable_value is None else max(0, int(reviewable_value))
        self._memory_context_task_id = ""
        if bool(getattr(event, "privacy_active", False)):
            self._memory_context_tone = "privacy"
            self._memory_context_badge.setText("隐私 · 0")
            tooltip = "隐私模式已开启，本次任务未调用长期记忆"
        elif not bool(getattr(event, "injection_enabled", True)):
            self._memory_context_tone = "disabled"
            self._memory_context_badge.setText("记忆关闭")
            tooltip = "记忆注入已关闭，本次任务未调用长期记忆"
        elif count:
            self._memory_context_tone = "selected"
            if reviewable_count:
                self._memory_context_task_id = str(getattr(event, "task_id", ""))
            self._memory_context_badge.setText(f"记忆 · {count}")
            labels = {
                "user_profile": "用户偏好",
                "system_profile": "助手设定",
                "project_memory": "项目上下文",
                "conversation_summary": "会话摘要",
                "episodic_memory": "情景记忆",
                "procedural_memory": "流程记忆",
            }
            type_counts = getattr(event, "type_counts", {}) or {}
            summary = [
                f"{label} {type_counts[key]}"
                for key, label in labels.items()
                if int(type_counts.get(key, 0)) > 0
            ]
            tooltip = (
                f"本次任务参考 {count} 条已确认记忆"
                + (f"：{' · '.join(summary)}" if summary else "")
                + (
                    f"。其中 {reviewable_count} 条可点击查看并反馈。"
                    if reviewable_count
                    else "。这里只显示数量，不展示记忆内容。"
                )
            )
        else:
            self._memory_context_tone = "empty"
            self._memory_context_badge.setText("记忆 · 0")
            tooltip = "本次没有找到与当前请求足够相关的长期记忆"

        self._memory_context_badge.setToolTip(tooltip)
        self._memory_context_badge.setEnabled(bool(self._memory_context_task_id))
        self._memory_context_badge.show()
        self.refresh_theme()

    def _request_memory_context_review(self) -> None:
        if self._memory_context_task_id:
            self.memory_context_requested.emit(self._memory_context_task_id)

    def refresh_theme(self):
        theme = ThemeManager.instance().current

        self.STYLE_INPUT = generate_input_style(theme)
        self.STYLE_SEND_BTN = (
            f"QPushButton {{ background: {theme.primary}; color: {theme.primary_text}; "
            f"border: none; border-radius: {theme.radius_sm}px; "
            f"padding: 8px 16px; font-size: 13px; font-weight: bold; }} "
            f"QPushButton:hover {{ background: {theme.primary_soft}; color: {theme.text}; }}"
        )
        self.STYLE_USER_MSG = generate_chat_bubble_style(theme, is_user=True)
        self.STYLE_BOT_MSG = generate_chat_bubble_style(theme, is_user=False)
        self.STYLE_HTML_WRAPPER = (
            f'font-family: "Microsoft YaHei UI", "Segoe UI", Arial, sans-serif; '
            f"font-size: 13px; line-height: 1.6; color: {theme.text};"
        )

        self._container.setStyleSheet(
            f"QWidget#container {{ background: {theme.surface}; "
            f"border: 1px solid {theme.border}; border-radius: {theme.radius_lg}px; }}"
        )
        self._header.setStyleSheet(
            f"background: {theme.surface}; border-bottom: 1px solid {theme.border}; "
            f"border-top-left-radius: {theme.radius_lg}px; "
            f"border-top-right-radius: {theme.radius_lg}px;"
        )
        self._header_mood.setStyleSheet(f"color: {theme.text_muted}; font-size: 10px;")
        self.title_label.setStyleSheet(f"color: {theme.text};")
        self._header_avatar.setStyleSheet(
            f"background: {theme.surface_soft}; border: 1px solid {theme.border}; "
            "border-radius: 19px; padding: 2px;"
        )
        header_button_style = (
            f"QPushButton {{ background: transparent; color: {theme.text_secondary}; "
            f"border: none; border-radius: {theme.radius_sm}px; padding: 5px 7px; "
            "font-size: 10px; } "
            f"QPushButton:hover {{ background: {theme.surface_soft}; color: {theme.primary}; }}"
        )
        for button in self._header_buttons:
            button.setStyleSheet(header_button_style)

        status_colors = {
            "idle": theme.pet_status_ok,
            "listening": theme.info,
            "working": theme.pet_status_busy,
            "success": theme.success,
            "warning": theme.warning,
            "error": theme.danger,
        }
        status_color = status_colors.get(self._agent_status_tone, theme.pet_status_ok)
        self._agent_status.setStyleSheet(
            f"color: {status_color}; font-size: 11px; font-weight: 700;"
        )
        self._agent_status_detail.setStyleSheet(f"color: {theme.text_muted}; font-size: 10px;")
        memory_selected = self._memory_context_tone == "selected"
        memory_privacy = self._memory_context_tone == "privacy"
        memory_background = theme.primary_soft if memory_selected else theme.surface_soft
        memory_border = (
            theme.primary if memory_selected else (theme.info if memory_privacy else theme.border)
        )
        memory_text = (
            theme.primary
            if memory_selected
            else (theme.info if memory_privacy else theme.text_muted)
        )
        self._memory_context_badge.setStyleSheet(
            f"background: {memory_background}; color: {memory_text}; "
            f"border: 1px solid {memory_border}; border-radius: {theme.radius_sm}px; "
            "padding: 4px 8px; font-size: 10px; font-weight: 700;"
        )
        self._new_chat_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.surface_soft}; color: {theme.text_secondary}; "
            f"border: 1px solid {theme.border}; border-radius: {theme.radius_sm}px; "
            "padding: 5px 10px; font-size: 10px; font-weight: 600; } "
            f"QPushButton:hover {{ background: {theme.primary_soft}; "
            f"border-color: {theme.primary}; color: {theme.text}; }}"
        )
        self.chat_widget.setStyleSheet(f"background: {theme.chat_bg};")
        self._chat_scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {theme.chat_bg}; }} "
            f"QScrollBar:vertical {{ width: 8px; background: transparent; }} "
            f"QScrollBar::handle:vertical {{ background: {theme.border}; "
            f"border-radius: 4px; min-height: 30px; }}"
        )
        tooltip_style = generate_tooltip_style(theme)
        self._timeline.setStyleSheet(tooltip_style)

        capability_button_style = (
            f"QPushButton {{ background: {theme.surface_soft}; color: {theme.text_secondary}; "
            f"border: 1px solid {theme.border}; border-radius: {theme.radius_sm}px; "
            "padding: 6px 12px; font-size: 11px; } "
            f"QPushButton:hover {{ background: {theme.surface}; "
            f"border-color: {theme.primary}; color: {theme.text}; }}"
        )
        self._capability_bar.setStyleSheet(
            f"background: {theme.surface}; border-top: 1px solid {theme.border};"
        )
        for button in self._capability_buttons:
            button.setStyleSheet(capability_button_style)
        self._mem_info_label.setStyleSheet(f"color: {theme.text_muted}; font-size: 10px;")

        self._input_container.setStyleSheet(
            f"background: {theme.surface}; border-top: 1px solid {theme.border}; "
            f"border-bottom-left-radius: {theme.radius_lg}px; "
            f"border-bottom-right-radius: {theme.radius_lg}px;"
        )
        self.image_preview.setStyleSheet(
            f"background: {theme.surface_soft}; border: 1px solid {theme.border}; "
            f"border-radius: {theme.radius_sm}px;"
        )
        self.image_preview_title.setStyleSheet(
            f"color: {theme.text}; font-size: 11px; font-weight: 700;"
        )
        self.image_preview_text.setStyleSheet(f"color: {theme.text_muted}; font-size: 9px;")
        self._clear_image_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.text_muted}; "
            "border: none; padding: 4px 7px; font-size: 9px; } "
            f"QPushButton:hover {{ color: {theme.danger}; background: {theme.surface}; }}"
        )
        self._image_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.surface_soft}; color: {theme.text_secondary}; "
            f"border: 1px solid {theme.border}; border-radius: 18px; font-size: 18px; }} "
            f"QPushButton:hover {{ background: {theme.primary_soft}; "
            f"border-color: {theme.primary}; color: {theme.text}; }}"
        )
        self._screen_region_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.primary_soft}; color: {theme.primary}; "
            f"border: 1px solid {theme.border_focus}; border-radius: {theme.radius_sm}px; "
            "font-size: 10px; font-weight: 700; } "
            f"QPushButton:hover {{ background: {theme.surface}; "
            f"border-color: {theme.primary}; color: {theme.text}; }}"
        )
        self.input_box.setStyleSheet(self.STYLE_INPUT)
        self._send_btn.setStyleSheet(self.STYLE_SEND_BTN)
        self.size_grip.setStyleSheet(
            f"QSizeGrip {{ background: {theme.primary}; border-radius: 4px; }}"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_pos:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()
