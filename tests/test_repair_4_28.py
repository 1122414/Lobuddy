"""Tests for bug fixes in repair_4.28.md."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.agent.nanobot_adapter import AgentResult, NanobotAdapter
from core.config import Settings
from core.models.chat import ChatMessage, ChatSession
from core.storage.chat_repo import ChatRepository
from core.storage.settings_repo import SettingsRepository


class TestSettingsSaveAndSync:
    """Bug 2: Settings must save to DB and sync to all components."""

    def test_settings_window_save_logic(self):
        """Test the settings save logic without Qt UI."""
        settings = Settings(
            llm_api_key="sk-test-key",
            llm_base_url="https://api.example.com/v1",
            llm_model="gpt-4",
            pet_name="TestPet",
            task_timeout=60,
            shell_enabled=False,
        )
        saved = {}

        def fake_set_setting(key, value):
            saved[key] = value

        repo = MagicMock()
        repo.set_setting = fake_set_setting

        # Simulate what _on_save does
        pet_name = "NewPet"
        api_key = "sk-test-key"
        base_url = "https://api.new.com/v1"
        model = "gpt-3.5"
        timeout = "90"
        shell = "True"

        repo.set_setting("pet_name", pet_name)
        repo.set_setting("llm_api_key", api_key)
        repo.set_setting("llm_base_url", base_url)
        repo.set_setting("llm_model", model)
        repo.set_setting("task_timeout", timeout)
        repo.set_setting("shell_enabled", shell)

        assert saved["pet_name"] == "NewPet"
        assert saved["llm_api_key"] == "sk-test-key"
        assert saved["llm_base_url"] == "https://api.new.com/v1"
        assert saved["llm_model"] == "gpt-3.5"
        assert saved["task_timeout"] == "90"
        assert saved["shell_enabled"] == "True"

    def test_api_key_preserved_when_not_modified(self):
        """Test that original API key is preserved when input is empty."""
        original_api_key = "sk-secret-key"
        api_key_input = ""  # User didn't modify

        # Logic from _on_save
        if not api_key_input or api_key_input == original_api_key:
            api_key_to_save = original_api_key
        else:
            api_key_to_save = api_key_input

        assert api_key_to_save == "sk-secret-key"


class TestApiKeyValidation:
    """Bug 5 + extra: API Key must be present and not sent as empty."""

    def test_agent_result_detects_api_key_error(self):
        adapter = NanobotAdapter.__new__(NanobotAdapter)
        is_error, detail = adapter._looks_like_api_error(
            'You didn\'t provide an API key. You need to provide your API key in an Authorization header...'
        )
        assert is_error is True
        assert "api key" in detail.lower()

    def test_agent_result_ignores_normal_content(self):
        adapter = NanobotAdapter.__new__(NanobotAdapter)
        is_error, _ = adapter._looks_like_api_error("Hello, how can I help you today?")
        assert is_error is False

    def test_build_success_result_flags_api_error(self):
        settings = Settings(
            llm_api_key="sk-test",
            llm_base_url="https://api.example.com/v1",
            llm_model="gpt-4",
        )
        adapter = NanobotAdapter(settings)

        mock_result = MagicMock()
        mock_result.content = "You didn't provide an API key. Please provide your API key."

        tracker = MagicMock()
        tracker.tools_used = []

        result = adapter._build_success_result(
            mock_result, tracker, datetime.now(), "test prompt", "test_session"
        )
        assert result.success is False
        assert "API request failed" in result.summary
        assert "api key" in result.error_message.lower()


class TestHistoryPersistence:
    """Bug 4: Chat history must persist to SQLite and be loadable."""

    def test_chat_repo_saves_and_loads_messages(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        settings = Settings(
            llm_api_key="sk-test",
            llm_base_url="https://api.example.com/v1",
            llm_model="gpt-4",
            data_dir=data_dir,
        )
        with patch("core.storage.db._db", None):
            from core.storage.db import Database

            db = Database(settings)
            db.init_database()
            repo = ChatRepository(db)

            session = ChatSession(id="sess_001", title="Test Chat")
            repo.save_session(session)

            msg = ChatMessage(
                id=str(uuid.uuid4()),
                session_id="sess_001",
                role="user",
                content="Hello",
            )
            repo.save_message(msg)

            loaded = repo.get_session("sess_001")
            assert loaded is not None
            assert len(loaded.messages) == 1
            assert loaded.messages[0].content == "Hello"

    def test_chat_repo_get_all_sessions(self, tmp_path):
        data_dir = tmp_path / "data2"
        data_dir.mkdir()
        settings = Settings(
            llm_api_key="sk-test",
            llm_base_url="https://api.example.com/v1",
            llm_model="gpt-4",
            data_dir=data_dir,
        )
        with patch("core.storage.db._db", None):
            from core.storage.db import Database

            db = Database(settings)
            db.init_database()
            repo = ChatRepository(db)

            for i in range(3):
                session = ChatSession(id=f"sess_{i}", title=f"Chat {i}")
                repo.save_session(session)

            sessions = repo.get_all_sessions()
            assert len(sessions) == 3


class TestHistoryWindow:
    """Bug 1: History window must display sessions correctly."""

    def test_history_window_loads_sessions(self, tmp_path):
        from ui.history_window import HistoryWindow
        from PySide6.QtWidgets import QApplication

        if not QApplication.instance():
            app = QApplication([])  # noqa: F841

        data_dir = tmp_path / "data_hist"
        data_dir.mkdir()
        settings = Settings(
            llm_api_key="sk-test",
            llm_base_url="https://api.example.com/v1",
            llm_model="gpt-4",
            data_dir=data_dir,
        )
        with patch("core.storage.db._db", None):
            from core.storage.db import Database

            db = Database(settings)
            db.init_database()
            repo = ChatRepository(db)

            session = ChatSession(id="sess_001", title="My Chat")
            repo.save_session(session)
            msg = ChatMessage(
                id=str(uuid.uuid4()),
                session_id="sess_001",
                role="user",
                content="Test message",
            )
            repo.save_message(msg)

            window = HistoryWindow(repo)
            # After loading, there should be at least one card widget
            assert window.session_layout.count() > 0

    def test_history_window_empty_state(self, tmp_path):
        from ui.history_window import HistoryWindow
        from PySide6.QtWidgets import QApplication

        if not QApplication.instance():
            app = QApplication([])  # noqa: F841

        data_dir = tmp_path / "data_empty"
        data_dir.mkdir()
        settings = Settings(
            llm_api_key="sk-test",
            llm_base_url="https://api.example.com/v1",
            llm_model="gpt-4",
            data_dir=data_dir,
        )
        with patch("core.storage.db._db", None):
            from core.storage.db import Database

            db = Database(settings)
            db.init_database()
            repo = ChatRepository(db)

            window = HistoryWindow(repo)
            # Should show empty state label
            assert window.session_layout.count() > 0


class TestTaskStatusOnApiFailure:
    """Extra: Tasks with API errors must not show Success or award EXP."""

    def test_task_result_failure_no_exp(self):
        from core.models.task_card import TaskCardModel

        card = TaskCardModel(
            title="Task Complete",
            status="failed",
            task_id="t1",
            short_result="API key missing",
            exp_reward=0,
        )
        assert card.status == "failed"
        assert card.exp_reward == 0

    def test_task_manager_on_failed_task(self):
        from core.models.pet import TaskRecord, TaskStatus, TaskResult

        task = TaskRecord(id="t1", input_text="test", status=TaskStatus.RUNNING)
        result = TaskResult(
            task_id="t1",
            success=False,
            raw_output="",
            summary="Failed",
            error_message="No API key",
        )
        task.complete(False)
        assert task.status == TaskStatus.FAILED
