"""Compare two Sourcify storage layouts for an unsafe upgrade.

This is our own diff. OpenZeppelin is not imported or vendored. A variable
that is removed, moved, or retyped is a clash. A variable appended after the
previous layout, or written into a gap that later variables did not leave,
is safe. A clash adds 3 heat. A clean diff adds 0.
"""

from __future__ import annotations

from typing import Any, Optional


def compare_layouts(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> dict[str, Any]:
    """Diff two layouts. No chain calls."""
    from eth_scanner.heat import evidence_heat

    old = _index(before)
    new = _index(after)
    clashes: list[dict[str, str]] = []
    for label, row in old.items():
        if _gap(label):
            continue
        nxt = new.get(label)
        if nxt is None:
            clashes.append({"kind": "removed", "label": label, "detail": "slot %s" % row["slot"]})
            continue
        if row["slot"] != nxt["slot"] or row["offset"] != nxt["offset"]:
            clashes.append({
                "kind": "moved",
                "label": label,
                "detail": "slot %s -> %s" % (row["slot"], nxt["slot"]),
            })
        elif row["type"] != nxt["type"]:
            clashes.append({
                "kind": "retyped",
                "label": label,
                "detail": "%s -> %s" % (row["type"], nxt["type"]),
            })
    occupied = {
        (row["slot"], row["offset"]): label
        for label, row in old.items()
        if not _gap(label) and label in new and new[label]["slot"] == row["slot"]
    }
    for label, row in new.items():
        if label in old or _gap(label):
            continue
        owner = occupied.get((row["slot"], row["offset"]))
        if owner:
            clashes.append({
                "kind": "overlap",
                "label": label,
                "detail": "shares slot %s with %s" % (row["slot"], owner),
            })
    report = {
        "status": "clash" if clashes else "held",
        "ran": True,
        "clashes": clashes[:8],
        "heat": 0,
        "heat_contribution": 0,
        "note": (
            "A storage variable was removed, moved, or retyped."
            if clashes
            else "The storage layout appends safely."
        ),
    }
    heat, breakdown = evidence_heat(funds_usd=None, invariant_results=[], upgrade=report)
    report["heat"] = heat
    report["heat_breakdown"] = {
        "upgrade": breakdown.get("upgrade"),
        "upgrade_evidence": breakdown.get("upgrade_evidence"),
        "total": breakdown.get("total"),
    }
    return report


def _index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        if not label or label in indexed:
            continue
        slot = _slot_number(row.get("slot"))
        if slot is None:
            continue
        try:
            offset = int(row.get("offset") or 0)
        except (TypeError, ValueError):
            offset = 0
        indexed[label] = {
            "slot": slot,
            "offset": offset,
            "type": str(row.get("type") or "").strip().lower(),
        }
    return indexed


def _gap(label: str) -> bool:
    return label.endswith("__gap") or label == "__gap"


def _slot_number(raw: Any) -> Optional[int]:
    text = str(raw if raw is not None else "").strip().lower()
    if not text:
        return None
    try:
        if text.startswith("0x"):
            return int(text, 16)
        if text.isdigit():
            return int(text)
        return int(text, 16)
    except ValueError:
        return None
