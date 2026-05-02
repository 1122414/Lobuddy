"""Trigger rules for profile updates."""

STRONG_SIGNALS = [
    "remember this",
    "from now on",
    "i do not like",
    "i do not want",
    "i like",
    "i prefer",
    "default to",
    "remember that",
    "always",
    "never",
    "记住",
    "以后叫我",
    "后面叫我",
    "我叫",
    "我是",
    "叫我",
    "你叫",
    "你是",
    "改名",
    "从现在开始",
    "永远",
    "不再",
    "不喜欢",
    "不想",
    "偏好",
    "默认",
]


def has_strong_signal(text: str) -> bool:
    """Check if message contains strong memory signal."""
    lower = text.lower()
    return any(signal in lower for signal in STRONG_SIGNALS)


def should_update_on_message_count(
    user_message_count: int,
    update_every_n: int,
) -> bool:
    """Check if profile should update based on message count."""
    if update_every_n <= 0:
        return False
    return user_message_count > 0 and user_message_count % update_every_n == 0
