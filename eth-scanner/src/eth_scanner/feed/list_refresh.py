"""Pick fresh scan-list rows from evidence. No heat and no transactions.

A row is eligible when the measured dollars are at least $100, the
contract is verified or has code, and the notes do not say it was
drained or already exploited. Risk signals raise the rank. They do not
add heat. List sizes stay at the previous loaded counts when enough
rows qualify.
"""

from __future__ import annotations

import re
from typing import Any, Optional

FLOOR_USD = 100.0
LIST1_COUNT = 2178
LIST2_COUNT = 929
LIST1_MIN = 2000.0
LIST1_MAX = 9_000_000.0
LIST2_MIN = 100.0
LIST2_MAX = 1900.0

_EXPLOITED = re.compile(r"past-hack|drained|exploit|rug|hacked", re.I)
_SIGNALS = (
    ("upgradeable", ("upgradeable", "proxy")),
    ("oracle", ("oracle", "chainlink")),
    ("vault", ("vault", "erc4626", "erc-4626")),
    ("lending", ("lending", "borrow")),
    ("single-key-admin", ("eoa-admin", "eoa admin", "single-key", "single key")),
    ("recent-upgrade", ("recent-upgrade", "recent upgrade", "upgraded")),
)


def chain_of_reason(reason: str) -> str:
    for part in (reason or "").split(";"):
        if not part.startswith("chain="):
            continue
        name = part.split("=", 1)[1]
        if name in {"ethereum", "bsc", "arbitrum", "base"}:
            return name
    return "ethereum"


def signals_in(text: str) -> list[str]:
    low = (text or "").lower()
    return [name for name, keys in _SIGNALS if any(key in low for key in keys)]


def exploited(text: str) -> bool:
    return bool(_EXPLOITED.search(text or ""))


def selection_reason(row: dict[str, Any], names: list[str]) -> str:
    parts = [
        "fresh-pick",
        "funds=%.2f" % float(row["usd"]),
        "source=%s" % (row.get("dollars_source") or "prior-measurement"),
        "chain=%s" % (row.get("chain") or "ethereum"),
    ]
    if row.get("verified"):
        parts.append("verified")
    elif row.get("has_code"):
        parts.append("decompilable")
    if names:
        parts.append("signals=" + ",".join(names))
    if row.get("not_recently_scanned"):
        parts.append("not-recently-scanned")
    parts.append("not-exploited")
    return ";".join(parts)


def choose_lists(
    rows: list[dict[str, Any]],
    *,
    list1_count: int = LIST1_COUNT,
    list2_count: int = LIST2_COUNT,
) -> dict[str, Any]:
    """Return two lists. A short list is a short eligible pool, not a padded one."""
    eligible: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in rows:
        address = str(raw.get("address") or "").strip().lower()
        chain = str(raw.get("chain") or "ethereum")
        if not address.startswith("0x") or len(address) != 42:
            continue
        key = (chain, address)
        if key in seen:
            continue
        try:
            usd = float(raw.get("usd") or 0)
        except (TypeError, ValueError):
            continue
        blob = " ".join(str(raw.get(name) or "") for name in ("reason", "category", "protocol", "evidence"))
        if usd < FLOOR_USD or exploited(blob):
            continue
        verified = bool(raw.get("verified"))
        has_code = raw.get("has_code")
        if not verified and has_code is not True:
            continue
        if LIST1_MIN <= usd <= LIST1_MAX:
            band = "list-1"
        elif LIST2_MIN <= usd <= LIST2_MAX:
            if raw.get("big_name"):
                continue
            band = "list-2"
        else:
            continue
        names = signals_in(blob)
        score = len(names) + (1 if verified else 0) + (1 if raw.get("not_recently_scanned") else 0)
        if raw.get("big_name"):
            score -= 3
        seen.add(key)
        eligible.append({
            **raw,
            "address": address,
            "chain": chain,
            "usd": round(usd, 2),
            "band": band,
            "score": score,
            "signal_names": names,
            "candidate_reason": selection_reason(raw, names),
        })
    eligible.sort(key=lambda item: (-int(item["score"]), -float(item["usd"]), item["chain"], item["address"]))
    list1 = [row for row in eligible if row["band"] == "list-1"][:list1_count]
    used = {(row["chain"], row["address"]) for row in list1}
    list2 = [row for row in eligible if row["band"] == "list-2" and (row["chain"], row["address"]) not in used][:list2_count]
    return {
        "list-1": list1,
        "list-2": list2,
        "list1_short": len(list1) < list1_count,
        "list2_short": len(list2) < list2_count,
        "eligible": len(eligible),
    }
