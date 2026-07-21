"""Operating-system adapters for bounded desktop observation and input."""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
from pathlib import Path
from typing import Protocol

from core.computer_use.models import (
    ComputerAction,
    ComputerActionType,
    ComputerSemanticSnapshot,
    ComputerTarget,
    ComputerTargetSource,
)


class DesktopAdapter(Protocol):
    """Seam between the computer-use domain and platform input APIs."""

    def is_available(self) -> bool: ...

    def screen_size(self) -> tuple[int, int]: ...

    def capture_screen(self) -> Path: ...

    def inspect_semantics(self) -> ComputerSemanticSnapshot: ...

    def execute_action(self, action: ComputerAction) -> str: ...


class NullDesktopAdapter:
    def is_available(self) -> bool:
        return False

    def screen_size(self) -> tuple[int, int]:
        return (0, 0)

    def capture_screen(self) -> Path:
        raise RuntimeError("Computer Use is unavailable on this platform")

    def inspect_semantics(self) -> ComputerSemanticSnapshot:
        return ComputerSemanticSnapshot()

    def execute_action(self, action: ComputerAction) -> str:
        raise RuntimeError("Computer Use is unavailable on this platform")


class WindowsDesktopAdapter:
    """Windows Implementation using Pillow capture, pynput input, and Unicode SendInput."""

    def __init__(self, action_delay_ms: int = 250) -> None:
        self._action_delay_seconds = max(0, action_delay_ms) / 1000

    def is_available(self) -> bool:
        return sys.platform == "win32"

    def screen_size(self) -> tuple[int, int]:
        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))

    def capture_screen(self) -> Path:
        if not self.is_available():
            raise RuntimeError("Computer Use is unavailable on this platform")
        from PIL import ImageGrab

        fd, raw_path = tempfile.mkstemp(prefix="lobuddy-screen-", suffix=".png")
        os.close(fd)
        path = Path(raw_path)
        try:
            ImageGrab.grab(all_screens=False).save(path, format="PNG")
            return path
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def inspect_semantics(self) -> ComputerSemanticSnapshot:
        """Read visible Win32 control metadata without reading text-field values."""
        if not self.is_available():
            return ComputerSemanticSnapshot()

        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetWindowRect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        ]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        foreground = user32.GetForegroundWindow()
        if not foreground:
            return ComputerSemanticSnapshot()

        foreground_app = self._window_text(user32, foreground)
        screen_width, screen_height = self.screen_size()
        targets: list[ComputerTarget] = []

        def append_target(hwnd) -> None:
            if len(targets) >= 60 or not user32.IsWindowVisible(hwnd):
                return
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            if width <= 2 or height <= 2:
                return
            x = int(rect.left)
            y = int(rect.top)
            if x < 0 or y < 0 or x >= screen_width or y >= screen_height:
                return

            class_name = self._window_class(user32, hwnd)
            role = self._control_role(class_name)
            label = self._control_label(user32, hwnd, class_name)
            if not label and role in {"window", "label"}:
                return
            targets.append(
                ComputerTarget(
                    id=f"native-{len(targets) + 1}",
                    label=label[:200],
                    role=role,
                    x=x,
                    y=y,
                    width=min(width, screen_width - x),
                    height=min(height, screen_height - y),
                    confidence=0.92,
                    source=ComputerTargetSource.NATIVE_CONTROL,
                )
            )

        append_target(foreground)
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )
        user32.EnumChildWindows.argtypes = [
            wintypes.HWND,
            callback_type,
            wintypes.LPARAM,
        ]
        user32.EnumChildWindows.restype = wintypes.BOOL

        @callback_type
        def enum_child(hwnd, _lparam):
            append_target(hwnd)
            return True

        user32.EnumChildWindows(foreground, enum_child, 0)
        return ComputerSemanticSnapshot(
            foreground_app=foreground_app[:200],
            targets=targets,
        )

    def execute_action(self, action: ComputerAction) -> str:
        if not self.is_available():
            raise RuntimeError("Computer Use is unavailable on this platform")

        from pynput.keyboard import Controller as KeyboardController
        from pynput.keyboard import Key
        from pynput.mouse import Button, Controller as MouseController

        mouse = MouseController()
        keyboard = KeyboardController()

        if action.action == ComputerActionType.MOVE:
            mouse.position = (action.x, action.y)
        elif action.action == ComputerActionType.CLICK:
            mouse.position = (action.x, action.y)
            mouse.click(Button.left, 1)
        elif action.action == ComputerActionType.DOUBLE_CLICK:
            mouse.position = (action.x, action.y)
            mouse.click(Button.left, 2)
        elif action.action == ComputerActionType.SCROLL:
            mouse.scroll(0, action.scroll_delta)
        elif action.action == ComputerActionType.TYPE_TEXT:
            self._send_unicode_text(action.text)
        elif action.action == ComputerActionType.PRESS_KEY:
            keyboard.press(self._keyboard_key(action.key, Key))
            keyboard.release(self._keyboard_key(action.key, Key))
        elif action.action == ComputerActionType.HOTKEY:
            keys = [self._keyboard_key(item, Key) for item in action.hotkey]
            for key in keys:
                keyboard.press(key)
            for key in reversed(keys):
                keyboard.release(key)
        else:
            raise ValueError(f"Unsupported action: {action.action}")

        if self._action_delay_seconds:
            import time

            time.sleep(self._action_delay_seconds)
        return "action_executed"

    @staticmethod
    def _keyboard_key(raw: str, key_enum):
        normalized = raw.lower().strip()
        aliases = {
            "alt": key_enum.alt,
            "backspace": key_enum.backspace,
            "ctrl": key_enum.ctrl,
            "delete": key_enum.delete,
            "down": key_enum.down,
            "end": key_enum.end,
            "enter": key_enum.enter,
            "esc": key_enum.esc,
            "home": key_enum.home,
            "left": key_enum.left,
            "page_down": key_enum.page_down,
            "page_up": key_enum.page_up,
            "right": key_enum.right,
            "shift": key_enum.shift,
            "space": key_enum.space,
            "tab": key_enum.tab,
            "up": key_enum.up,
        }
        if normalized in aliases:
            return aliases[normalized]
        if len(normalized) == 1:
            return normalized
        raise ValueError(f"Unsupported key: {raw}")

    @staticmethod
    def _send_unicode_text(text: str) -> None:
        """Type Unicode without using or overwriting the user's clipboard."""
        from ctypes import wintypes

        input_keyboard = 1
        keyeventf_keyup = 0x0002
        keyeventf_unicode = 0x0004

        class KeyboardInput(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t),
            ]

        class InputUnion(ctypes.Union):
            _fields_ = [("ki", KeyboardInput)]

        class Input(ctypes.Structure):
            _anonymous_ = ("union",)
            _fields_ = [("type", wintypes.DWORD), ("union", InputUnion)]

        utf16 = text.encode("utf-16-le")
        inputs: list[Input] = []
        for index in range(0, len(utf16), 2):
            scan_code = int.from_bytes(utf16[index : index + 2], "little")
            inputs.extend(
                [
                    Input(
                        type=input_keyboard,
                        ki=KeyboardInput(
                            0,
                            scan_code,
                            keyeventf_unicode,
                            0,
                            0,
                        ),
                    ),
                    Input(
                        type=input_keyboard,
                        ki=KeyboardInput(
                            0,
                            scan_code,
                            keyeventf_unicode | keyeventf_keyup,
                            0,
                            0,
                        ),
                    ),
                ]
            )
        if not inputs:
            return
        array_type = Input * len(inputs)
        sent = ctypes.windll.user32.SendInput(
            len(inputs),
            array_type(*inputs),
            ctypes.sizeof(Input),
        )
        if sent != len(inputs):
            raise ctypes.WinError()

    @staticmethod
    def _window_text(user32, hwnd) -> str:
        length = int(user32.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(min(length, 500) + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value.strip()

    @staticmethod
    def _window_class(user32, hwnd) -> str:
        buffer = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, buffer, len(buffer))
        return buffer.value.strip()

    @staticmethod
    def _control_role(class_name: str) -> str:
        lowered = class_name.lower()
        role_prefixes = (
            ("button", "button"),
            ("edit", "text field"),
            ("richedit", "text field"),
            ("scintilla", "text editor"),
            ("combobox", "combo box"),
            ("listbox", "list"),
            ("syslistview", "list"),
            ("systreeview", "tree"),
            ("systabcontrol", "tab"),
            ("toolbarwindow", "toolbar"),
            ("scrollbar", "scroll bar"),
            ("static", "label"),
        )
        for prefix, role in role_prefixes:
            if lowered.startswith(prefix):
                return role
        return "window" if not lowered else f"control:{class_name[:40]}"

    @classmethod
    def _control_label(cls, user32, hwnd, class_name: str) -> str:
        lowered = class_name.lower()
        if lowered.startswith(("edit", "richedit", "scintilla")):
            return ""
        return cls._window_text(user32, hwnd)


def create_desktop_adapter(action_delay_ms: int = 250) -> DesktopAdapter:
    if sys.platform == "win32":
        return WindowsDesktopAdapter(action_delay_ms=action_delay_ms)
    return NullDesktopAdapter()
