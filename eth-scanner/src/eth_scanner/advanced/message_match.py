"""Compare message ids that were already observed.

An id is a 32-byte hex word. The same id on two chains is a lead. A
longer word is dropped, so calldata is not stored. Nothing is replayed
and nothing is sent. Heat stays 0.
"""

from __future__ import annotations

from typing import Any, Optional

from eth_scanner.chains.registry import normalize_chain


def _message_id(value: object) -> Optional[str]:
    text = str(value or "").strip().lower()
    if len(text) != 66 or not text.startswith("0x"):
        return None
    if any(ch not in "0123456789abcdef" for ch in text[2:]):
        return None
    return text


def message_match(seen: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, set[str]] = {}
    dropped = 0
    for row in seen or []:
        if not isinstance(row, dict):
            dropped += 1
            continue
        ident = _message_id(row.get("id"))
        if ident is None:
            dropped += 1
            continue
        grouped.setdefault(ident, set()).add(normalize_chain(row.get("chain")))
    matches = []
    for ident in sorted(grouped):
        chains = sorted(grouped[ident])
        matches.append({
            "id": ident,
            "chains": chains,
            "relation": "seen-on-multiple-chains" if len(chains) > 1 else "seen-once",
            "heat_contribution": 0,
        })
    if not matches:
        return {
            "status": "skipped",
            "reason": "no message ids",
            "matches": [],
            "dropped": dropped,
            "heat_contribution": 0,
        }
    return {
        "status": "ok",
        "reason": "",
        "matches": matches,
        "multiple": sum(1 for row in matches if row["relation"] == "seen-on-multiple-chains"),
        "dropped": dropped,
        "heat_contribution": 0,
        "note": "Ids are compared. Messages are not replayed and calldata is not stored.",
    }
