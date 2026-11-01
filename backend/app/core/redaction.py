from __future__ import annotations

import re

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{8,}", re.IGNORECASE),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{8,}"),
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key|token|authorization)\s*[:=]\s*\S+"),
)


def redact(text: str, limit: int = 300) -> str:
    """Remove credential-shaped strings and cap length before logging or storage."""
    cleaned = text.replace("\x00", " ")
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > limit:
        return cleaned[: limit - 1] + "…"
    return cleaned
