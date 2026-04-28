"""History window for Lobuddy."""

from datetime import datetime
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QFont

from core.storage.chat_repo import ChatRepository


class HistoryWindow(QDialog):
    """Dialog showing chat session history."""

    session_selected = Signal(str)

    def __init__(self, chat_repo: ChatRepository, parent=None):
        super().__init__(parent)
        self.chat_repo = chat_repo
        self._init_ui()
        self._load_sessions()

    def _init_ui(self):
        self.setWindowTitle("History")
        self.setMinimumSize(420, 520)
        self.setMaximumSize(520, 700)

        # Creamy / orange theme matching Lobuddy
        self.setStyleSheet("""
            QDialog {
                background-color: #FFF7ED;
            }
            QLabel {
                color: #1F2937;
            }
            QPushButton {
                background: #F97316;
                color: white;
                border: none;
                border-radius: 10px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #EA580C;
            }
            QScrollArea {
                border: none;
                background: #FFF7ED;
            }
            QScrollBar:vertical {
                width: 8px;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: #F3D9B1;
                border-radius: 4px;
                min-height: 30px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title = QLabel("Chat History")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #F97316;")
        header.addWidget(title)
        header.addStretch()

        close_btn = QPushButton("x")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            "background: rgba(249,115,22,0.15); color: #F97316; border-radius: 14px; "
            "font-size: 14px; font-weight: bold; padding: 0px;"
        )
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # Scroll area for sessions
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.session_container = QWidget()
        self.session_layout = QVBoxLayout(self.session_container)
        self.session_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.session_layout.setSpacing(10)
        self.session_layout.setContentsMargins(4, 4, 4, 4)

        scroll.setWidget(self.session_container)
        layout.addWidget(scroll, 1)

    def _load_sessions(self):
        """Load and display all chat sessions."""
        # Clear existing widgets
        while self.session_layout.count():
            item = self.session_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        sessions = self.chat_repo.get_all_sessions(limit=50)

        if not sessions:
            empty_label = QLabel("No chat history yet.\nStart a conversation to see it here!")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(
                "color: #9CA3AF; font-size: 14px; padding: 40px;"
            )
            self.session_layout.addWidget(empty_label)
            return

        for session in sessions:
            card = self._create_session_card(session)
            self.session_layout.addWidget(card)

        self.session_layout.addStretch()

    def _create_session_card(self, session) -> QWidget:
        """Create a clickable card for a session."""
        card = QWidget()
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setStyleSheet("""
            QWidget {
                background: #FFFFFF;
                border: 1px solid #F3D9B1;
                border-radius: 12px;
            }
            QWidget:hover {
                background: #FFF7ED;
                border-color: #F97316;
            }
        """)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Title row
        title_row = QHBoxLayout()
        title_label = QLabel(session.title or "New Chat")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #1F2937; border: none; background: transparent;")
        title_row.addWidget(title_label)
        title_row.addStretch()

        # Time
        time_text = self._format_time(session.updated_at)
        time_label = QLabel(time_text)
        time_label.setStyleSheet("color: #9CA3AF; font-size: 11px; border: none; background: transparent;")
        title_row.addWidget(time_label)
        layout.addLayout(title_row)

        msg_count = len(self.chat_repo.get_messages(session.id))
        count_label = QLabel(f"{msg_count} messages")
        count_label.setStyleSheet("color: #6B7280; font-size: 12px; border: none; background: transparent;")
        layout.addWidget(count_label)

        # Recent message preview (if any)
        if session.messages:
            preview_text = session.messages[-1].content[:60]
            if len(session.messages[-1].content) > 60:
                preview_text += "..."
            preview_label = QLabel(preview_text)
            preview_label.setStyleSheet("color: #6B7280; font-size: 11px; border: none; background: transparent;")
            preview_label.setWordWrap(True)
            layout.addWidget(preview_label)

        # Click handler
        def make_handler(sid):
            return lambda: self._on_session_clicked(sid)

        card.mousePressEvent = lambda evt, sid=session.id: self._on_session_clicked(sid)

        return card

    def _on_session_clicked(self, session_id: str):
        """Emit signal when a session is selected."""
        self.session_selected.emit(session_id)
        self.accept()

    @staticmethod
    def _format_time(dt: datetime) -> str:
        """Format datetime to human-readable string."""
        if not dt:
            return ""
        now = datetime.now()
        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        elif dt.date() == now.date().replace(day=now.day - 1):
            return "Yesterday"
        else:
            return dt.strftime("%Y-%m-%d")

    def showEvent(self, event):
        """Reload sessions each time window opens."""
        super().showEvent(event)
        self._load_sessions()
