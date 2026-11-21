"""Order contracts from lead counts. The order never changes heat.

The weight is 1 only when labeled incidents have a higher mean lead count
than labeled safe contracts. Otherwise the weight is 0 and the order is
the address order, so a noisy detector does not promote anything.
"""

from __future__ import annotations

from typing import Any


def _mean(rows: list[dict[str, Any]], label: str) -> float:
    vals = [int(row.get("leads") or 0) for row in rows if row.get("label") == label]
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def learn_order(
    train: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    weight = 1 if _mean(train, "affected") > _mean(train, "safe") else 0
    ordered = sorted(
        rows,
        key=lambda row: (
            -(weight * int(row.get("leads") or 0)),
            str(row.get("chain") or "ethereum"),
            str(row.get("address") or ""),
        ),
    )
    return {
        "weight": weight,
        "order": [
            {
                "chain": str(row.get("chain") or "ethereum"),
                "address": str(row.get("address") or ""),
                "leads": int(row.get("leads") or 0),
                "heat_contribution": 0,
            }
            for row in ordered
        ],
        "heat_contribution": 0,
        "note": "Ordering only. Heat stays 0.",
    }
