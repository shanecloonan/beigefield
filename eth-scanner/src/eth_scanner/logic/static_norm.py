"""Normalize Slither, Aderyn, and Semgrep rows into one evidence scale.

High-confidence funds detectors are worth the most. Generic style checks,
informational noise, and findings that only describe an Ownable or
AccessControl guard are worth zero. Nothing here is a verdict.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Detectors whose hit is itself a funds-moving logic bug, not a style note.
HIGH_RULES = frozenset({
    "arbitrary-send-eth",
    "arbitrary-send-erc20",
    "arbitrary-send-erc20-permit",
    "suicidal",
    "unprotected-upgrade",
    "controlled-delegatecall",
    "uncontrolled-delegatecall",
    "uninitialized-state",
    "uninitialized-storage",
    "reentrancy-eth",
    "unprotected-initializer",
    "delegatecall-user-target",
    "spot-price-value",
    "share-inflation-empty",
    "public-selfdestruct",
})

MEDIUM_RULES = frozenset({
    "reentrancy-no-eth",
    "reentrancy-benign",
    "unchecked-transfer",
    "unchecked-lowlevel",
    "unchecked-send",
    "tx-origin",
    "tx-origin-auth",
    "divide-before-multiply",
    "weak-prng",
    "encode-packed-collision",
    "multiple-constructors",
    "locked-ether",
})

# Admin-key and style noise. These must not feed heat.
ZERO_RULES = frozenset({
    "centralization-risk",
    "naming-convention",
    "solc-version",
    "pragma",
    "timestamp",
    "block-timestamp",
    "costly-loop",
    "costly-operations-loop",
    "too-many-digits",
    "boolean-equal",
    "assembly",
    "unused-state",
    "constable-states",
})

# Aderyn and Semgrep ids that name the same bug as a Slither check.
RULE_ALIASES = {
    "reentrancy-state-change": "reentrancy-eth",
    "reentrancy-vulnerable": "reentrancy-eth",
    "reentrancy-without-eth-transfer": "reentrancy-no-eth",
    "arbitrary-transfer-from": "arbitrary-send-erc20",
    "unchecked-return": "unchecked-transfer",
    "weak-randomness": "weak-prng",
    "delegate-call": "controlled-delegatecall",
    "delegatecall-in-loop": "controlled-delegatecall",
    "uninitialized-state-variable": "uninitialized-state",
    "uninitialized-storage-variable": "uninitialized-storage",
    "tx-origin-used-for-auth": "tx-origin-auth",
    "selfdestruct": "public-selfdestruct",
    "suicidal": "suicidal",
}

_ADMIN_GUARD = re.compile(
    r"onlyOwner|onlyRole|AccessControl|_checkOwner|requiresAuth|whenNotPaused",
    re.I,
)
_UNPROTECTED = re.compile(
    r"unprotected|missing (?:modifier|access)|anyone-callable|no access control|public initialize",
    re.I,
)
_LONG_HEX = re.compile(r"0x[0-9a-fA-F]{16,}")
_URL = re.compile(r"https?://\S+", re.I)

STATIC_CAP = 6
HIGH_WEIGHT = 3
MEDIUM_WEIGHT = 1


def clean_evidence(text: Any, limit: int = 400) -> str:
    """Short evidence. Drop calldata-sized hex and URLs."""
    cleaned = _URL.sub("[url]", str(text or ""))
    cleaned = _LONG_HEX.sub("0x…", cleaned)
    return " ".join(cleaned.split())[:limit]


def rule_name(raw: Any) -> str:
    text = str(raw or "").strip().lower().replace("_", "-")
    if not text:
        return ""
    leaf = text.split(".")[-1].split(":")[-1]
    return RULE_ALIASES.get(leaf, leaf)


def _field(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def as_row(row: Any) -> dict[str, Any]:
    """Accept an EngineFinding or a plain dict."""
    if isinstance(row, dict):
        src = row
    else:
        src = {
            "engine": _field(row, "engine", ""),
            "rule": _field(row, "rule", ""),
            "title": _field(row, "title", ""),
            "severity": _field(row, "severity", "info"),
            "confidence": _field(row, "confidence", "low"),
            "funds_class": _field(row, "funds_class", "") or _field(row, "class", ""),
            "evidence": _field(row, "evidence", ""),
            "function": _field(row, "function"),
            "line": _field(row, "line"),
            "file": _field(row, "file"),
            "contract": _field(row, "contract"),
            "generic": _field(row, "generic", False),
        }
    rule = rule_name(src.get("rule") or src.get("check") or src.get("detector"))
    return {
        "engine": str(src.get("engine") or "static")[:40],
        "rule": rule,
        "title": clean_evidence(src.get("title") or rule, 180),
        "severity": str(src.get("severity") or "info").lower(),
        "confidence": str(src.get("confidence") or "low").lower(),
        "funds_class": str(src.get("funds_class") or src.get("class") or "other"),
        "evidence": clean_evidence(src.get("evidence") or src.get("description") or ""),
        "function": (str(src.get("function")) if src.get("function") else "")[:80],
        "line": src.get("line") if isinstance(src.get("line"), int) else None,
        "file": str(src.get("file") or "")[:160],
        "contract": str(src.get("contract") or "")[:80],
        "generic": bool(src.get("generic")),
        "defensive_only": True,
    }


def admin_gated(row: dict[str, Any]) -> bool:
    """True when the hit only restates a privileged role gate."""
    blob = " ".join([
        row.get("rule") or "",
        row.get("title") or "",
        row.get("evidence") or "",
        row.get("funds_class") or "",
    ])
    if _UNPROTECTED.search(blob):
        return False
    if row.get("rule") in ZERO_RULES:
        return True
    if row.get("rule") in HIGH_RULES:
        return False
    return bool(_ADMIN_GUARD.search(blob))


def weight_of(row: dict[str, Any]) -> int:
    rule = row.get("rule") or ""
    if row.get("generic") and rule not in HIGH_RULES and rule not in MEDIUM_RULES:
        return 0
    if rule in ZERO_RULES or admin_gated(row):
        return 0
    if rule in HIGH_RULES:
        return HIGH_WEIGHT
    if rule in MEDIUM_RULES:
        return MEDIUM_WEIGHT
    return 0


def _locus(row: dict[str, Any]) -> str:
    if row.get("function"):
        return str(row["function"])
    if row.get("line"):
        return "L%s" % row["line"]
    return row.get("contract") or ""


def finding_key(row: dict[str, Any]) -> str:
    return "%s:%s:%s" % (row.get("engine") or "static", row.get("rule") or "rule", _locus(row) or "0")


def score_static(findings: Optional[list[Any]]) -> dict[str, Any]:
    """Points for a contract. The same rule at the same function counts once."""
    rows: list[dict[str, Any]] = []
    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw in findings or []:
        row = as_row(raw)
        if not row["rule"] and not row["title"]:
            continue
        row["weight"] = weight_of(row)
        row["finding_key"] = finding_key(row)
        dedupe = "%s:%s" % (row["rule"], _locus(row))
        prev = best.get(dedupe)
        if prev is None:
            best[dedupe] = row
            order.append(dedupe)
            continue
        if row["weight"] > prev["weight"]:
            best[dedupe] = row
    points = 0
    for key in order:
        row = best[key]
        if row["weight"] <= 0 or points >= STATIC_CAP:
            row["counted"] = False
            row["weight_applied"] = 0
        else:
            applied = min(row["weight"], STATIC_CAP - points)
            row["counted"] = applied > 0
            row["weight_applied"] = applied
            points += applied
        rows.append(row)
    return {
        "points": points,
        "cap": STATIC_CAP,
        "rows": rows[:40],
        "high": sum(1 for row in rows if row.get("weight") == HIGH_WEIGHT and row.get("counted")),
        "medium": sum(1 for row in rows if row.get("weight") == MEDIUM_WEIGHT and row.get("counted")),
        "ignored": sum(1 for row in rows if not row.get("counted")),
    }
