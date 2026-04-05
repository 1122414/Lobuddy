"""Global hotkey manager for Lobuddy."""

from PySide6.QtCore import QObject, QThread, Signal


class HotkeyWorker(QThread):
    """Worker thread for global hotkey."""

    activated = Signal()

    def __init__(self):
        super().__init__()
        self._running = False
        self._listener = None

    def run(self):
        """Run hotkey listener."""
        try:
            from pynput import keyboard

            self._running = True

            def on_activate():
                self.activated.emit()

            # Ctrl+Shift+L
            hotkey = keyboard.HotKey(keyboard.HotKey.parse("<ctrl>+<shift>+l"), on_activate)

            with keyboard.Listener(
                on_press=hotkey.press, on_release=hotkey.release
            ) as self._listener:
                self._listener.join()

        except ImportError:
            pass
        except Exception:
            pass

    def stop(self):
        """Stop hotkey listener."""
        self._running = False
        if self._listener:
            self._listener.stop()


class HotkeyManager(QObject):
    """Global hotkey manager (Ctrl+Shift+L)."""

    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._available = False

    def start(self):
        """Start hotkey listener."""
        try:
            import pynput

            self._worker = HotkeyWorker()
            self._worker.activated.connect(self.activated.emit)
            self._worker.start()
            self._available = True
        except ImportError:
            self._available = False

    def stop(self):
        """Stop hotkey listener."""
        if self._worker:
            self._worker.stop()
            self._worker.wait(1000)

    def is_available(self) -> bool:
        """Check if hotkey is available."""
        return self._available
