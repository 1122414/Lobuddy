"""Deterministic explicit identity signals, independent of the agent engine."""

import re


def extract_user_name(text: str) -> str | None:
    if looks_like_identity_question(text):
        return None
    patterns = [
        r"(?:my name is|call me)\s+([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})",
        r"(?:我叫|我的名字是|请叫我)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip(" ，。,.!！?？")
            return None if is_invalid_identity_value(candidate) else candidate
    return None


def extract_pet_name(text: str) -> str | None:
    if looks_like_identity_question(text):
        return None
    patterns = [
        r"(?:your name is|i will call you|from now on you are)\s+([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})",
        r"(?:你叫|你的名字是|以后叫你|以后你叫|叫你)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip(" ，。,.!！?？")
            return None if is_invalid_identity_value(candidate) else candidate
    return None


def looks_like_identity_question(text: str) -> bool:
    lower = text.lower()
    return any(
        phrase in lower
        for phrase in (
            "who am i",
            "who are you",
            "what is my name",
            "what's my name",
            "我是谁",
            "你是谁",
            "我叫什么",
            "你叫什么",
        )
    )


def is_invalid_identity_value(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {
        "",
        "who",
        "what",
        "unknown",
        "谁",
        "什么",
    }
