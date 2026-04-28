"""Unified time formatting utilities for Lobuddy."""

from datetime import datetime


def format_message_time(dt: datetime, fmt: str = "HH:mm") -> str:
    """Format a datetime for message timestamp display.

    Args:
        dt: The datetime to format
        fmt: Format string, supports custom tokens:
             HH=24h, hh=12h, mm=minutes, ss=seconds,
             yyyy=4-digit year, M=month(1-12), MM=zero-padded month,
             d=day, dd=zero-padded day, dddd=weekday name
    """
    weekday_map = {
        0: "周一", 1: "周二", 2: "周三", 3: "周四",
        4: "周五", 5: "周六", 6: "周日",
    }
    result = fmt
    result = result.replace("yyyy", str(dt.year))
    result = result.replace("MM", f"{dt.month:02d}")
    result = result.replace("dd", f"{dt.day:02d}")
    result = result.replace("HH", f"{dt.hour:02d}")
    result = result.replace("mm", f"{dt.minute:02d}")
    result = result.replace("ss", f"{dt.second:02d}")
    result = result.replace("dddd", weekday_map.get(dt.weekday(), ""))
    result = result.replace("M", str(dt.month))
    result = result.replace("d", str(dt.day))
    result = result.replace("hh", f"{dt.hour % 12 or 12:02d}")
    return result


def format_clock_time(dt: datetime, show_seconds: bool = False) -> str:
    """Format datetime for pet clock display: MM/dd HH:mm or MM/dd HH:mm:ss."""
    base = f"{dt.month:02d}/{dt.day:02d} {dt.hour:02d}:{dt.minute:02d}"
    if show_seconds:
        base += f":{dt.second:02d}"
    return base


def format_full_datetime(dt: datetime) -> str:
    """Format full datetime for tooltip: yyyy年M月d日 HH:mm:ss."""
    return f"{dt.year}年{dt.month}月{dt.day}日 {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"


def format_time_divider_label(dt: datetime, now: datetime = None) -> str:
    """Format a time divider label for chat.

    Args:
        dt: The message datetime
        now: Current time reference (defaults to datetime.now())

    Returns:
        "今天 HH:mm" for today, "yyyy年M月d日 dddd" for other days
    """
    if now is None:
        now = datetime.now()
    weekday_map = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"}
    if dt.date() == now.date():
        return f"今天 {dt.hour:02d}:{dt.minute:02d}"
    return f"{dt.year}年{dt.month}月{dt.day}日 {weekday_map.get(dt.weekday(), '')}"


def get_greeting_for_hour(hour: int) -> str:
    """Get appropriate greeting based on hour of day.

    Returns one of: 'morning', 'afternoon', 'evening', 'night'
    """
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 23:
        return "evening"
    else:
        return "night"


def is_sleepy_time(hour: int, start_hour: int = 23, end_hour: int = 6) -> bool:
    """Check if current hour falls within sleepy time range."""
    if start_hour > end_hour:
        return hour >= start_hour or hour < end_hour
    return start_hour <= hour < end_hour


def minutes_since(dt: datetime, now: datetime = None) -> float:
    """Calculate minutes elapsed since a given datetime."""
    if now is None:
        now = datetime.now()
    delta = now - dt
    return delta.total_seconds() / 60.0
