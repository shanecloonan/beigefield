"""Match runtime bytecode against known-exploited hashes.

Metadata is stripped before the hash, so a compiler-metadata change still
matches. A near match is a byte-window overlap, not a verdict. Forta alert
names are optional and add no heat. No exploit bytecode is generated.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

EXACT_WEIGHT = 3
NEAR_WEIGHT = 1
CLONE_CAP = 3
NEAR_THRESHOLD = 0.92
_IPFS = "a264697066735822"


def normalize_runtime(code: str) -> str:
    """Lowercase hex without 0x and without Solidity CBOR metadata."""
    hexcode = "".join(ch for ch in (code or "").lower() if ch in "0123456789abcdef")
    if len(hexcode) < 8:
        return hexcode
    try:
        length = int(hexcode[-4:], 16)
    except ValueError:
        length = 0
    start = len(hexcode) - 4 - length * 2
    if 0 < start < len(hexcode) - 4:
        meta = hexcode[start:-4]
        if meta.startswith(("a1", "a2")) or _IPFS in meta[:40]:
            return hexcode[:start]
    idx = hexcode.rfind(_IPFS)
    if idx > 16:
        return hexcode[:idx]
    return hexcode


def runtime_hash(code: str) -> str:
    return hashlib.sha256(normalize_runtime(code).encode("ascii")).hexdigest()


def _histogram(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for i in range(0, len(text) - 1, 2):
        byte = text[i:i + 2]
        counts[byte] = counts.get(byte, 0) + 1
    return counts


def similarity(left: str, right: str) -> float:
    """Byte-histogram overlap of normalized runtime. Identical code is 1."""
    a = normalize_runtime(left)
    b = normalize_runtime(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ha, hb = _histogram(a), _histogram(b)
    keys = set(ha) | set(hb)
    inter = sum(min(ha.get(key, 0), hb.get(key, 0)) for key in keys)
    union = sum(max(ha.get(key, 0), hb.get(key, 0)) for key in keys)
    if not union:
        return 0.0
    return inter / union


def _entry_norm(entry: dict[str, Any]) -> str:
    if entry.get("normalized"):
        return normalize_runtime(str(entry["normalized"]))
    if entry.get("runtime"):
        return normalize_runtime(str(entry["runtime"]))
    return ""


def match_runtime(code: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Best match. Exact hash weight 3, near match weight 1, otherwise 0."""
    norm = normalize_runtime(code)
    digest = hashlib.sha256(norm.encode("ascii")).hexdigest() if norm else ""
    best_id = ""
    best_score = 0.0
    kind = "none"
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "")
        other_hash = str(entry.get("runtime_hash") or "")
        other = _entry_norm(entry)
        if other and other == norm or (other_hash and other_hash == digest):
            return {
                "id": entry_id,
                "kind": "exact",
                "similarity": 1.0,
                "weight": EXACT_WEIGHT,
                "runtime_hash": digest,
                "defensive_only": True,
            }
        if not other:
            continue
        score = similarity(norm, other)
        if score > best_score:
            best_score = score
            best_id = entry_id
            kind = "near" if score >= NEAR_THRESHOLD else "none"
    weight = NEAR_WEIGHT if kind == "near" else 0
    return {
        "id": best_id if kind == "near" else "",
        "kind": kind if weight else "none",
        "similarity": round(best_score, 4),
        "weight": weight,
        "runtime_hash": digest,
        "defensive_only": True,
    }


def load_index(path: Optional[Path] = None) -> list[dict[str, Any]]:
    if path is None:
        path = Path(__file__).resolve().parents[3] / "data" / "exploit_bytecode_index.json"
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("entries") if isinstance(data, dict) else data
    return [row for row in rows or [] if isinstance(row, dict)]


def forta_alerts(
    payload: Any = None,
    *,
    fetch: Optional[Callable[[str], Any]] = None,
) -> dict[str, Any]:
    """Alert names only. Unconfigured stays empty and adds no heat."""
    report: dict[str, Any] = {
        "enabled": False,
        "alerts": [],
        "heat_contribution": 0,
        "note": "Forta is not configured. Set FORTA_ALERTS_URL to a free JSON feed to record alert names.",
    }
    data = payload
    if data is None:
        url = (os.environ.get("FORTA_ALERTS_URL") or "").strip()
        if not url:
            return report
        getter = fetch or _http_json
        try:
            data = getter(url)
        except Exception as exc:  # noqa: BLE001
            report["note"] = "Forta feed was not read (%s)." % type(exc).__name__
            return report
    names: list[str] = []
    rows = data if isinstance(data, list) else (data or {}).get("alerts") if isinstance(data, dict) else []
    for item in rows or []:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("alertId") or "")
        else:
            continue
        name = " ".join(name.split())[:80]
        if name and name not in names:
            names.append(name)
        if len(names) >= 20:
            break
    report["enabled"] = True
    report["alerts"] = names
    report["note"] = "Alert names only. They do not add heat."
    return report


def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "beigefield-eth-scanner"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))
