"""Tests for token meter."""

import pytest

from core.runtime.token_meter import TokenMeter, TokenUsage


class TestTokenMeter:
    """Test token metering functionality."""

    def test_token_accounting(self):
        """Test that token usage is recorded correctly per module."""
        meter = TokenMeter()

        # Record usage for different modules
        meter.record_usage("session_1", "system", prompt_tokens=100)
        meter.record_usage("session_1", "history", prompt_tokens=200)
        meter.record_usage("session_1", "user_input", prompt_tokens=50)
        meter.record_usage("session_1", "output", completion_tokens=150)

        stats = meter.get_last_call_stats("session_1")
        assert stats is not None
        assert stats["total_tokens"] == 500
        assert stats["total_prompt"] == 350
        assert stats["total_completion"] == 150
        assert stats["modules"]["system"]["prompt"] == 100
        assert stats["modules"]["output"]["completion"] == 150

    def test_tool_result_truncation(self):
        """Test that tool results above threshold are truncated."""
        meter = TokenMeter()

        long_text = "word " * 3000  # ~15000 chars, well above 2000 tokens

        # Should need truncation (using a simple mock encoder)
        class MockEncoder:
            def encode(self, text):
                return text.split()

        encoder = MockEncoder()
        assert meter.should_truncate(long_text, encoder) is True

        short_text = "hello"
        assert meter.should_truncate(short_text, encoder) is False

    def test_rolling_summary_trigger(self):
        """Test that rolling summary triggers after threshold."""
        meter = TokenMeter()

        # Should not trigger before threshold
        for _ in range(10):
            meter.increment_turn("session_1")
        assert meter.should_trigger_rolling_summary("session_1") is False

        # Should trigger after threshold
        meter.increment_turn("session_1")
        assert meter.should_trigger_rolling_summary("session_1") is True

    def test_session_reset(self):
        """Test that session metrics can be reset."""
        meter = TokenMeter()
        meter.record_usage("session_1", "test", prompt_tokens=100)

        assert meter.get_session_metrics("session_1") is not None
        meter.reset_session("session_1")
        assert meter.get_session_metrics("session_1") is None

    def test_multiple_sessions(self):
        """Test that multiple sessions are tracked independently."""
        meter = TokenMeter()

        meter.record_usage("session_1", "test", prompt_tokens=100)
        meter.record_usage("session_2", "test", prompt_tokens=200)

        stats_1 = meter.get_last_call_stats("session_1")
        stats_2 = meter.get_last_call_stats("session_2")

        assert stats_1["total_tokens"] == 100
        assert stats_2["total_tokens"] == 200


class TestTokenUsage:
    """Test TokenUsage dataclass."""

    def test_total_property(self):
        """Test that total combines prompt and completion."""
        usage = TokenUsage(prompt=100, completion=50)
        assert usage.total == 150

    def test_default_values(self):
        """Test default values are zero."""
        usage = TokenUsage()
        assert usage.prompt == 0
        assert usage.completion == 0
        assert usage.total == 0
