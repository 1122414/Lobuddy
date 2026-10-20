"""Test script for Lobuddy companion features.

Usage: pytest tests/test_companion_features.py -v
       python -m pytest tests/test_companion_features.py -v
"""

import pytest
from datetime import datetime, timedelta

from core.time_format import (
    format_message_time,
    format_clock_time,
    format_full_datetime,
    format_time_divider_label,
    get_greeting_for_hour,
    is_sleepy_time,
    minutes_since,
)
from core.pet_state_manager import PetStateManager, PetState, MaxPriorityState


class TestTimeFormat:
    def test_format_message_time_HH_mm(self):
        dt = datetime(2026, 4, 28, 20, 35, 21)
        assert format_message_time(dt, "HH:mm") == "20:35"

    def test_format_message_time_full(self):
        dt = datetime(2026, 4, 28, 20, 35, 21)
        result = format_message_time(dt, "yyyy年M月d日 HH:mm")
        assert "2026" in result
        assert "4" in result
        assert "28" in result

    def test_format_clock_time_no_seconds(self):
        dt = datetime(2026, 4, 28, 20, 35, 21)
        result = format_clock_time(dt, show_seconds=False)
        assert result == "04/28 20:35"

    def test_format_clock_time_with_seconds(self):
        dt = datetime(2026, 4, 28, 20, 35, 21)
        result = format_clock_time(dt, show_seconds=True)
        assert result == "04/28 20:35:21"

    def test_format_full_datetime(self):
        dt = datetime(2026, 4, 28, 20, 35, 21)
        result = format_full_datetime(dt)
        assert "2026年4月28日" in result
        assert "20:35:21" in result

    def test_format_time_divider_today(self):
        now = datetime(2026, 4, 28, 22, 0, 0)
        dt = datetime(2026, 4, 28, 20, 35, 0)
        result = format_time_divider_label(dt, now)
        assert result == "今天 20:35"

    def test_format_time_divider_other_day(self):
        now = datetime(2026, 4, 28, 22, 0, 0)
        dt = datetime(2026, 4, 27, 15, 0, 0)
        result = format_time_divider_label(dt, now)
        assert "2026年4月27日" in result

    def test_greeting_morning(self):
        assert get_greeting_for_hour(7) == "morning"

    def test_greeting_afternoon(self):
        assert get_greeting_for_hour(14) == "afternoon"

    def test_greeting_evening(self):
        assert get_greeting_for_hour(19) == "evening"

    def test_greeting_night(self):
        assert get_greeting_for_hour(2) == "night"

    def test_is_sleepy_time_overnight(self):
        assert is_sleepy_time(23, 23, 6)

    def test_is_sleepy_time_early(self):
        assert is_sleepy_time(3, 23, 6)

    def test_is_sleepy_time_daytime(self):
        assert not is_sleepy_time(14, 23, 6)

    def test_minutes_since(self):
        dt = datetime(2026, 4, 28, 20, 30, 0)
        now = datetime(2026, 4, 28, 20, 35, 0)
        assert minutes_since(dt, now) == pytest.approx(5.0, 0.01)


class TestPetStateManager:
    def test_default_idle(self):
        mgr = PetStateManager()
        assert mgr.current_state == PetState.IDLE

    def test_disabled_always_idle(self):
        mgr = PetStateManager()
        mgr.enabled = False
        mgr.set_state(PetState.WORKING)
        assert mgr.current_state == PetState.IDLE

    def test_thinking_on_message(self):
        mgr = PetStateManager()
        mgr.on_message_sent()
        assert mgr.current_state == PetState.THINKING

    def test_happy_temporary(self):
        mgr = PetStateManager()
        mgr.on_pet_clicked()
        assert mgr.current_state == PetState.HAPPY

    def test_priority_error_over_thinking(self):
        mgr = PetStateManager()
        mgr.on_message_sent()
        mgr.on_task_error()
        assert mgr.current_state == PetState.ERROR

    def test_priority_think_over_listening(self):
        mgr = PetStateManager()
        mgr.on_user_typing()
        assert mgr.current_state == PetState.LISTENING
        mgr.on_message_sent()
        assert mgr.current_state == PetState.THINKING

    def test_state_text(self):
        mgr = PetStateManager()
        texts = {"idle": "待机中", "thinking": "思考中"}
        mgr.on_message_sent()
        assert mgr.get_state_text(texts) == "思考中"

    def test_time_based_idle(self):
        mgr = PetStateManager()
        mgr.update_time_based_state(hour=14, idle_minutes=15, idle_threshold=10, sleepy_start=23, sleepy_end=6)
        assert mgr.current_state == PetState.IDLE

    def test_time_based_sleepy(self):
        mgr = PetStateManager()
        mgr.update_time_based_state(hour=23, idle_minutes=0, idle_threshold=10, sleepy_start=23, sleepy_end=6)
        assert mgr.current_state == PetState.SLEEPY


class TestMaxPriorityState:
    def test_higher_wins(self):
        result = MaxPriorityState(PetState.IDLE, PetState.ERROR)
        assert result == PetState.ERROR

    def test_same_returns_first(self):
        result = MaxPriorityState(PetState.IDLE, PetState.IDLE)
        assert result == PetState.IDLE


class TestCompanionSettings:
    def test_settings_fields_exist(self):
        from core.config.settings import Settings
        s = Settings(llm_api_key="test")
        assert hasattr(s, 'pet_click_feedback_enabled')
        assert s.pet_click_feedback_enabled is True
        assert hasattr(s, 'pet_clock_enabled')
        assert s.pet_clock_enabled is True
        assert hasattr(s, 'chat_message_time_enabled')
        assert s.chat_message_time_enabled is True
        assert hasattr(s, 'conversation_timeline_enabled')
        assert s.conversation_timeline_enabled is True
        assert hasattr(s, 'pet_state_enabled')
        assert s.pet_state_enabled is True
        assert hasattr(s, 'daily_greeting_enabled')
        assert s.daily_greeting_enabled is False

    def test_pet_state_texts_exist(self):
        from core.config.settings import Settings
        s = Settings(llm_api_key="test")
        assert s.pet_state_text_idle == "待机中"
        assert s.pet_state_text_happy == "开心"

    def test_greeting_messages_exist(self):
        from core.config.settings import Settings
        s = Settings(llm_api_key="test")
        assert len(s.greeting_morning) > 0
        assert len(s.greeting_night) > 0


class TestReservedInterfaces:
    def test_memory_card_store(self):
        from core.reserved.memory_card_store import MemoryCardStore
        store = MemoryCardStore()
        card = store.add_card("test memory")
        assert len(store.list_cards()) == 1
        store.delete_card(card.id)
        assert len(store.list_cards()) == 0

    def test_focus_companion(self):
        from core.reserved.focus_companion import FocusCompanion
        fc = FocusCompanion()
        session = fc.start_focus()
        assert session.is_running
        fc.stop_current()
        assert not session.is_running

    def test_message_highlight(self):
        from core.reserved.message_highlight import MessageHighlightStore
        store = MessageHighlightStore()
        h = store.add_highlight("s1", "m1", "hello")
        assert len(store.get_highlights("s1")) == 1
        store.remove_highlight(h.id)
        assert len(store.get_highlights()) == 0
