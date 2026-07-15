from __future__ import annotations

import re
from pathlib import Path
from typing import Any

REDACTION = "[REDACTED_SECRET]"

_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b", flags=re.IGNORECASE),
    re.compile(
        r"(?P<prefix>\b(?:api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*)"
        r"(?P<quote>[\"']?)"
        r"(?P<value>[^\s\"',}\]]{6,})"
        r"(?P=quote)",
        flags=re.IGNORECASE,
    ),
]


def redact_text(value: str) -> str:
    redacted = value
    redacted = _SECRET_PATTERNS[0].sub(REDACTION, redacted)
    redacted = _SECRET_PATTERNS[1].sub(f"Bearer {REDACTION}", redacted)
    redacted = _SECRET_PATTERNS[2].sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('quote')}"
            f"{REDACTION}{match.group('quote')}"
        ),
        redacted,
    )
    return redacted


def redact_for_log(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Path):
        return value
    if isinstance(value, list):
        return [redact_for_log(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_for_log(item) for item in value)
    if isinstance(value, dict):
        return {key: redact_for_log(item) for key, item in value.items()}
    return value
