import json
import os
import subprocess
import sys
import tempfile
import time


def test_process_with_active_subagent_can_exit():
    script = {"responses": [{"__sleep": 30}]}
    fd, script_path = tempfile.mkstemp(suffix=".json", text=True)
    with os.fdopen(fd, "w") as f:
        json.dump(script, f)

    code = f"""
import asyncio
import multiprocessing as mp
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["LOBUDDY_SUBAGENT_TEST_SCRIPT"] = {repr(script_path)}

from app.config import Settings
from core.agent.subagent_factory import SubagentFactory

settings = Settings(
    llm_api_key="test-key",
    llm_base_url="https://api.openai.com/v1",
    llm_model="kimi-2.5",
    llm_multimodal_model="qwen3.5-omni-plus",
    workspace_path=Path(tempfile.mkdtemp()),
    task_timeout=60,
    nanobot_max_iterations=5,
)
factory = SubagentFactory(settings)

started = threading.Event()
_original_start = mp.Process.start

def _patched_start(self):
    _original_start(self)
    started.set()

mp.Process.start = _patched_start

async def run():
    await factory.run_subagent("image_analysis", "hang", media_paths=[])

thread = threading.Thread(target=lambda: asyncio.run(run()), daemon=True)
thread.start()
assert started.wait(timeout=5), "Subagent process did not start in time"
time.sleep(0.5)
sys.exit(0)
"""

    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        proc.wait(timeout=5)
        stderr = proc.stderr.read() if proc.stderr else ""
        assert proc.returncode == 0, f"Child exited with code {proc.returncode}. stderr: {stderr}"
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        raise AssertionError("Process with active subagent did not exit within 5 seconds")
    finally:
        os.unlink(script_path)


def test_tray_exit_terminates_process_with_active_hotkey():
    code = """
import sys
import threading
import time
import types

keyboard_mod = types.ModuleType("pynput.keyboard")

class FakeHotKey:
    def __init__(self, combo, callback):
        self.callback = callback
        self._keys = []
    def press(self, key):
        pass
    def release(self, key):
        pass
    @staticmethod
    def parse(x):
        return x

keyboard_mod.HotKey = FakeHotKey

class FakeListener:
    def __init__(self, on_press=None, on_release=None):
        self._stopped = False
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def stop(self):
        self._stopped = True
    def join(self, timeout=None):
        if timeout is not None:
            end = time.time() + timeout
            while not self._stopped and time.time() < end:
                time.sleep(0.05)
            return
        while not self._stopped:
            time.sleep(0.05)
    def is_alive(self):
        return not self._stopped

keyboard_mod.Listener = FakeListener

pynput_mod = types.ModuleType("pynput")
pynput_mod.keyboard = keyboard_mod
sys.modules["pynput"] = pynput_mod
sys.modules["pynput.keyboard"] = keyboard_mod

qtcore_mod = types.ModuleType("PySide6.QtCore")

class FakeQObject:
    def __init__(self, parent=None):
        self._slots = []
    def __setattr__(self, name, value):
        super().__setattr__(name, value)

class FakeSignal:
    def __init__(self):
        self._slots = []
    def connect(self, slot):
        self._slots.append(slot)
    def emit(self, *args):
        for slot in self._slots:
            slot(*args)

class FakeQThread:
    def __init__(self):
        self._thread = None
        self._running = False
    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
    def run(self):
        pass
    def isRunning(self):
        return self._running and (self._thread is not None and self._thread.is_alive())
    def wait(self, ms):
        if self._thread:
            self._thread.join(timeout=ms / 1000.0)
        return not self.isRunning()
    def terminate(self):
        self._running = False

qtcore_mod.QObject = FakeQObject
qtcore_mod.Signal = FakeSignal
qtcore_mod.QThread = FakeQThread
sys.modules["PySide6.QtCore"] = qtcore_mod

from ui.hotkey_manager import HotkeyManager

hotkey = HotkeyManager()
hotkey.start()
assert hotkey._worker is not None
assert hotkey._worker.isRunning(), "Worker thread should be running"

time.sleep(0.5)
stopped = hotkey.stop()
assert stopped is True, "Hotkey manager did not stop cleanly"
"""

    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        proc.wait(timeout=5)
        stderr = proc.stderr.read() if proc.stderr else ""
        assert proc.returncode == 0, f"Child exited with code {proc.returncode}. stderr: {stderr}"
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        raise AssertionError("Process did not exit after tray quit simulation")


def test_system_tray_exit_signal_closes_application():
    code = r"""
import sys
import threading
import time
import types

sys.path.insert(0, r"E:\GitHub\Repositories\Lobuddy")

qtcore_mod = types.ModuleType("PySide6.QtCore")

class FakeQObject:
    def __init__(self, parent=None):
        pass

class FakeSignal:
    def __init__(self):
        self._slots = []
    def connect(self, slot):
        self._slots.append(slot)
    def emit(self, *args):
        for slot in self._slots:
            slot(*args)

qtcore_mod.QObject = FakeQObject
qtcore_mod.Signal = FakeSignal
sys.modules["PySide6.QtCore"] = qtcore_mod

qtgui_mod = types.ModuleType("PySide6.QtGui")

class FakeQAction:
    def __init__(self, text, parent=None):
        self.triggered = FakeSignal()
        self.text = text

class FakeQMovie:
    def __init__(self, path):
        self._path = path
        self._started = False
    def setParent(self, parent):
        pass
    def frameChanged(self):
        return FakeSignal()
    def start(self):
        self._started = True

qtgui_mod.QAction = FakeQAction
qtgui_mod.QIcon = lambda: None
qtgui_mod.QMovie = FakeQMovie
sys.modules["PySide6.QtGui"] = qtgui_mod

qtwidgets_mod = types.ModuleType("PySide6.QtWidgets")

class FakeQApp:
    def __init__(self, argv):
        self._running = False
    def setQuitOnLastWindowClosed(self, val):
        pass
    def closeAllWindows(self):
        pass
    def quit(self):
        self._running = False
    def exec(self):
        self._running = True
        while self._running:
            time.sleep(0.05)

class FakeTray:
    activated = FakeSignal()
    def __init__(self, parent=None):
        self.menu = None
    def setIcon(self, icon):
        pass
    def setToolTip(self, tip):
        pass
    def setContextMenu(self, menu):
        pass
    def show(self):
        pass
    def showMessage(self, *args, **kwargs):
        pass

class FakeMenu:
    def __init__(self):
        self.actions = []
    def addAction(self, action):
        self.actions.append(action)
    def addSeparator(self):
        pass

qtwidgets_mod.QApplication = FakeQApp
qtwidgets_mod.QSystemTrayIcon = FakeTray
qtwidgets_mod.QMenu = FakeMenu
sys.modules["PySide6.QtWidgets"] = qtwidgets_mod

asset_mod = types.ModuleType("ui.asset_manager")
class FakeAssetManager:
    def get_tray_icon(self):
        return None
    def get_tray_movie(self):
        return None
asset_mod.AssetManager = FakeAssetManager
sys.modules["ui.asset_manager"] = asset_mod

ui_pkg = types.ModuleType("ui")
ui_pkg.__path__ = [r"E:\GitHub\Repositories\Lobuddy\ui"]
sys.modules["ui"] = ui_pkg

from ui.system_tray import SystemTray

app = FakeQApp([])
tray = SystemTray()
tray.show()

quit_called = threading.Event()
original_quit = app.quit
def tracked_quit():
    quit_called.set()
    original_quit()

tray.exit_requested.connect(tracked_quit)

exit_action = None
for action in tray.menu.actions:
    if action.text == "Exit":
        exit_action = action
        break
assert exit_action is not None, "Exit action not found in menu"

def emit_exit():
    exit_action.triggered.emit(True)

exit_thread = threading.Thread(target=emit_exit, daemon=True)
exit_thread.start()

assert quit_called.wait(timeout=5), "quit() was not called within 5 seconds"
exit_thread.join(timeout=2)
"""

    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        proc.wait(timeout=10)
        stderr = proc.stderr.read() if proc.stderr else ""
        assert proc.returncode == 0, f"Child exited with code {proc.returncode}. stderr: {stderr}"
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        raise AssertionError("Process did not exit after SystemTray exit simulation")


for _mod in list(sys.modules.keys()):
    if _mod.startswith(('PySide6', 'ui', 'pynput')):
        del sys.modules[_mod]

