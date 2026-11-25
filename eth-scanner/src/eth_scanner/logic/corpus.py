"""Source-pattern detectors drawn from SWC ids and public incident families.

Patterns are shapes. Incident names stay names. No writeup and no exploit
sequence is stored. A match is evidence for heat, not a verdict.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

_MAX_CHARS = 400_000
_GUARD = re.compile(r"onlyOwner|onlyRole|initializer", re.I)

# Shape detectors. The rule ids are the static-evidence allowlist.
PATTERNS: tuple[dict[str, Any], ...] = (
    {
        "swc": "SWC-105",
        "rule": "unprotected-initializer",
        "family": "defihacklabs-unprotected-init",
        "pattern": re.compile(r"function\s+initialize\s*\([^)]*\)\s*(public|external)\b", re.I),
    },
    {
        "swc": "SWC-106",
        "rule": "public-selfdestruct",
        "family": "swc-unprotected-selfdestruct",
        "pattern": re.compile(r"selfdestruct\s*\(", re.I),
    },
    {
        "swc": "SWC-112",
        "rule": "delegatecall-user-target",
        "family": "swc-delegatecall",
        "pattern": re.compile(r"\.delegatecall\s*\(", re.I),
    },
    {
        "swc": "SWC-115",
        "rule": "tx-origin-auth",
        "family": "swc-tx-origin",
        "pattern": re.compile(r"tx\.origin", re.I),
    },
    {
        "swc": "SWC-107",
        "rule": "reentrancy-eth",
        "family": "audit-reentrancy-eth",
        "pattern": re.compile(r"\.call\s*\{[^}]*value\s*:", re.I),
    },
    {
        "swc": "",
        "rule": "spot-price-value",
        "family": "audit-oracle-spot-only",
        "pattern": re.compile(r"getReserves\s*\(\s*\)[\s\S]{0,400}?\.transfer\s*\(", re.I),
    },
    {
        "swc": "",
        "rule": "share-inflation-empty",
        "family": "defihacklabs-erc4626-inflation",
        "pattern": re.compile(r"totalSupply\s*\(\s*\)\s*==\s*0[\s\S]{0,400}?_mint\s*\(", re.I),
    },
    {
        "swc": "",
        "rule": "unprotected-upgrade",
        "family": "defihacklabs-proxy-admin-takeover",
        "pattern": re.compile(r"function\s+(upgradeTo|upgradeToAndCall|changeAdmin)\s*\([^)]*\)\s*(public|external)\b", re.I),
    },
)

_NAME_FAMILIES = (
    ("share-inflation-empty", ("inflation", "erc4626", "first depositor")),
    ("spot-price-value", ("oracle", "price manip", "spot price")),
    ("reentrancy-eth", ("reentrancy", "reentrant")),
    ("unprotected-initializer", ("uninitialized", "initializer")),
)


def incident_family(name: str) -> str:
    """Map a public incident title onto a pattern family. The title is not a recipe."""
    text = (name or "").lower()
    for rule, words in _NAME_FAMILIES:
        if any(word in text for word in words):
            return rule
    return ""


def catalog_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "known_vulnerable_clones.json"


def load_families(path: Optional[Path] = None) -> list[dict[str, str]]:
    """Titles and ids from the curated catalog. Markers are not executed."""
    raw_path = path or catalog_path()
    try:
        data = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = []
    for entry in data.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        rows.append({
            "id": str(entry.get("id") or ""),
            "title": str(entry.get("title") or ""),
            "severity": str(entry.get("severity") or ""),
        })
    return rows


def scan_source(source: str) -> list[dict[str, Any]]:
    """Return normalized finding dicts. Guarded matches are dropped."""
    text = source or ""
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS]
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for spec in PATTERNS:
        match = spec["pattern"].search(text)
        if match is None:
            continue
        window = text[max(0, match.start() - 180):match.end() + 40]
        if _GUARD.search(window):
            continue
        rule = str(spec["rule"])
        if rule in seen:
            continue
        seen.add(rule)
        found.append({
            "engine": "corpus",
            "rule": rule,
            "title": spec["swc"] or spec["family"],
            "severity": "high",
            "confidence": "high" if rule != "tx-origin-auth" else "medium",
            "funds_class": "other",
            "evidence": "pattern %s (%s)" % (spec["family"], spec["swc"] or "family"),
            "function": "",
            "defensive_only": True,
        })
    return found


def corpus_report(source: str) -> dict[str, Any]:
    from eth_scanner.logic.static_norm import score_static

    rows = scan_source(source)
    scored = score_static(rows)
    return {
        "findings": scored["rows"],
        "corpus_evidence": scored["points"],
        "families_loaded": len(load_families()),
        "note": "pattern match only; incident writeups are not stored",
    }
