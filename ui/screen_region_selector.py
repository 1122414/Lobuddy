"""Full-screen, user-driven selector for an ephemeral visual question."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, QPoint, QRect, QTemporaryFile, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QDialog, QWidget

from core.screen_region.models import (
    ScreenRegionBounds,
    ScreenRegionDraft,
)
from ui.theme import ThemeManager


class ScreenRegionSelector(QDialog):
    """Freeze one screen and let the user explicitly choose the shared pixels."""

    def __init__(
        self,
        parent: QWidget,
        *,
        minimum_size: int = 24,
        background: QPixmap | None = None,
        screen_geometry: QRect | None = None,
        screen_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("screenRegionSelector")
        self.setWindowTitle("框选屏幕区域")
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._minimum_size = max(8, minimum_size)
        self._start: QPoint | None = None
        self._selection = QRect()
        self._draft: ScreenRegionDraft | None = None
        self._error_message = ""

        if background is None:
            screen = QGuiApplication.screenAt(QCursor.pos())
            screen = screen or QGuiApplication.primaryScreen()
            if screen is None:
                raise RuntimeError("No screen is available for region selection")
            background = screen.grabWindow(0)
            screen_geometry = screen.geometry()
            screen_name = screen.name()
        if background.isNull():
            raise RuntimeError("Could not capture the selected screen")

        self._background = background
        self._screen_geometry = screen_geometry or QRect(
            0,
            0,
            background.width(),
            background.height(),
        )
        self._screen_name = screen_name
        self.setGeometry(self._screen_geometry)

    def selected_draft(self) -> ScreenRegionDraft:
        if self._draft is None:
            raise RuntimeError("No screen region has been confirmed")
        return self._draft

    @property
    def error_message(self) -> str:
        return self._error_message

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(self.rect(), self._background)

        theme = ThemeManager.instance().current
        scrim = _shadow_color(theme.shadow_medium, theme.text)
        scrim.setAlpha(150)
        painter.fillRect(self.rect(), scrim)

        selection = self._normalized_selection()
        if not selection.isEmpty():
            scale_x = self._background.width() / max(1, self.width())
            scale_y = self._background.height() / max(1, self.height())
            source = QRect(
                round(selection.x() * scale_x),
                round(selection.y() * scale_y),
                round(selection.width() * scale_x),
                round(selection.height() * scale_y),
            )
            painter.drawPixmap(selection, self._background, source)
            painter.setPen(QPen(QColor(theme.primary), 3))
            painter.drawRoundedRect(selection.adjusted(1, 1, -1, -1), 8, 8)
            self._draw_selection_size(painter, selection)

        self._draw_instruction(painter)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.reject()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._start = event.position().toPoint()
        self._selection = QRect(self._start, self._start)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._start is None:
            return
        self._selection = QRect(self._start, event.position().toPoint()).normalized()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._selection = QRect(self._start, event.position().toPoint()).normalized()
        self._start = None
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._normalized_selection().contains(
            event.position().toPoint()
        ):
            self._confirm_selection()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self._confirm_selection()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self._background = QPixmap()
        super().closeEvent(event)

    def _confirm_selection(self) -> None:
        selection = self._normalized_selection()
        if not self._selection_is_valid(selection):
            return
        scale_x = self._background.width() / max(1, self.width())
        scale_y = self._background.height() / max(1, self.height())
        source = QRect(
            round(selection.x() * scale_x),
            round(selection.y() * scale_y),
            round(selection.width() * scale_x),
            round(selection.height() * scale_y),
        ).intersected(self._background.rect())
        cropped = self._background.copy(source)
        template = str(Path(QDir.tempPath()) / "lobuddy-region-draft-XXXXXX.png")
        # Keep the QFile wrapper local. Parenting it to the dialog can retain a
        # Windows file handle after close(), blocking immediate secure adoption.
        temporary = QTemporaryFile(template)
        temporary.setAutoRemove(False)
        if not temporary.open():
            self._error_message = "无法创建临时屏幕选区文件"
            self.reject()
            return
        path = Path(temporary.fileName())
        temporary.close()
        if not cropped.save(str(path), "PNG"):
            path.unlink(missing_ok=True)
            self._error_message = "无法保存临时屏幕选区"
            self.reject()
            return
        self._draft = ScreenRegionDraft(
            path=path,
            bounds=ScreenRegionBounds(
                x=self._screen_geometry.x() + selection.x(),
                y=self._screen_geometry.y() + selection.y(),
                width=selection.width(),
                height=selection.height(),
            ),
            screen_name=self._screen_name,
        )
        self.accept()

    def _normalized_selection(self) -> QRect:
        return self._selection.normalized().intersected(self.rect())

    def _selection_is_valid(self, selection: QRect) -> bool:
        return selection.width() >= self._minimum_size and selection.height() >= self._minimum_size

    def _draw_instruction(self, painter: QPainter) -> None:
        theme = ThemeManager.instance().current
        width = min(590, max(300, self.width() - 48))
        box = QRect((self.width() - width) // 2, 24, width, 68)
        surface = QColor(theme.surface)
        surface.setAlpha(242)
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.setBrush(surface)
        painter.drawRoundedRect(box, theme.radius_md, theme.radius_md)

        painter.setPen(QColor(theme.text))
        painter.setFont(QFont("Microsoft YaHei UI", 12, QFont.Weight.DemiBold))
        painter.drawText(
            box.adjusted(16, 9, -16, -32),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "框选你想让 Lobuddy 看见的区域",
        )
        painter.setPen(QColor(theme.text_secondary))
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        hint = (
            "拖动重新选择 · Enter 确认 · Esc / 右键取消"
            if self._selection_is_valid(self._normalized_selection())
            else "按住鼠标拖动；只会发送你框选的部分"
        )
        painter.drawText(
            box.adjusted(16, 34, -16, -8),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            hint,
        )

    def _draw_selection_size(self, painter: QPainter, selection: QRect) -> None:
        theme = ThemeManager.instance().current
        label = f"{selection.width()} × {selection.height()}"
        box_width = max(94, 14 + len(label) * 8)
        top = (
            selection.bottom() + 10
            if selection.bottom() + 42 < self.height()
            else selection.top() - 38
        )
        box = QRect(selection.left(), max(100, top), box_width, 30)
        surface = QColor(theme.surface)
        surface.setAlpha(242)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(surface)
        painter.drawRoundedRect(box, theme.radius_sm, theme.radius_sm)
        painter.setPen(QColor(theme.primary))
        painter.setFont(QFont("Microsoft YaHei UI", 9, QFont.Weight.DemiBold))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)


def _shadow_color(value: str, fallback: str) -> QColor:
    """Read the RGB part of a theme shadow token for a functional scrim."""
    if value.startswith("rgba(") and value.endswith(")"):
        parts = [item.strip() for item in value[5:-1].split(",")]
        if len(parts) >= 3:
            try:
                return QColor(int(parts[0]), int(parts[1]), int(parts[2]))
            except ValueError:
                pass
    return QColor(fallback)
