"""Tests for profile update triggers."""

from core.memory.user_profile_triggers import (
    has_strong_signal,
    should_update_on_message_count,
)


class TestStrongSignal:
    """Test has_strong_signal detection."""

    def test_detects_remember_this(self):
        assert has_strong_signal("please remember this about me")

    def test_detects_i_like(self):
        assert has_strong_signal("I like Python more than Java")

    def test_detects_i_prefer(self):
        assert has_strong_signal("I prefer dark mode")

    def test_detects_from_now_on(self):
        assert has_strong_signal("from now on, use tabs")

    def test_ignores_normal_message(self):
        assert not has_strong_signal("what is the weather today?")

    def test_case_insensitive(self):
        assert has_strong_signal("REMEMBER THIS")


class TestMessageCountTrigger:
    """Test should_update_on_message_count."""

    def test_triggers_on_interval(self):
        assert should_update_on_message_count(6, 6)

    def test_triggers_on_multiple(self):
        assert should_update_on_message_count(12, 6)

    def test_no_trigger_before_interval(self):
        assert not should_update_on_message_count(5, 6)

    def test_no_trigger_at_zero(self):
        assert not should_update_on_message_count(0, 6)

    def test_no_trigger_when_interval_zero(self):
        assert not should_update_on_message_count(6, 0)

    def test_no_trigger_when_interval_negative(self):
        assert not should_update_on_message_count(6, -1)
