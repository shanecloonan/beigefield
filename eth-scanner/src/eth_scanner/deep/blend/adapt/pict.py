"""PICT-style pairwise covering array over the protocol factors.

Rows are combinations of actor, method, amount bucket, oracle freshness,
and approval state. They name a case to replay. They are not transactions.
"""

from __future__ import annotations

from typing import Iterable


FACTORS: dict[str, tuple[str, ...]] = {
    "actor": ("attacker", "victim", "keeper", "oracle"),
    "method": ("deposit", "harvest", "redeem", "setAnswer"),
    "amount": ("dust", "unit", "large"),
    "oracle": ("fresh", "stale"),
    "approval": ("none", "approved", "harvested"),
}


def _pairs(names: list[str]) -> list[tuple[str, str]]:
    return [(names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))]


def covering_rows(strength: int = 2, *, limit: int = 48) -> list[dict[str, str]]:
    """Greedy covering array. strength 2 covers pairs; 3 covers triples."""
    names = list(FACTORS)
    values = {name: FACTORS[name] for name in names}
    if strength <= 2:
        needed = []
        for left, right in _pairs(names):
            for a in values[left]:
                for b in values[right]:
                    needed.append((left, a, right, b))
    else:
        needed = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                for k in range(j + 1, len(names)):
                    a, b, c = names[i], names[j], names[k]
                    for va in values[a]:
                        for vb in values[b]:
                            for vc in values[c]:
                                needed.append((a, va, b, vb, c, vc))
    uncovered = set(needed)
    rows: list[dict[str, str]] = []

    def covers(row: dict[str, str], item: tuple) -> bool:
        if len(item) == 4:
            left, a, right, b = item
            return row[left] == a and row[right] == b
        a, va, b, vb, c, vc = item
        return row[a] == va and row[b] == vb and row[c] == vc

    while uncovered and len(rows) < limit:
        best: dict[str, str] | None = None
        best_hits = 0
        # One candidate per still-uncovered interaction, filled with the first level of the other factors.
        for item in list(uncovered)[:80]:
            row = {name: values[name][0] for name in names}
            if len(item) == 4:
                row[item[0]] = item[1]
                row[item[2]] = item[3]
            else:
                row[item[0]] = item[1]
                row[item[2]] = item[3]
                row[item[4]] = item[5]
            hits = sum(1 for pending in uncovered if covers(row, pending))
            if hits > best_hits:
                best = row
                best_hits = hits
        if best is None or best_hits == 0:
            break
        rows.append(best)
        uncovered = {item for item in uncovered if not covers(best, item)}
    return rows


def covers_pairs(rows: Iterable[dict[str, str]]) -> bool:
    """Every actor × method pair appears in some row."""
    found = {(row["actor"], row["method"]) for row in rows}
    for actor in FACTORS["actor"]:
        for method in FACTORS["method"]:
            if (actor, method) not in found:
                return False
    return True
