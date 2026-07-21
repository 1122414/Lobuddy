"""Observation adapters for privacy-preserving system presence."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Protocol

from core.companion.models import ActivityCategory, ObservationSnapshot

logger = logging.getLogger(__name__)

_APP_CATEGORIES: dict[ActivityCategory, set[str]] = {
    ActivityCategory.DEVELOPMENT: {
        "code",
        "codium",
        "devenv",
        "idea64",
        "pycharm64",
        "webstorm64",
        "rider64",
        "windowsterminal",
        "powershell",
        "pwsh",
        "cmd",
    },
    ActivityCategory.COMMUNICATION: {
        "teams",
        "slack",
        "wechat",
        "weixin",
        "qq",
        "dingtalk",
        "zoom",
        "telegram",
        "discord",
    },
    ActivityCategory.BROWSER: {
        "chrome",
        "msedge",
        "firefox",
        "brave",
        "opera",
        "vivaldi",
    },
    ActivityCategory.PRODUCTIVITY: {
        "winword",
        "excel",
        "powerpnt",
        "onenote",
        "notion",
        "obsidian",
        "acrobat",
    },
    ActivityCategory.MEDIA: {
        "spotify",
        "vlc",
        "potplayer",
        "wmplayer",
        "music",
    },
    ActivityCategory.SYSTEM: {
        "explorer",
        "taskmgr",
        "systemsettings",
        "control",
    },
}


class ObservationAdapter(Protocol):
    """Seam for operating-system observation implementations."""

    def observe(self) -> ObservationSnapshot: ...


def classify_application(executable_name: str) -> ActivityCategory:
    normalized = Path(executable_name).stem.lower().strip()
    for category, names in _APP_CATEGORIES.items():
        if normalized in names:
            return category
    return ActivityCategory.UNKNOWN


class NullObservationAdapter:
    """Cross-platform adapter used when system observation is unavailable."""

    def observe(self) -> ObservationSnapshot:
        return ObservationSnapshot(available=False)


class WindowsObservationAdapter:
    """Windows adapter using documented user32/kernel32 calls.

    It reads only last-input time and the foreground process executable name.
    Window titles, keyboard input, and screen pixels are intentionally excluded.
    """

    def observe(self) -> ObservationSnapshot:
        try:
            idle_seconds = self._read_idle_seconds()
            foreground_app = self._read_foreground_executable()
            return ObservationSnapshot(
                available=True,
                idle_seconds=idle_seconds,
                foreground_app=foreground_app,
                activity_category=classify_application(foreground_app),
            )
        except Exception as exc:
            logger.debug("Windows observation unavailable: %s", exc)
            return ObservationSnapshot(available=False)

    @staticmethod
    def _read_idle_seconds() -> float:
        import ctypes
        from ctypes import wintypes

        class LastInputInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        info = LastInputInfo()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        current_tick = kernel32.GetTickCount64()
        elapsed_ms = (current_tick - info.dwTime) & 0xFFFFFFFF
        return max(0.0, elapsed_ms / 1000.0)

    @staticmethod
    def _read_foreground_executable() -> str:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        kernel32.OpenProcess.restype = wintypes.HANDLE

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if not process_id.value:
            return ""

        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            process_id.value,
        )
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(
                handle,
                0,
                buffer,
                ctypes.byref(size),
            ):
                return ""
            return Path(buffer.value).stem.lower()
        finally:
            kernel32.CloseHandle(handle)


def create_system_observation_adapter() -> ObservationAdapter:
    if sys.platform == "win32":
        return WindowsObservationAdapter()
    return NullObservationAdapter()
