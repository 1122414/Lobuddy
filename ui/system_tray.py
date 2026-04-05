"""System tray for Lobuddy."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu

from ui.asset_manager import AssetManager


class SystemTray(QObject):
    """System tray icon and menu."""

    show_requested = Signal()
    settings_requested = Signal()
    about_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._asset_manager = AssetManager()
        self._init_tray()

    def _init_tray(self):
        """Initialize system tray icon."""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self._asset_manager.get_tray_icon())
        self.tray_icon.setToolTip("Lobuddy - AI Desktop Pet")

        self._create_menu()
        self.tray_icon.activated.connect(self._on_activated)

    def _create_menu(self):
        """Create context menu."""
        self.menu = QMenu()

        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show_requested.emit)
        self.menu.addAction(show_action)

        self.menu.addSeparator()

        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.settings_requested.emit)
        self.menu.addAction(settings_action)

        about_action = QAction("About", self)
        about_action.triggered.connect(self.about_requested.emit)
        self.menu.addAction(about_action)

        self.menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.exit_requested.emit)
        self.menu.addAction(exit_action)

        self.tray_icon.setContextMenu(self.menu)

    def _on_activated(self, reason):
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_requested.emit()

    def show(self):
        """Show tray icon."""
        self.tray_icon.show()

    def hide(self):
        """Hide tray icon."""
        self.tray_icon.hide()

    def show_message(self, title: str, message: str, duration_ms: int = 3000):
        """Show tray notification."""
        self.tray_icon.showMessage(
            title, message, QSystemTrayIcon.MessageIcon.Information, duration_ms
        )
