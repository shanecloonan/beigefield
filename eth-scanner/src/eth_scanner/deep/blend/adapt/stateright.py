"""Stateright / Coyote style interleaving of a few actors.

Attacker, victim, keeper, and oracle-updater each take one call. The
scheduler enumerates interleavings and picks a seed-stable slice so a
replay repeats the same schedule. Schedules are call names, not transactions.
"""

from __future__ import annotations

import itertools
from typing import Sequence


ACTORS = ("attacker", "victim", "keeper", "oracle")
CALLS = ("Vault.deposit", "Oracle.setAnswer", "Strategy.harvest", "Vault.redeem")


def _orders() -> list[tuple[str, ...]]:
    return sorted(set(itertools.permutations(CALLS)))


def interleavings(seed: int, width: int = 4) -> list[list[dict[str, str]]]:
    """Seed-stable slice of the actor interleavings."""
    orders = _orders()
    if not orders:
        return []
    start = abs(int(seed)) % len(orders)
    chosen = [orders[(start + i) % len(orders)] for i in range(max(1, width))]
    schedules: list[list[dict[str, str]]] = []
    for order in chosen:
        schedules.append([
            {"actor": ACTORS[i % len(ACTORS)], "call": call}
            for i, call in enumerate(order)
        ])
    return schedules


def replay_matches(seed: int, schedule: Sequence[dict[str, str]]) -> bool:
    """The same seed yields the same first schedule."""
    rows = interleavings(seed, width=1)
    if not rows:
        return False
    return list(schedule) == rows[0]
