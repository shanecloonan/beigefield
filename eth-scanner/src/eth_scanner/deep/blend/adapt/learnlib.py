"""LearnLib-style membership queries against a small protocol model.

The fork is the membership oracle: a word of calls is accepted only when
each call's resources are already on the fork. Rejected words are the
under-tested transitions (harvest on a stale oracle, redeem during migrate).
Call names only. No transaction is built.
"""

from __future__ import annotations

from typing import Iterable


# (has_shares, oracle_fresh, migrated) -> call -> next state or None if rejected.
_TRANSITIONS: dict[tuple[bool, bool, bool], dict[str, tuple[bool, bool, bool] | None]] = {}


def _build() -> None:
    if _TRANSITIONS:
        return
    flags = (False, True)
    for shares in flags:
        for fresh in flags:
            for migrated in flags:
                state = (shares, fresh, migrated)
                _TRANSITIONS[state] = {
                    "Vault.deposit": (True, fresh, migrated),
                    "Oracle.setAnswer": (shares, True, migrated),
                    "Oracle.age": (shares, False, migrated),
                    "Keeper.migrate": (shares, fresh, True),
                    "Strategy.harvest": (shares, fresh, migrated) if shares and fresh else None,
                    "Vault.redeem": (False, fresh, migrated) if shares and not migrated else None,
                }


def membership(word: Iterable[str], start: tuple[bool, bool, bool] = (False, False, False)) -> bool:
    """True when every call is enabled by the state the earlier calls left."""
    _build()
    state: tuple[bool, bool, bool] | None = start
    for call in word:
        if state is None:
            return False
        nxt = _TRANSITIONS[state].get(call)
        if nxt is None and call not in _TRANSITIONS[state]:
            return False
        if _TRANSITIONS[state].get(call) is None:
            return False
        state = _TRANSITIONS[state][call]
    return state is not None


def learn() -> dict:
    """Observation table: accepted words, plus the two rejected gaps."""
    _build()
    accepted: list[list[str]] = []
    frontier: list[tuple[tuple[bool, bool, bool], list[str]]] = [((False, False, False), [])]
    seen = {(False, False, False)}
    while frontier and len(accepted) < 16:
        state, word = frontier.pop(0)
        for call, nxt in _TRANSITIONS[state].items():
            if nxt is None or nxt in seen:
                continue
            seen.add(nxt)
            extended = word + [call]
            if membership(extended):
                accepted.append(extended)
                frontier.append((nxt, extended))
    unseen = [
        {"state": "stale_oracle", "call": "Strategy.harvest", "accepted": False,
         "why": "harvest after a stale oracle is not a member"},
        {"state": "migrated", "call": "Vault.redeem", "accepted": False,
         "why": "redeem during migrate is not a member"},
    ]
    return {
        "states": len(seen),
        "accepted": accepted,
        "unseen": unseen,
        "heat_contribution": 0,
    }
