"""Chat panel with conversation management and image support."""

import uuid
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QGraphicsDropShadowEffect,
)
from PySide6.QtGui import QFont, QColor, QMovie, QPixmap
import markdown


class TaskPanel(QDialog):
    """Chat dialog with conversation history sidebar and image support."""

    task_submitted = Signal(str, str, str)

    def __init__(self, chat_repo, parent=None):
        super().__init__(parent)
        self.chat_repo = chat_repo
        self.current_session_id = "default"
        self.messages = []
        self.drag_pos = None
        self.current_image_path = None
        self._init_ui()
        self._load_session_list()

    def _init_ui(self):
        self.setMinimumSize(650, 550)
        self.setMaximumSize(800, 700)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        container = QWidget(self)
        container.setObjectName("container")
        container.setStyleSheet("""
            QWidget#container {
                background-color: #ffffff;
                border-radius: 16px;
                border: 1px solid #e0e0e0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(container)

        main_layout = QHBoxLayout(container)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(180)
        sidebar.setStyleSheet(
            "background-color: #f5f5f5; border-top-left-radius: 16px; border-bottom-left-radius: 16px;"
        )
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setSpacing(8)
        sidebar_layout.setContentsMargins(12, 16, 12, 16)

        new_chat_btn = QPushButton("+ New Chat")
        new_chat_btn.setStyleSheet(
            "background: #4CAF50; color: white; border: none; border-radius: 8px; padding: 10px; font-size: 13px; font-weight: bold;"
        )
        new_chat_btn.clicked.connect(self._on_new_chat)
        sidebar_layout.addWidget(new_chat_btn)

        history_label = QLabel("History")
        history_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        history_label.setStyleSheet("color: #666; margin-top: 10px;")
        sidebar_layout.addWidget(history_label)

        self.session_list = QListWidget()
        self.session_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; outline: none; }
            QListWidget::item { background: transparent; padding: 8px; border-radius: 6px; margin: 2px 0; }
            QListWidget::item:selected { background: #4CAF50; color: white; }
            QListWidget::item:hover { background: #e0e0e0; }
            QListWidget::item:selected:hover { background: #45a049; }
        """)
        self.session_list.itemClicked.connect(self._on_session_selected)
        sidebar_layout.addWidget(self.session_list)

        delete_btn = QPushButton("Delete")
        delete_btn.setStyleSheet(
            "background: #f44336; color: white; border: none; border-radius: 6px; padding: 8px; font-size: 12px;"
        )
        delete_btn.clicked.connect(self._on_delete_session)
        sidebar_layout.addWidget(delete_btn)

        main_layout.addWidget(sidebar)

        # Chat area
        chat_area = QWidget()
        chat_layout = QVBoxLayout(chat_area)
        chat_layout.setSpacing(0)
        chat_layout.setContentsMargins(0, 0, 0, 0)

        header = QWidget()
        header.setFixedHeight(50)
        header.setStyleSheet("background-color: #4CAF50; border-top-right-radius: 16px;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        self.title_label = QLabel("Current Chat")
        self.title_label.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: white;")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        close_btn = QPushButton("x")
        close_btn.setFixedSize(26, 26)
        close_btn.setStyleSheet(
            "background: rgba(255,255,255,0.25); color: white; border: none; border-radius: 13px; font-size: 14px; font-weight: bold;"
        )
        close_btn.clicked.connect(self.hide)
        header_layout.addWidget(close_btn)

        chat_layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: #f8f9fa; } QScrollBar:vertical { width: 8px; background: transparent; } QScrollBar::handle:vertical { background: #c1c1c1; border-radius: 4px; min-height: 30px; }"
        )

        self.chat_widget = QWidget()
        self.chat_widget.setStyleSheet("background: #f8f9fa;")
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_layout.setSpacing(12)
        self.chat_layout.setContentsMargins(16, 16, 16, 16)
        self.chat_layout.addStretch()

        scroll.setWidget(self.chat_widget)
        chat_layout.addWidget(scroll, 1)

        # Input area
        input_container = QWidget()
        input_container.setStyleSheet("background: white; border-bottom-right-radius: 16px;")
        input_container_layout = QVBoxLayout(input_container)
        input_container_layout.setContentsMargins(16, 8, 16, 8)
        input_container_layout.setSpacing(4)

        # Image preview area
        self.image_preview = QWidget()
        self.image_preview.setFixedHeight(60)
        self.image_preview.setStyleSheet("background: #f0f0f0; border-radius: 8px;")
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

        # Text input and buttons
        input_area = QWidget()
        input_area.setFixedHeight(50)
        input_layout = QHBoxLayout(input_area)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)

        # Image button
        image_btn = QPushButton("📎")
        image_btn.setFixedSize(36, 36)
        image_btn.setStyleSheet(
            "QPushButton { background: #f0f0f0; border: none; border-radius: 18px; font-size: 16px; } "
            "QPushButton:hover { background: #e0e0e0; }"
        )
        image_btn.clicked.connect(self._on_select_image)
        input_layout.addWidget(image_btn)

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Type a message...")
        self.input_box.setFont(QFont("Microsoft YaHei", 11))
        self.input_box.setStyleSheet(
            "QLineEdit { background: #f0f0f0; border: none; border-radius: 20px; padding: 8px 16px; font-size: 13px; color: #333; } QLineEdit:focus { background: #e8e8e8; }"
        )
        self.input_box.returnPressed.connect(self._on_send)
        input_layout.addWidget(self.input_box)

        send_btn = QPushButton("Send")
        send_btn.setFixedSize(70, 36)
        send_btn.setStyleSheet(
            "QPushButton { background: #4CAF50; color: white; border: none; border-radius: 18px; font-size: 13px; font-weight: bold; } QPushButton:hover { background: #45a049; } QPushButton:pressed { background: #3d8b40; }"
        )
        send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(send_btn)

        input_container_layout.addWidget(input_area)
        chat_layout.addWidget(input_container)
        main_layout.addWidget(chat_area, 1)

    def _on_select_image(self):
        """Open file dialog to select image."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
        )
        if file_path:
            self.current_image_path = file_path
            self._update_image_preview(file_path)

    def _update_image_preview(self, image_path: str):
        """Update image preview label."""
        self._stop_image_preview_movie()
        self.image_preview_label.clear()
        self.image_preview_text.clear()

        if Path(image_path).suffix.lower() == ".gif":
            movie = QMovie(image_path)
            movie.setScaledSize(QSize(50, 50))
            movie.setParent(self.image_preview_label)
            self.image_preview_label.setMovie(movie)
            movie.start()
            self.image_preview_label._movie = movie
            self.image_preview_text.setText(Path(image_path).name)
            self.image_preview.show()
            return

        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(
                50,
                50,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_preview_label.setPixmap(pixmap)
            self.image_preview_text.setText(Path(image_path).name)
            self.image_preview.show()
        else:
            self.image_preview_label.clear()
            self.image_preview_text.setText(f"📷 {Path(image_path).name}")
            self.image_preview.show()

    def _stop_image_preview_movie(self):
        if getattr(self.image_preview_label, "_movie", None) is not None:
            self.image_preview_label._movie.stop()
            self.image_preview_label._movie.deleteLater()
            self.image_preview_label._movie = None

    def _clear_image_preview(self):
        """Clear image preview."""
        self.current_image_path = None
        self._stop_image_preview_movie()
        self.image_preview_label.clear()
        self.image_preview_text.clear()
        self.image_preview.hide()

    def _load_session_list(self):
        self.session_list.clear()
        sessions = self.chat_repo.get_all_sessions(limit=20)
        for session in sessions:
            item = QListWidgetItem(session.title or "New Chat")
            item.setData(Qt.ItemDataRole.UserRole, session.id)
            self.session_list.addItem(item)
            if session.id == self.current_session_id:
                self.session_list.setCurrentItem(item)

    def _on_new_chat(self):
        session_id = f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.current_session_id = session_id
        from core.models.chat import ChatSession

        session = ChatSession(id=session_id, title="New Chat")
        self.chat_repo.save_session(session)
        self._clear_chat_display()
        self._clear_image_preview()
        self._load_session_list()
        self.title_label.setText("New Chat")

    def _on_session_selected(self, item):
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if session_id != self.current_session_id:
            self.current_session_id = session_id
            self._load_session_messages(session_id)

    def _load_session_messages(self, session_id: str):
        self._clear_chat_display()
        self._clear_image_preview()
        session = self.chat_repo.get_session(session_id)
        if session:
            self.title_label.setText(session.title or "Chat")
            for msg in session.messages:
                is_user = msg.role == "user"
                self._add_message_to_display(
                    msg.content, is_user, is_markdown=not is_user, image_path=msg.image_path
                )

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

    def _add_message_to_display(
        self, text: str, is_user: bool = True, is_markdown: bool = False, image_path: str = None
    ):
        """Add message bubble to display, optionally with image."""
        bubble = QWidget()
        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Image display
        if image_path:
            img_label = QLabel()
            img_label.setFixedSize(200, 150)
            img_label.setStyleSheet("background: #e0e0e0; border-radius: 8px;")
            img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            if Path(image_path).suffix.lower() == ".gif":
                movie = QMovie(image_path)
                movie.setScaledSize(QSize(200, 150))
                movie.setParent(img_label)
                img_label.setMovie(movie)
                movie.start()
                img_label._movie = movie
            else:
                pixmap = QPixmap(image_path)
                if not pixmap.isNull():
                    pixmap = pixmap.scaled(
                        200,
                        150,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    img_label.setPixmap(pixmap)
                else:
                    img_label.setText("📷 Image")

            if is_user:
                img_layout = QHBoxLayout()
                img_layout.addStretch()
                img_layout.addWidget(img_label)
                layout.addLayout(img_layout)
            else:
                layout.addWidget(img_label)

        # Text message
        msg_layout = QHBoxLayout()
        msg_layout.setContentsMargins(0, 0, 0, 0)
        msg_label = QLabel()
        msg_label.setWordWrap(True)
        msg_label.setFont(QFont("Microsoft YaHei", 11))
        msg_label.setMaximumWidth(350)
        msg_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        if is_user:
            msg_label.setText(text)
            msg_label.setStyleSheet(
                "QLabel { background-color: #4CAF50; color: white; padding: 10px 14px; border-radius: 18px; border-bottom-right-radius: 4px; }"
            )
            msg_layout.addStretch()
            msg_layout.addWidget(msg_label)
        else:
            if is_markdown:
                md = markdown.Markdown(extensions=["nl2br"])
                html = md.convert(text)
                styled_html = f'<div style="font-family: Microsoft YaHei; font-size: 13px; line-height: 1.6; color: #333;">{html}</div>'
                msg_label.setTextFormat(Qt.TextFormat.RichText)
                msg_label.setText(styled_html)
            else:
                msg_label.setText(text)
            msg_label.setStyleSheet(
                "QLabel { background-color: #e9ecef; color: #333; padding: 10px 14px; border-radius: 18px; border-bottom-left-radius: 4px; }"
            )
            msg_layout.addWidget(msg_label)
            msg_layout.addStretch()

        layout.addLayout(msg_layout)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        self.messages.append(bubble)
        QTimer.singleShot(50, self._scroll_bottom)

    def _scroll_bottom(self):
        scroll = self.chat_widget.parent()
        if isinstance(scroll, QScrollArea):
            bar = scroll.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _on_send(self):
        text = self.input_box.text().strip()
        if text or self.current_image_path:
            session = self.chat_repo.get_session(self.current_session_id)
            is_first_message = session is None or len(session.messages) == 0

            self._add_message_to_display(text, is_user=True, image_path=self.current_image_path)
            self.task_submitted.emit(text, self.current_session_id, self.current_image_path or "")

            self.input_box.clear()
            self._clear_image_preview()

            if is_first_message and text:
                title = text[:30] + "..." if len(text) > 30 else text
                self.chat_repo.update_session_title(self.current_session_id, title)
                self.title_label.setText(title)
                self._load_session_list()

    def add_pet_response(self, text: str, session_id: str = None):
        if session_id is None or session_id == self.current_session_id:
            self._add_message_to_display(text, is_user=False, is_markdown=True)

    def _on_delete_session(self):
        current_item = self.session_list.currentItem()
        if current_item:
            session_id = current_item.data(Qt.ItemDataRole.UserRole)
            self.chat_repo.delete_session(session_id)
            if session_id == self.current_session_id:
                self._clear_chat_display()
                self._clear_image_preview()
                self.current_session_id = "default"
                self._load_session_messages("default")
            self._load_session_list()

    def set_position_near(self, x: int, y: int):
        self.move(x + 140, y)

    def hideEvent(self, event):
        self._stop_image_preview_movie()
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
        self._load_session_list()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_pos:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()
