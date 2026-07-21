"""UI smoke tests for Lobuddy components.

Tests verify construction and basic functionality of main UI widgets under
headless PySide6 mocks. Uses sys.modules injection (Pattern A from AGENTS.md).

Rules:
- No real display, no blocking dialogs
- sys.modules injection for PySide6 mocking
- Class-grouped tests
- All fixtures local (no conftest.py)
"""

import asyncio
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

# ────────────────────────────────────────────────────────────────────────
# Stand-in base classes with metaclass-level namespace support
# Qt classes like QFrame double as constructors AND namespaces for enums
# (e.g. QFrame.Shape.StyledPanel). Instance __getattr__ handles the former;
# metaclass __getattr__ handles the latter.
# ────────────────────────────────────────────────────────────────────────


class _MockMeta(type):
    """Metaclass: __getattr__ on the CLASS returns MagicMock (for namespace access)."""

    def __getattr__(cls, name):
        return MagicMock()


class _MockQObject(metaclass=_MockMeta):
    """Stand-in for QObject. Instance __getattr__ handles arbitrary method calls."""

    def __init__(self, parent=None):
        pass

    def __getattr__(self, name):
        return MagicMock()


class _MockQDialog(_MockQObject):
    pass


class _MockQMainWindow(_MockQObject):
    pass


class _MockQWidget(_MockQObject):
    pass


class _MockQFrame(_MockQWidget):
    pass


# ────────────────────────────────────────────────────────────────────────
# Widget constructor + namespace mock
# Qt classes serve dual roles: constructor (QLabel(parent)) and namespace
# for enums/constants (QFont.Weight.Bold, QHeaderView.ResizeMode.Stretch).
# Also used in type hints (QMovie | None) which are evaluated eagerly.
# ────────────────────────────────────────────────────────────────────────


class _QtMock:
    """Callable that also supports attribute access and | operator."""

    def __call__(self, *args, **kwargs):
        return MagicMock()

    def __getattr__(self, name):
        return MagicMock()

    def __or__(self, other):
        return MagicMock()

    def __ror__(self, other):
        return MagicMock()


_mock_qt = _QtMock()


# ────────────────────────────────────────────────────────────────────────
# PySide6 module mock
# ────────────────────────────────────────────────────────────────────────


@contextmanager
def _mock_pyside_for_import():
    """Inject mock PySide6 into sys.modules for headless test runs."""
    _pyside = MagicMock()

    # QtCore
    _pyside.QtCore = MagicMock()
    _pyside.QtCore.Qt = MagicMock()
    _pyside.QtCore.Signal = MagicMock(return_value=MagicMock())
    _pyside.QtCore.Slot = MagicMock(return_value=lambda fn: fn)
    _pyside.QtCore.QObject = _MockQObject
    _pyside.QtCore.QPropertyAnimation = _mock_qt
    _pyside.QtCore.QTimer = _mock_qt
    _pyside.QtCore.QEasingCurve = _mock_qt
    _pyside.QtCore.QSize = _mock_qt
    _pyside.QtCore.QPoint = _mock_qt
    _pyside.QtCore.QRect = _mock_qt

    # QtGui — use _mock_qt for everything (handles constructor + namespace + type hints)
    _pyside.QtGui = MagicMock()
    _pyside.QtGui.QFont = _mock_qt
    _pyside.QtGui.QMovie = _mock_qt
    _pyside.QtGui.QPixmap = _mock_qt
    _pyside.QtGui.QColor = _mock_qt
    _pyside.QtGui.QPen = _mock_qt
    _pyside.QtGui.QBrush = _mock_qt
    _pyside.QtGui.QPainter = _mock_qt
    _pyside.QtGui.QMouseEvent = _mock_qt
    _pyside.QtGui.QAction = _mock_qt
    _pyside.QtGui.QIcon = _mock_qt
    _pyside.QtGui.QGraphicsOpacityEffect = _mock_qt
    _pyside.QtGui.QGraphicsDropShadowEffect = _mock_qt

    # QtWidgets — base classes vs instantiable widgets
    _pyside.QtWidgets = MagicMock()
    _pyside.QtWidgets.QApplication = _mock_qt
    _pyside.QtWidgets.QDialog = _MockQDialog
    _pyside.QtWidgets.QMainWindow = _MockQMainWindow
    _pyside.QtWidgets.QWidget = _MockQWidget
    _pyside.QtWidgets.QFrame = _MockQFrame
    # Instantiable widgets / namespace classes use _mock_qt
    _pyside.QtWidgets.QLabel = _mock_qt
    _pyside.QtWidgets.QPushButton = _mock_qt
    _pyside.QtWidgets.QVBoxLayout = _mock_qt
    _pyside.QtWidgets.QHBoxLayout = _mock_qt
    _pyside.QtWidgets.QScrollArea = _mock_qt
    _pyside.QtWidgets.QLineEdit = _mock_qt
    _pyside.QtWidgets.QTextEdit = _mock_qt
    _pyside.QtWidgets.QProgressBar = _mock_qt
    _pyside.QtWidgets.QMenu = _mock_qt
    _pyside.QtWidgets.QFileDialog = _mock_qt
    _pyside.QtWidgets.QMessageBox = _mock_qt
    _pyside.QtWidgets.QSizeGrip = _mock_qt
    _pyside.QtWidgets.QTableWidget = _mock_qt
    _pyside.QtWidgets.QTableWidgetItem = _mock_qt
    _pyside.QtWidgets.QHeaderView = _mock_qt
    _pyside.QtWidgets.QCheckBox = _mock_qt
    _pyside.QtWidgets.QTabWidget = _mock_qt
    _pyside.QtWidgets.QToolTip = _mock_qt

    modules = {
        "PySide6": _pyside,
        "PySide6.QtCore": _pyside.QtCore,
        "PySide6.QtGui": _pyside.QtGui,
        "PySide6.QtWidgets": _pyside.QtWidgets,
    }
    with patch.dict(sys.modules, modules):
        yield


@pytest.fixture(scope="module")
def _with_pyside_mock():
    """Module-scoped PySide6 mock with UI module cleanup on teardown."""
    existing_ui_modules = {
        name: module
        for name, module in sys.modules.items()
        if name.startswith("ui.") or name == "ui"
    }
    for mod_name in existing_ui_modules:
        del sys.modules[mod_name]
    with _mock_pyside_for_import():
        yield
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("ui.") or mod_name == "ui":
            del sys.modules[mod_name]
    sys.modules.update(existing_ui_modules)


# ────────────────────────────────────────────────────────────────────────
# Helper factories
# ────────────────────────────────────────────────────────────────────────


def _make_mock_chat_repo():
    repo = MagicMock()
    repo.get_sessions.return_value = []
    repo.get_messages.return_value = []
    repo.create_session.return_value = "mock-session-id"
    return repo


def _make_mock_settings(**overrides):
    s = MagicMock()
    s.llm_api_key = "test-key"
    s.pet_click_feedback_enabled = True
    s.pet_clock_enabled = True
    s.chat_message_time_enabled = True
    s.conversation_timeline_enabled = True
    s.pet_state_enabled = True
    s.daily_greeting_enabled = False
    s.skill_panel_click_to_fill_input = False
    s.chat_time_divider_enabled = True
    s.chat_time_divider_gap_minutes = 5
    s.memory_console_show_sensitive_content = False
    s.memory_console_items_per_page = 20
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ============================================================================
# Test: TaskPanel construction
# ============================================================================


class TestTaskPanelConstruction:
    """Smoke tests for TaskPanel (QDialog) construction under PySide6 mock."""

    def test_constructs_without_error(self, _with_pyside_mock):
        with patch("ui.task_panel.MemoryRepository"):
            from ui.task_panel import TaskPanel

            chat_repo = _make_mock_chat_repo()
            panel = TaskPanel(chat_repo)
            assert panel is not None
            assert panel.chat_repo is chat_repo
            assert panel.current_session_id == "default"
            assert panel._skill_registry is not None

    def test_constructs_with_parent(self, _with_pyside_mock):
        with patch("ui.task_panel.MemoryRepository"):
            from ui.task_panel import TaskPanel

            parent = MagicMock()
            chat_repo = _make_mock_chat_repo()
            panel = TaskPanel(chat_repo, parent=parent)
            assert panel is not None

    def test_has_expected_signals(self, _with_pyside_mock):
        with patch("ui.task_panel.MemoryRepository"):
            from ui.task_panel import TaskPanel

            chat_repo = _make_mock_chat_repo()
            panel = TaskPanel(chat_repo)
            assert hasattr(panel, "task_submitted")
            assert hasattr(panel, "history_requested")
            assert hasattr(panel, "settings_requested")

    def test_initial_state_attributes(self, _with_pyside_mock):
        with patch("ui.task_panel.MemoryRepository"):
            from ui.task_panel import TaskPanel

            chat_repo = _make_mock_chat_repo()
            panel = TaskPanel(chat_repo)
            assert panel.messages == []
            assert panel._msg_data == []
            assert panel.drag_pos is None
            assert panel.current_image_path is None
            assert panel._settings is None
            assert panel._focus_active is False
            assert panel._skill_panel is None
            assert panel._mem_info_label is not None

    def test_is_dialog_subclass(self, _with_pyside_mock):
        with patch("ui.task_panel.MemoryRepository"):
            from ui.task_panel import TaskPanel

            assert TaskPanel.__mro__[1].__name__ == "_MockQDialog"


# ============================================================================
# Test: PetWindow construction
# ============================================================================


class TestPetWindowConstruction:
    """Smoke tests for PetWindow (QMainWindow) construction under PySide6 mock."""

    def test_constructs_without_error(self, _with_pyside_mock):
        from ui.pet_window import PetWindow

        window = PetWindow()
        assert window is not None

    def test_constructs_with_parent(self, _with_pyside_mock):
        from ui.pet_window import PetWindow

        parent = MagicMock()
        window = PetWindow(parent=parent)
        assert window is not None

    def test_has_expected_signals(self, _with_pyside_mock):
        from ui.pet_window import PetWindow

        window = PetWindow()
        expected_signals = [
            "task_requested",
            "settings_requested",
            "memory_console_requested",
            "close_requested",
            "chat_requested",
            "pet_settings_requested",
            "codex_pet_library_requested",
            "relationship_rhythm_requested",
            "click_feedback_changed",
            "companion_feedback_requested",
            "companion_check_in_requested",
            "focus_requested",
            "focus_stop_requested",
        ]
        for sig_name in expected_signals:
            assert hasattr(window, sig_name), f"Missing signal: {sig_name}"

    def test_initial_ui_children_present(self, _with_pyside_mock):
        from ui.pet_window import PetWindow

        window = PetWindow()
        assert hasattr(window, "pet_label")
        assert hasattr(window, "mood_label")
        assert hasattr(window, "name_label")
        assert hasattr(window, "level_label")
        assert hasattr(window, "exp_bar")
        assert hasattr(window, "central_widget")

    def test_speech_bubble_initialised(self, _with_pyside_mock):
        from ui.pet_window import PetWindow

        window = PetWindow()
        assert hasattr(window, "_speech_bubble")
        assert hasattr(window, "_speech_timer")
        assert hasattr(window, "_speech_anim")

    def test_is_mainwindow_subclass(self, _with_pyside_mock):
        from ui.pet_window import PetWindow

        assert PetWindow.__mro__[1].__name__ == "_MockQMainWindow"


# ============================================================================
# Test: QtHitlApprovalProvider trigger logic
# ============================================================================


class TestHitlApprovalProviderTrigger:
    """Tests for QtHitlApprovalProvider signal-based approval flow."""

    @pytest.fixture
    def provider(self, _with_pyside_mock):
        from ui.hitl_approval_provider import QtHitlApprovalProvider

        return QtHitlApprovalProvider()

    @pytest.fixture
    def sample_request(self):
        from core.safety.hitl_approval import HitlApprovalRequest

        return HitlApprovalRequest.create(
            session_id="test-session",
            tool_name="exec",
            command="rm temp.txt",
            working_dir="/tmp",
            reason="cleanup",
        )

    def test_has_approval_requested_signal(self, provider):
        assert hasattr(provider, "approval_requested")

    def test_pending_dict_initialised_empty(self, provider):
        assert provider._pending == {}

    def test_set_parent_window(self, provider):
        assert provider._parent_window is None
        mock_window = MagicMock()
        provider.set_parent_window(mock_window)
        assert provider._parent_window is mock_window

    def test_request_approval_emits_signal(self, provider, sample_request):
        from core.safety.hitl_approval import HitlApprovalDecision

        fake_decision = HitlApprovalDecision.approved_now(sample_request.request_id, "test")

        async def _fake_wrap(fut):
            return fake_decision

        async def _run():
            with patch("asyncio.wrap_future", side_effect=_fake_wrap):
                decision = await provider.request_approval(sample_request)
                return decision

        decision = asyncio.run(_run())
        assert decision.approved is True
        provider.approval_requested.emit.assert_called_once_with(sample_request)

    def test_request_approval_stores_in_pending(self, provider, sample_request):
        from core.safety.hitl_approval import HitlApprovalDecision

        fake_decision = HitlApprovalDecision.approved_now(sample_request.request_id, "test")

        async def _fake_wrap(fut):
            return fake_decision

        async def _run():
            with patch("asyncio.wrap_future", side_effect=_fake_wrap):
                return await provider.request_approval(sample_request)

        asyncio.run(_run())
        assert sample_request.request_id not in provider._pending

    def test_request_approval_rejects_on_failure(self, provider, sample_request):
        async def _run():
            with patch("asyncio.wrap_future", side_effect=RuntimeError("boom")):
                decision = await provider.request_approval(sample_request)
                return decision

        decision = asyncio.run(_run())
        assert decision.approved is False
        assert "HITL approval failed" in decision.reason
        assert sample_request.request_id not in provider._pending


# ============================================================================
# Test: SkillPanel construction
# ============================================================================


class TestSkillPanelConstruction:
    """Smoke tests for SkillPanel (QDialog) construction under PySide6 mock."""

    @pytest.fixture
    def mock_registry(self):
        from core.skills.skill_registry import SkillDefinition, SkillRegistry

        registry = SkillRegistry()
        registry._skills = {}
        registry.register(
            SkillDefinition(
                id="chat",
                name="Chat",
                description="Natural language conversation with AI",
                icon=".",
                category="core",
                examples=["Hello", "What is the weather today"],
            )
        )
        registry.register(
            SkillDefinition(
                id="code",
                name="Code Generation",
                description="Generate and modify code",
                icon=".",
                category="dev",
                examples=["Write a Python function"],
            )
        )
        return registry

    def test_constructs_without_error(self, _with_pyside_mock, mock_registry):
        from ui.skill_panel import SkillPanel

        settings = _make_mock_settings()
        panel = SkillPanel(mock_registry, settings)
        assert panel is not None
        assert panel._registry is mock_registry

    def test_constructs_with_parent(self, _with_pyside_mock, mock_registry):
        from ui.skill_panel import SkillPanel

        settings = _make_mock_settings()
        parent = MagicMock()
        panel = SkillPanel(mock_registry, settings, parent=parent)
        assert panel is not None

    def test_has_expected_signal(self, _with_pyside_mock, mock_registry):
        from ui.skill_panel import SkillPanel

        settings = _make_mock_settings()
        panel = SkillPanel(mock_registry, settings)
        assert hasattr(panel, "example_selected")

    def test_skill_cards_created(self, _with_pyside_mock, mock_registry):
        from ui.skill_panel import SkillPanel

        settings = _make_mock_settings()
        panel = SkillPanel(mock_registry, settings)
        assert len(panel._cards) == 2
        assert panel._container_layout is not None

    def test_is_dialog_subclass(self, _with_pyside_mock):
        from ui.skill_panel import SkillPanel

        assert SkillPanel.__mro__[1].__name__ == "_MockQDialog"


# ============================================================================
# Test: MemoryConsoleWindow construction
# ============================================================================


class TestMemoryConsoleConstruction:
    """Smoke tests for MemoryConsoleWindow (QDialog) construction under PySide6 mock."""

    @pytest.fixture
    def mock_control_service(self):
        svc = MagicMock()
        svc.get_all_memories.return_value = []
        svc.get_memory_by_id.return_value = None
        svc.search_memories.return_value = []
        svc._settings = _make_mock_settings()
        return svc

    def test_constructs_without_error(self, _with_pyside_mock, mock_control_service):
        from ui.memory_console_window import MemoryConsoleWindow

        window = MemoryConsoleWindow(mock_control_service)
        assert window is not None
        assert window._control is mock_control_service

    def test_constructs_with_parent(self, _with_pyside_mock, mock_control_service):
        from ui.memory_console_window import MemoryConsoleWindow

        parent = MagicMock()
        window = MemoryConsoleWindow(mock_control_service, parent=parent)
        assert window is not None

    def test_has_expected_signal(self, _with_pyside_mock, mock_control_service):
        from ui.memory_console_window import MemoryConsoleWindow

        window = MemoryConsoleWindow(mock_control_service)
        assert hasattr(window, "memory_changed")

    def test_initial_state_attributes(self, _with_pyside_mock, mock_control_service):
        from ui.memory_console_window import MemoryConsoleWindow

        window = MemoryConsoleWindow(mock_control_service)
        assert window._current_item is None
        assert window._show_full is False
        assert window._items_per_page == 20

    def test_ui_children_created(self, _with_pyside_mock, mock_control_service):
        from ui.memory_console_window import MemoryConsoleWindow

        window = MemoryConsoleWindow(mock_control_service)
        assert hasattr(window, "_table")
        assert hasattr(window, "_search_input")
        assert hasattr(window, "_type_filter")
        assert hasattr(window, "_refresh_btn")

    def test_is_dialog_subclass(self, _with_pyside_mock):
        from ui.memory_console_window import MemoryConsoleWindow

        assert MemoryConsoleWindow.__mro__[1].__name__ == "_MockQDialog"


# ============================================================================
# Test: QtHitlApprovalProvider class-level checks
# ============================================================================


class TestHitlApprovalProviderClass:
    """Class-level structural checks for QtHitlApprovalProvider."""

    def test_is_qobject_subclass(self, _with_pyside_mock):
        from ui.hitl_approval_provider import QtHitlApprovalProvider

        assert QtHitlApprovalProvider.__mro__[1].__name__ == "_MockQObject"

    def test_signal_class_attribute(self, _with_pyside_mock):
        from ui.hitl_approval_provider import QtHitlApprovalProvider

        assert hasattr(QtHitlApprovalProvider, "approval_requested")
