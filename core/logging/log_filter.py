"""Log redaction filter for sensitive data."""

import logging
import re

class SensitiveDataFilter(logging.Filter):
    """Redacts sensitive information from log records."""
    
    PATTERNS = {
        "api_key": (
            re.compile(r"(sk-[a-zA-Z0-9]{20,48})"),
            "[API_KEY_REDACTED]",
        ),
        "bearer_token": (
            re.compile(r"(Bearer\s+)[a-zA-Z0-9\-_~+/]+=*"),
            r"\1[TOKEN_REDACTED]",
        ),
    }
    
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for name, (pattern, replacement) in self.PATTERNS.items():
            msg = pattern.sub(replacement, msg)
        record.msg = msg
        record.args = ()
        return True
