"""Chat panel with conversation management and image support."""

import uuid
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QPoint
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
    QApplication,
)
from PySide6.QtGui import QFont, QMovie, QPixmap
import markdown
from ui.styles import (
    TASKPANEL_TRANSPARENT,
    TASKPANEL_CONTAINER,
    TASKPANEL_HEADER,
    TASKPANEL_TITLE,
    TASKPANEL_CLOSE_BTN,
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
    TASKPANEL_HISTORY_BTN,
    TASKPANEL_NEW_CHAT_BTN,
)
from ui.theme import (
    ThemeManager,
    ThemeColors,
    generate_chat_bubble_style,
    generate_input_style,
    generate_tooltip_style,
)
from ui.widgets.conversation_timeline import ConversationTimelineWidget
from core.skills.skill_registry import SkillRegistry


class HTMLSanitizer(HTMLParser):
    ALLOWED_TAGS = {'p', 'br', 'strong', 'b', 'em', 'i', 'code', 'pre',
                    'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                    'a', 'blockquote', 'span', 'div'}
    ALLOWED_ATTRS = {'href': ['a'], 'title': ['a']}

    def __init__(self):
        super().__init__()
        self.result = []
        self.skip = False

    def _escape_attr(self, value):
        return (value
                .replace('&', '&amp;')
                .replace('"', '&quot;')
                .replace('<', '&lt;')
                .replace('>', '&gt;'))

    def handle_starttag(self, tag, attrs):
        if tag in self.ALLOWED_TAGS:
            if tag in self.ALLOWED_ATTRS.get('href', []):
                attrs_dict = dict(attrs)
                href = (attrs_dict.get('href', '') or '').strip()
                allowed_schemes = {'http:', 'https:', 'mailto:'}
                if not any(href.lower().startswith(s) for s in allowed_schemes):
                    return
                safe_href = self._escape_attr(href)
                self.result.append(f'<{tag} href="{safe_href}">')
            else:
                self.result.append(f'<{tag}>')
        else:
            self.skip = True

    def handle_endtag(self, tag):
        if tag in self.ALLOWED_TAGS and not self.skip:
            self.result.append(f'</{tag}>')
        self.skip = False

    def handle_data(self, data):
        if not self.skip:
            import html
            self.result.append(html.escape(data))

    def get_clean_html(self):
        return ''.join(self.result)


def sanitize_html(html_str: str) -> str:
    sanitizer = HTMLSanitizer()
    sanitizer.feed(html_str)
    return sanitizer.get_clean_html()


class TaskPanel(QDialog):
    """Chat dialog with compact layout, history hidden by default."""

    task_submitted = Signal(str, str, str)
    history_requested = Signal()
    settings_requested = Signal()

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
                size.width(), size.height(),
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
        self._settings = None
        self._focus_active = False
        self._skill_registry = SkillRegistry()
        self._skill_panel = None
        self._init_ui()
        self._load_header_avatar()

    def _init_ui(self):
        self.setMinimumSize(420, 520)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(TASKPANEL_TRANSPARENT)
        self.setAutoFillBackground(False)

        container = QWidget(self)
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
        header.setFixedHeight(76)
        header.setStyleSheet(TASKPANEL_HEADER)

        header_vlayout = QVBoxLayout(header)
        header_vlayout.setContentsMargins(14, 6, 14, 4)
        header_vlayout.setSpacing(4)

        id_row = QHBoxLayout()
        id_row.setSpacing(8)

        self._header_avatar = QLabel()
        self._header_avatar.setFixedSize(26, 26)
        self._header_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header_avatar.setStyleSheet(
            "background: rgba(255,255,255,0.25); border-radius: 13px; "
            "font-size: 14px;"
        )
        id_row.addWidget(self._header_avatar)

        self.title_label = QLabel("Lobuddy")
        self.title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        self.title_label.setStyleSheet(TASKPANEL_TITLE)
        id_row.addWidget(self.title_label)

        self._header_mood = QLabel("今天也要一起加油哦～")
        self._header_mood.setStyleSheet(
            "color: rgba(255,255,255,0.75); font-size: 10px;"
        )
        id_row.addWidget(self._header_mood, stretch=1)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(TASKPANEL_CLOSE_BTN)
        close_btn.clicked.connect(self.hide)
        id_row.addWidget(close_btn)

        history_btn = QPushButton("☰")
        history_btn.setFixedSize(24, 24)
        history_btn.setStyleSheet(TASKPANEL_HISTORY_BTN)
        history_btn.setToolTip("History")
        history_btn.clicked.connect(self.history_requested.emit)
        id_row.addWidget(history_btn)

        settings_btn = QPushButton("⚙")
        settings_btn.setFixedSize(24, 24)
        settings_btn.setStyleSheet(TASKPANEL_HISTORY_BTN)
        settings_btn.setToolTip("Settings")
        settings_btn.clicked.connect(self.settings_requested.emit)
        id_row.addWidget(settings_btn)
        header_vlayout.addLayout(id_row)

        qa_row = QHBoxLayout()
        qa_row.setSpacing(6)
        qa_btn_style = (
            "QPushButton { background: rgba(255,255,255,0.2); color: white; "
            "border: none; border-radius: 10px; padding: 4px 10px; font-size: 11px; } "
            "QPushButton:hover { background: rgba(255,255,255,0.35); }"
        )
        qa_actions = [
            ("陪我聊聊", self._on_new_chat),
            ("聊天记录", self.history_requested.emit),
            ("设置小窝", self.settings_requested.emit),
        ]
        for label, handler in qa_actions:
            btn = QPushButton(label)
            btn.setStyleSheet(qa_btn_style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(handler)
            qa_row.addWidget(btn)
        qa_row.addStretch()

        new_chat_btn = QPushButton("+ 新对话")
        new_chat_btn.setStyleSheet(qa_btn_style)
        new_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_chat_btn.clicked.connect(self._on_new_chat)
        qa_row.addWidget(new_chat_btn)
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
        cards_widget.setFixedHeight(52)
        cards_layout = QHBoxLayout(cards_widget)
        cards_layout.setContentsMargins(16, 4, 16, 4)
        cards_layout.setSpacing(8)

        card_style = (
            "QPushButton { background: #FFF7ED; color: #6B4E3D; "
            "border: 1px solid #F1D9C0; border-radius: 12px; "
            "padding: 6px 14px; font-size: 11px; } "
            "QPushButton:hover { background: #FFF1DF; border-color: #FF8A3D; }"
        )
        mem_btn = QPushButton("我的记忆")
        mem_btn.setStyleSheet(card_style)
        mem_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mem_btn.clicked.connect(self.history_requested.emit)
        cards_layout.addWidget(mem_btn)

        skill_btn = QPushButton("我会的技能")
        skill_btn.setStyleSheet(card_style)
        skill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        skill_btn.clicked.connect(self._on_show_skills)
        cards_layout.addWidget(skill_btn)

        mem_label = QLabel("最近: 聊过天、帮过忙、记得你")
        mem_label.setStyleSheet("color: #A0846C; font-size: 10px;")
        mem_label.setWordWrap(True)
        cards_layout.addWidget(mem_label, stretch=1)
        main_layout.addWidget(cards_widget)

        input_container = QWidget()
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
        self.image_preview_text = QLabel()
        preview_layout.addWidget(self.image_preview_text)
        preview_layout.addStretch()
        input_container_layout.addWidget(self.image_preview)

        input_area = QWidget()
        input_area.setFixedHeight(50)
        input_layout = QHBoxLayout(input_area)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)

        image_btn = QPushButton("📎")
        image_btn.setFixedSize(36, 36)
        image_btn.setStyleSheet(TASKPANEL_IMAGE_BTN)
        image_btn.clicked.connect(self._on_select_image)
        input_layout.addWidget(image_btn)

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("想和我聊点什么呢？")
        self.input_box.setFont(QFont("Microsoft YaHei", 11))
        self.input_box.setStyleSheet(self.STYLE_INPUT)
        self.input_box.returnPressed.connect(self._on_send)
        input_layout.addWidget(self.input_box)

        send_btn = QPushButton("Send")
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
        self.size_grip.setStyleSheet(
            "QSizeGrip { background: #F97316; border-radius: 4px; }"
        )
        grip_layout.addWidget(self.size_grip)
        main_layout.addLayout(grip_layout)

    def _on_select_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
        )
        if file_path:
            p = Path(file_path)
            if not p.is_file():
                QMessageBox.warning(self, "Invalid File", "Selected file does not exist.")
                return
            if p.stat().st_size > 50 * 1024 * 1024:
                QMessageBox.warning(self, "File Too Large", "Image must be under 50MB.")
                return
            self.current_image_path = file_path
            self._update_image_preview(file_path)

    def _update_image_preview(self, image_path: str):
        self.image_preview_label.clear()
        self.image_preview_text.clear()
        self._load_image_to_label(self.image_preview_label, image_path, QSize(50, 50))
        self.image_preview_text.setText(Path(image_path).name)
        self.image_preview.show()

    def _stop_image_preview_movie(self):
        if getattr(self.image_preview_label, "_movie", None) is not None:
            self.image_preview_label._movie.stop()
            self.image_preview_label._movie.deleteLater()
            self.image_preview_label._movie = None

    def _clear_image_preview(self):
        self.current_image_path = None
        self._stop_image_preview_movie()
        self.image_preview_label.clear()
        self.image_preview_text.clear()
        self.image_preview.hide()

    def _on_new_chat(self):
        session_id = f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.current_session_id = session_id
        from core.models.chat import ChatSession

        session = ChatSession(id=session_id, title="New Chat")
        self.chat_repo.save_session(session)
        self._clear_chat_display()
        self._clear_image_preview()
        self._timeline.clear()
        self.title_label.setText("New Chat")

    def _on_show_skills(self):
        if not self._settings or not self._settings.skill_panel_enabled:
            return
        if self._skill_panel is None:
            from ui.skill_panel import SkillPanel

            self._skill_panel = SkillPanel(
                self._skill_registry, self._settings, parent=self
            )
            self._skill_panel.example_selected.connect(self._on_skill_example_selected)
        self._skill_panel.show()
        self._skill_panel.raise_()
        self._skill_panel.activateWindow()

    def _on_skill_example_selected(self, example: str):
        self.input_box.setText(example)
        self.input_box.setFocus()

    def _load_session_messages(self, session_id: str):
        self._clear_chat_display()
        self._clear_image_preview()
        self._timeline.clear()
        session = self.chat_repo.get_session(session_id)
        if session:
            self.title_label.setText(session.title or "Chat")
            for msg in session.messages:
                is_user = msg.role == "user"
                self._add_message_to_display(
                    msg.content, is_user=is_user, is_markdown=not is_user,
                    image_path=msg.image_path, created_at=msg.created_at, msg_id=msg.id
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
        tl_enabled = getattr(settings, 'conversation_timeline_enabled', True)
        self._timeline.set_enabled(tl_enabled)
        gap = getattr(settings, 'conversation_timeline_min_dot_gap_px', 8)
        preview = getattr(settings, 'conversation_timeline_preview_max_chars', 32)
        tooltip = getattr(settings, 'conversation_timeline_tooltip_enabled', True)
        self._timeline.set_config(gap, preview, tooltip)

    def _add_message_to_display(
        self, text: str, is_user: bool = True, is_markdown: bool = False,
        image_path: str = None, created_at: datetime = None, msg_id: str = None
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

        if created_at and self._settings and getattr(self._settings, 'chat_message_time_enabled', True):
            from core.time_format import format_message_time
            time_fmt = getattr(self._settings, 'chat_time_format', 'HH:mm')
            time_text = format_message_time(created_at, time_fmt)
            time_label = QLabel(time_text)
            time_label.setStyleSheet(
                "color: #A0846C; font-size: 10px; padding: 1px 4px;"
            )
            time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addWidget(time_label)

        if msg_id:
            bubble.setProperty("msg_id", msg_id)
            self._msg_data.append({"widget": bubble, "msg_id": msg_id, "created_at": created_at, "content": text})
            if is_user and self._settings and getattr(self._settings, 'conversation_timeline_enabled', True):
                self._timeline.add_dot(msg_id, text, created_at, bubble)

        self._insert_time_divider(created_at)

        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        self.messages.append(bubble)
        QTimer.singleShot(50, self._scroll_bottom)

    def _insert_time_divider(self, created_at: datetime = None):
        if not created_at or not self._settings:
            return
        if not getattr(self._settings, 'chat_time_divider_enabled', True):
            return
        gap = getattr(self._settings, 'chat_time_divider_gap_minutes', 5)
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
        divider.setStyleSheet(
            "color: #A0846C; font-size: 10px; padding: 4px 12px; "
            "margin: 4px 0;"
        )
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
            session = self.chat_repo.get_session(self.current_session_id)
            is_first_message = session is None or len(session.messages) == 0

            import uuid
            now = datetime.now()
            self._add_message_to_display(
                text, is_user=True, image_path=self.current_image_path,
                created_at=now, msg_id=str(uuid.uuid4())
            )
            self.task_submitted.emit(text, self.current_session_id, self.current_image_path or "")

            self.input_box.clear()
            self._clear_image_preview()

            if is_first_message and text:
                title = text[:30] + "..." if len(text) > 30 else text
                self.chat_repo.update_session_title(self.current_session_id, title)
                self.title_label.setText(title)

    def add_pet_response(self, text: str, session_id: str = None, created_at: datetime = None, msg_id: str = None):
        if session_id is None or session_id == self.current_session_id:
            self._add_message_to_display(
                text, is_user=False, is_markdown=True,
                created_at=created_at, msg_id=msg_id
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
        from pathlib import Path

        app = get_appearance()
        path = getattr(app, "custom_asset_path", None)
        if path and Path(path).exists():
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    26, 26,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._header_avatar.setPixmap(pixmap)
                self._header_avatar.setStyleSheet(
                    "border-radius: 13px;"
                )
                return
        self._header_avatar.setText("🐱")

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
            f'font-size: 13px; line-height: 1.6; color: {theme.text};'
        )

        self._header.setStyleSheet(
            f"background: {theme.header_bg}; "
            f"border-top-left-radius: {theme.radius_lg}px; "
            f"border-top-right-radius: {theme.radius_lg}px;"
        )
        self._header_mood.setStyleSheet(
            f"color: rgba(255,255,255,0.75); font-size: 10px;"
        )
        self.title_label.setStyleSheet(f"color: {theme.header_text};")
        self.chat_widget.setStyleSheet(f"background: {theme.chat_bg};")
        self._chat_scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {theme.chat_bg}; }} "
            f"QScrollBar:vertical {{ width: 8px; background: transparent; }} "
            f"QScrollBar::handle:vertical {{ background: {theme.border}; "
            f"border-radius: 4px; min-height: 30px; }}"
        )
        tooltip_style = generate_tooltip_style(theme)
        self._timeline.setStyleSheet(tooltip_style)
        self.input_box.setStyleSheet(self.STYLE_INPUT)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_pos:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()
