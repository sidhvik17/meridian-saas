"""Logging utilities — PII redaction for every log handler."""
from __future__ import annotations

import logging
import re
from typing import Final

_EMAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)
_BEARER_RE: Final[re.Pattern[str]] = re.compile(r"(?i)\b(bearer|token|api[_-]?key)\b[\s:=]+\S+")

_REDACTED: Final[str] = "[REDACTED]"


class RedactPIIFilter(logging.Filter):
    """Mask email addresses and credential-like substrings in log records.

    Applied to every handler via ``LOGGING`` so a stray ``logger.info`` in
    application code cannot leak PII or tokens to log aggregation.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _EMAIL_RE.sub(_REDACTED, message)
        redacted = _BEARER_RE.sub(_REDACTED, redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True
