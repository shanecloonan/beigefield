"""Extra evidence that is not an admin key.

An unprotected value move, an unverified upgradeable proxy, and a fresh
high-value deployment each add a small heat component. None of them is a
verdict, and none of them broadcasts a transaction.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

UNPROTECTED_POINTS = 3
PROXY_POINTS = 2
FRESH_POINTS = 2
FRESH_MIN_USD = 100_000
FRESH_DAYS = 30
ADMIN_ONLY_CAP = 5

_FN = re.compile(r"function\s+\w+\s*\([^;]*?\)\s*([^{;]*)\{", re.S)
_GUARD = re.compile(r"\bonlyOwner\b|\bonlyRole\b|\bonlyAdmin\b|\bview\b|\bpure\b")
_VALUE = re.compile(
    r"\.transfer\s*\(|\.transferFrom\s*\(|\.send\s*\(|\.call\s*\{value|_mint\s*\(|safeTransfer"
)
_PROXY = ("upgradeto", "upgradetoandcall", "eip1967.proxy", "3659cfe6", "proxiableuuid")


def unprotected_value_mover(source: str) -> bool:
    """A public function moves value and its header has no admin guard."""
    text = source or ""
    for match in _FN.finditer(text):
        header = match.group(1) or ""
        if _GUARD.search(header):
            continue
        body = text[match.end():match.end() + 400]
        if _VALUE.search(body):
            return True
    return False


def unverified_upgradeable_proxy(*, verified: bool, source: str = "", bytecode: str = "") -> bool:
    """An unverified contract whose source or bytecode looks like a proxy."""
    if verified:
        return False
    blob = "%s\n%s" % (source or "", bytecode or "")
    lowered = blob.lower()
    return any(mark in lowered for mark in _PROXY)


def fresh_deployment(
    funds_usd: Optional[float],
    deployed_at: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> bool:
    """True when value is at least $100k and the contract is at most 30 days old."""
    if funds_usd is None or float(funds_usd) < FRESH_MIN_USD or not deployed_at:
        return False
    text = str(deployed_at).strip().replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = current - when
    return timedelta(0) <= age <= timedelta(days=FRESH_DAYS)


def priority_points(
    *,
    unprotected_value: bool = False,
    unverified_proxy: bool = False,
    funds_usd: Optional[float] = None,
    deployed_at: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    unprotected = UNPROTECTED_POINTS if unprotected_value else 0
    proxy = PROXY_POINTS if unverified_proxy else 0
    fresh = FRESH_POINTS if fresh_deployment(funds_usd, deployed_at, now=now) else 0
    return {
        "unprotected_evidence": unprotected,
        "proxy_evidence": proxy,
        "fresh_evidence": fresh,
        "points": unprotected + proxy + fresh,
    }
