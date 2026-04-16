"""Global hotkey manager for Lobuddy."""

from PySide6.QtCore import QObject, QThread, Signal


class HotkeyWorker(QThread):
    """Worker thread for global hotkey."""

    activated = Signal()

    def __init__(self):
        super().__init__()
        self._running = False
        self._listener = None
        self._should_stop = False

    def run(self):
        """Run hotkey listener."""
        try:
            from pynput import keyboard

            self._running = True

            if self._should_stop:
                return

            def on_activate():
                self.activated.emit()

            # Ctrl+Shift+L
            hotkey = keyboard.HotKey(keyboard.HotKey.parse("<ctrl>+<shift>+l"), on_activate)

            with keyboard.Listener(
                on_press=hotkey.press, on_release=hotkey.release
            ) as self._listener:
                if self._should_stop:
                    return
                while not self._should_stop and self._listener.is_alive():
                    self._listener.join(timeout=0.1)

        except ImportError:
            pass
        except Exception:
            pass

    def stop(self):
        """Stop hotkey listener."""
        self._running = False
        self._should_stop = True
        if self._listener:
            self._listener.stop()

    def force_stop(self) -> bool:
        """Force stop the thread if graceful stop fails."""
        self.stop()
        if self.isRunning():
            self.terminate()
            self.wait(500)
        return not self.isRunning()


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

    def stop(self) -> bool:
        """Stop hotkey listener. Returns True if stopped cleanly, False otherwise."""
        if self._worker:
            self._worker.stop()
            stopped = self._worker.wait(3000)
            if not stopped:
                stopped = self._worker.force_stop()
            self._worker = None
            return stopped
        return True

    def is_available(self) -> bool:
        """Check if hotkey is available."""
        return self._available
