"""Conversation timeline widget - right-side dots for message navigation."""

from datetime import datetime
from PySide6.QtCore import Qt, Signal, QPoint, QRect
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QToolTip, QScrollArea,
)
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QMouseEvent


class TimelineDot:
    def __init__(self, msg_id: str, content: str, created_at: datetime, bubble: QWidget):
        self.msg_id = msg_id
        self.content = content
        self.created_at = created_at
        self.bubble = bubble


class ConversationTimelineWidget(QWidget):
    dot_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dots: list[TimelineDot] = []
        self._enabled = True
        self._tooltip_enabled = True
        self._min_gap_px = 8
        self._preview_max = 32
        self._hovered_index = -1
        self.setFixedWidth(18)
        self.setMouseTracking(True)

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.setVisible(enabled)
        if not enabled:
            self._dots.clear()
            self.update()

    def set_config(self, min_gap_px: int, preview_max: int, tooltip: bool):
        self._min_gap_px = min_gap_px
        self._preview_max = preview_max
        self._tooltip_enabled = tooltip

    def add_dot(self, msg_id: str, content: str, created_at: datetime, bubble: QWidget):
        if not self._enabled:
            return
        self._dots.append(TimelineDot(msg_id, content, created_at, bubble))
        self.update()

    def clear(self):
        self._dots.clear()
        self.update()

    def rebuild_from_msg_data(self, msg_data: list):
        self._dots.clear()
        for item in msg_data:
            widget = item.get("widget")
            if widget and item.get("msg_id") and item.get("created_at"):
                self._dots.append(TimelineDot(
                    item["msg_id"],
                    widget.findChild(QLabel).text() if widget.findChild(QLabel) else "",
                    item["created_at"],
                    widget,
                ))
        self.update()

    def paintEvent(self, event):
        if not self._dots:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        h = self.height()
        count = len(self._dots)
        if count == 0:
            return

        visible = self._compute_visible_dots(h)

        for i, idx in enumerate(visible):
            y = h - 10 - (i / max(len(visible) - 1, 1)) * (h - 20)

            is_hovered = (self._hovered_index == idx)
            radius = 4 if is_hovered else 3
            color = QColor("#FF8A3D") if is_hovered else QColor("#F1D9C0")
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            cx = self.width() // 2
            painter.drawEllipse(QPoint(cx, int(y)), radius, radius)
        painter.end()

    def _compute_visible_dots(self, available_height: int) -> list:
        count = len(self._dots)
        if count == 0:
            return []
        max_dots = max(1, (available_height - 20) // self._min_gap_px + 1)
        if count <= max_dots:
            return list(range(count))
        step = count / max_dots
        return [int(i * step) for i in range(max_dots)]

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self._tooltip_enabled:
            return
        h = self.height()
        visible = self._compute_visible_dots(h)
        if not visible:
            return

        y = event.pos().y()
        for i, idx in enumerate(visible):
            dy = h - 10 - (i / max(len(visible) - 1, 1)) * (h - 20)
            if abs(y - dy) < 6:
                if self._hovered_index != idx:
                    self._hovered_index = idx
                    self.update()
                    dot = self._dots[idx]
                    from core.time_format import format_message_time
                    preview = dot.content[:self._preview_max]
                    if len(dot.content) > self._preview_max:
                        preview += "..."
                    time_str = format_message_time(dot.created_at, "HH:mm")
                    QToolTip.showText(
                        event.globalPos(),
                        f"{time_str} {preview}",
                        self,
                    )
                return
        self._hovered_index = -1
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._hovered_index >= 0 and self._hovered_index < len(self._dots):
            dot = self._dots[self._hovered_index]
            if dot.bubble:
                scroll = self._find_scroll_area()
                if scroll:
                    scroll.ensureWidgetVisible(dot.bubble, 0, 50)

    def _find_scroll_area(self):
        w = self.parent()
        while w:
            if isinstance(w, QScrollArea):
                return w
            if hasattr(w, 'findChild'):
                scroll = w.findChild(QScrollArea)
                if scroll:
                    return scroll
            w = w.parent() if hasattr(w, 'parent') and callable(getattr(w, 'parent', None)) else None
        return None
