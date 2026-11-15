"""Picire / Picireny style hierarchical reduction of a call script.

Coarse chunks are removed first. At each chunk size every candidate
removal is considered together, then the shortest script that is still
interesting is kept. Interesting means the fork still shows
caller_profit_delta > 0. The predicate is supplied by the caller.
The script is call names, not a transaction.
"""

from __future__ import annotations

from typing import Callable, Sequence


def picire(sequence: Sequence[str], interesting: Callable[[list[str]], bool]) -> list[str]:
    """1-minimal subsequence. Empty when the input is not interesting."""
    data = list(sequence)
    if not data or not interesting(data):
        return []
    granularity = max(1, len(data) // 2)
    while True:
        changed = True
        while changed:
            changed = False
            candidates: list[list[str]] = []
            for start in range(0, len(data), granularity):
                trial = data[:start] + data[start + granularity:]
                if trial and interesting(trial):
                    candidates.append(trial)
            if not candidates:
                continue
            shortest = min(candidates, key=len)
            if len(shortest) < len(data):
                data = shortest
                changed = True
        if granularity == 1:
            break
        granularity = max(1, granularity // 2)
    return data
