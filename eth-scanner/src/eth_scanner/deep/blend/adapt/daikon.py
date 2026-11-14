"""Daikon-style likely-invariant mining over fork traces.

Equalities and monotonic series become candidate property names for
Medusa, Echidna, and Halmos. A broken candidate is evidence. It becomes
a drain witness only when the same trace records caller_profit_delta > 0.
"""

from __future__ import annotations

from typing import Any


def _numeric(row: dict[str, Any], key: str) -> float | None:
    if key == "caller_profit_delta":
        return None
    value = row.get(key)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def mine(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Likely invariants that hold on every sample."""
    if len(traces) < 2:
        return []
    keys = sorted({key for row in traces for key in row if _numeric(row, key) is not None})
    found: list[dict[str, Any]] = []
    for left in keys:
        series = [_numeric(row, left) for row in traces]
        if any(value is None for value in series):
            continue
        nums = [float(value) for value in series if value is not None]
        if all(nums[i] <= nums[i + 1] for i in range(len(nums) - 1)):
            found.append({"kind": "monotonic", "left": left, "relation": "non-decreasing"})
        for right in keys:
            if right <= left:
                continue
            pairs = [(_numeric(row, left), _numeric(row, right)) for row in traces]
            if any(pair[0] is None or pair[1] is None for pair in pairs):
                continue
            if all(pair[0] == pair[1] for pair in pairs):
                found.append({
                    "kind": "equality",
                    "left": left,
                    "right": right,
                    "relation": "%s == %s" % (left, right),
                })
    return found


def as_properties(invariants: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Names the three harness styles can hang a check on. No bytecode."""
    out: list[dict[str, str]] = []
    for inv in invariants:
        if inv["kind"] == "equality":
            slug = "%s_eq_%s" % (inv["left"], inv["right"])
        else:
            slug = "%s_monotonic" % inv["left"]
        out.append({
            "slug": slug,
            "medusa": "test_%s" % slug,
            "echidna": "echidna_%s" % slug,
            "halmos": "check_%s" % slug,
        })
    return out


def violations(invariants: list[dict[str, Any]], sample: dict[str, Any]) -> list[dict[str, Any]]:
    """A sample that breaks a mined relation. Profit is recorded, not assumed."""
    try:
        delta = int(sample.get("caller_profit_delta") or 0)
    except (TypeError, ValueError):
        delta = 0
    broken: list[dict[str, Any]] = []
    for inv in invariants:
        holds = True
        if inv["kind"] == "equality":
            left = _numeric(sample, inv["left"])
            right = _numeric(sample, inv["right"])
            holds = left is not None and right is not None and left == right
        if holds:
            continue
        broken.append({
            "relation": inv.get("relation") or inv["kind"],
            "caller_profit_delta": delta if delta > 0 else 0,
            "kind": "drain-proof" if delta > 0 else "evidence-only",
            "label": "drain proof" if delta > 0 else "evidence only",
            "heat_contribution": 0,
        })
    return broken
