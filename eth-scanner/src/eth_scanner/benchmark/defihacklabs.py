"""DeFiHackLabs incident names and dates. No writeups and no proof-of-concept code.

The public README is parsed for the bracketed date and protocol name only.
The anchor text, file paths, and any reproduced steps are dropped. A failed
fetch returns an empty index and adds no heat. This index does not score
the scanner and does not change the labeled benchmark.
"""

from __future__ import annotations

import re
import urllib.request
from typing import Any, Callable, Optional

README_URL = "https://raw.githubusercontent.com/SunWeb3Sec/DeFiHackLabs/main/README.md"
_ROW = re.compile(r"^\[(\d{8})\s+([^\]]+)\]")
_UNSAFE_NAME = re.compile(r"\.sol\b|function\s|calldata|0x[0-9a-f]{8,}", re.I)


def incident_family(name: str) -> str:
    """Pattern family for a public title. Delegates to the corpus map. Still not a recipe."""
    from eth_scanner.logic.corpus import incident_family as _family
    return _family(name)


def parse_index(text: str) -> list[dict[str, str]]:
    """Keep date and name. Drop everything after the closing bracket."""
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in (text or "").splitlines():
        match = _ROW.match(line.strip())
        if not match:
            continue
        raw_date, name = match.group(1), match.group(2).strip()
        if _UNSAFE_NAME.search(name) or not _valid_date(raw_date):
            continue
        date = "%s-%s-%s" % (raw_date[0:4], raw_date[4:6], raw_date[6:8])
        key = (date, name.lower())
        if key in seen:
            continue
        seen.add(key)
        rows.append({"date": date, "name": name})
    return rows


def index_report(
    labeled: Optional[list[dict[str, Any]]] = None,
    *,
    text: Optional[str] = None,
    fetch: Optional[Callable[[], str]] = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "metadata_only": True,
        "heat_contribution": 0,
        "incidents": 0,
        "labeled_affected": 0,
        "matched_affected": 0,
        "degraded": False,
        "note": "Names and dates only. Writeups and proof-of-concept files are not stored.",
    }
    if text is None:
        try:
            text = (fetch or _fetch_readme)()
        except Exception as exc:  # noqa: BLE001 — a missing index is not a scan failure
            report["degraded"] = True
            report["note"] = "The incident index was not read (%s)." % type(exc).__name__
            return report
    rows = parse_index(text)
    report["incidents"] = len(rows)
    if not rows:
        report["degraded"] = True
        report["note"] = "No incident names were parsed. Nothing was stored."
        return report
    affected = [
        row for row in (labeled or [])
        if isinstance(row, dict) and str(row.get("label") or "").lower() == "affected"
    ]
    names = {row["name"].lower() for row in rows}
    matched = [row for row in affected if str(row.get("name") or "").lower() in names]
    report["labeled_affected"] = len(affected)
    report["matched_affected"] = len(matched)
    families: dict[str, int] = {}
    for row in rows:
        family = incident_family(row["name"])
        if not family:
            continue
        families[family] = families.get(family, 0) + 1
    report["families"] = families
    return report


def _fetch_readme() -> str:
    req = urllib.request.Request(README_URL, headers={"User-Agent": "beigefield-eth-scanner"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _valid_date(raw: str) -> bool:
    month = int(raw[4:6])
    day = int(raw[6:8])
    return 1 <= month <= 12 and 1 <= day <= 31
