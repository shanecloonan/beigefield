"""OpenSpiel-style search over a four-player protocol game.

Players are the attacker, the user, the keeper, and the oracle updater.
A turn is a resource-legal call. A winning line is the shortest legal
sequence that still contains a caller-profit witness. With no witness the
search returns no extracting strategy. Lines are call names, not transactions.
"""

from __future__ import annotations

from typing import Optional, Sequence

from eth_scanner.deep.blend.adapt.syzkaller import PROTOCOL, Method, chain_is_legal


PLAYERS = ("attacker", "user", "keeper", "oracle")


def _by_label() -> dict[str, Method]:
    return {method.label: method for method in PROTOCOL}


def search(profit_calls: Sequence[str], *, limit: int = 6) -> dict:
    """Depth-limited search. Value is 0 unless a witness call is reached."""
    wanted = [call for call in profit_calls if call]
    methods = list(PROTOCOL)
    best: Optional[list[str]] = None
    frontier: list[list[Method]] = [[]]
    while frontier:
        seq = frontier.pop(0)
        if len(seq) >= limit:
            continue
        have = {produced for step in seq for produced in step.produces}
        for method in methods:
            if method in seq or not set(method.consumes).issubset(have):
                continue
            nxt = seq + [method]
            labels = [step.label for step in nxt]
            if any(call in labels for call in wanted):
                if best is None or len(labels) < len(best):
                    best = labels
                continue
            frontier.append(nxt)
    if best and not chain_is_legal(best, methods):
        best = None
    return {
        "players": list(PLAYERS),
        "winning_line": best,
        "value": 1 if best else 0,
        "heat_contribution": 0,
    }
