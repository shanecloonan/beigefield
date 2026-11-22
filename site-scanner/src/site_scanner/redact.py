"""Replace secret-shaped strings before anything is stored or shown."""

from __future__ import annotations

import math
import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    ("stripe-live-key", re.compile(r"\bsk_live_[0-9A-Za-z]{16,}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")),
    ("slack-token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{20,}\b")),
]

_ASSIGNED = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|password|private[_-]?key)\s*[:=]\s*['\"]([A-Za-z0-9_\-+/=]{24,})['\"]"
)


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    total = len(value)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def redact(text: str) -> tuple[str, list[str]]:
    """Return text with secrets removed, and the kinds that were found."""
    found: list[str] = []
    out = text or ""
    for kind, pattern in _PATTERNS:
        if pattern.search(out):
            found.append(kind)
            out = pattern.sub("«redacted:%s»" % kind, out)

    def _swap(match: re.Match[str]) -> str:
        token = match.group(1)
        if _entropy(token) < 3.5:
            return match.group(0)
        found.append("assigned-secret")
        return match.group(0).replace(token, "«redacted:assigned-secret»")

    out = _ASSIGNED.sub(_swap, out)
    # Stable order, one mention per kind.
    kinds = list(dict.fromkeys(found))
    return out, kinds
