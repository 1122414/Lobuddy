"""Tests for Focus Companion."""

import sys
from unittest.mock import MagicMock


class _QObject:
    """Minimal QObject stand-in for testing."""
    def __init__(self, *args, **kwargs):
        pass


class _Signal:
    """Minimal Signal stand-in for testing."""
    def __init__(self, *args, **kwargs):
        pass

    def connect(self, *args, **kwargs):
        pass

    def disconnect(self, *args, **kwargs):
        pass

    def emit(self, *args, **kwargs):
        pass


class _QTimer:
    """Minimal QTimer stand-in for testing."""
    def __init__(self, *args, **kwargs):
        self._interval = 0
        self._active = False
        self.timeout = _Signal()

    def setInterval(self, interval):
        self._interval = interval

    def start(self, *args, **kwargs):
        self._active = True

    def stop(self):
        self._active = False


_pyside_core = type(sys)("PySide6.QtCore")
_pyside_core.QObject = _QObject
_pyside_core.Signal = _Signal
_pyside_core.QTimer = _QTimer

_pyside = type(sys)("PySide6")
_pyside.QtCore = _pyside_core

sys.modules.setdefault("PySide6", _pyside)
sys.modules.setdefault("PySide6.QtCore", _pyside_core)

from core.focus.focus_companion import FocusCompanion, FocusSession, FocusState


class TestFocusSession:
    """Test FocusSession state transitions."""

    def test_initial_state(self):
        session = FocusSession()
        assert session.state == FocusState.IDLE

    def test_start_focus(self):
        session = FocusSession(focus_minutes=1)
        session.start_focus()
        assert session.state == FocusState.FOCUSING
        assert session.seconds_remaining > 0

    def test_start_focus_already_focusing_is_noop(self):
        session = FocusSession(focus_minutes=1)
        session.start_focus()
        first_remaining = session.seconds_remaining
        session.start_focus()
        assert session.seconds_remaining == first_remaining

    def test_stop(self):
        session = FocusSession()
        session.start_focus()
        session.stop()
        assert session.state == FocusState.STOPPED

    def test_reset(self):
        session = FocusSession()
        session.start_focus()
        session.reset()
        assert session.state == FocusState.IDLE

    def test_start_break_only_after_completed(self):
        session = FocusSession(focus_minutes=1, break_minutes=1)
        session.start_break()
        assert session.state == FocusState.IDLE

    def test_seconds_remaining_zero_when_idle(self):
        session = FocusSession()
        assert session.seconds_remaining == 0

    def test_focus_break_minutes_properties(self):
        session = FocusSession(focus_minutes=30, break_minutes=10)
        assert session.focus_minutes == 30
        assert session.break_minutes == 10


class TestFocusCompanion:
    """Test FocusCompanion manager."""

    def test_start_focus(self):
        settings = MagicMock()
        settings.focus_default_minutes = 25
        settings.focus_break_minutes = 5
        settings.focus_auto_loop = False

        companion = FocusCompanion(settings)
        session = companion.start_focus()

        assert companion.is_active
        assert session.state == FocusState.FOCUSING

    def test_stop(self):
        settings = MagicMock()
        settings.focus_default_minutes = 25
        settings.focus_break_minutes = 5

        companion = FocusCompanion(settings)
        companion.start_focus()
        companion.stop()

        assert not companion.is_active
        assert companion.current_session is None

    def test_custom_duration(self):
        settings = MagicMock()
        settings.focus_default_minutes = 25
        settings.focus_break_minutes = 5

        companion = FocusCompanion(settings)
        session = companion.start_focus(minutes=10)

        assert session.focus_minutes == 10

    def test_is_active_false_when_idle(self):
        settings = MagicMock()
        settings.focus_default_minutes = 25
        settings.focus_break_minutes = 5

        companion = FocusCompanion(settings)
        assert not companion.is_active

    def test_start_focus_stops_previous(self):
        settings = MagicMock()
        settings.focus_default_minutes = 25
        settings.focus_break_minutes = 5

        companion = FocusCompanion(settings)
        companion.start_focus()
        assert companion.is_active
        companion.start_focus(minutes=10)
        assert companion.is_active
        assert companion.current_session.focus_minutes == 10

    def test_stop_when_no_session(self):
        settings = MagicMock()
        companion = FocusCompanion(settings)
        companion.stop()
        assert not companion.is_active
