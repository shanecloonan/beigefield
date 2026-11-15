"""Randoop-style feedback-directed sequence growth.

A sequence is extended only by a call whose arguments are already satisfied
by resources an earlier call produced (shares, oracle answers, rewards).
The result is a list of call names. It is not a transaction.
"""

from __future__ import annotations

from typing import Iterable, Optional

from eth_scanner.deep.blend.adapt.syzkaller import PROTOCOL, Method


def feedback_sequences(
    methods: Optional[Iterable[Method]] = None,
    *,
    limit: int = 8,
) -> list[list[str]]:
    """Grow sequences one call at a time. New resources are the feedback."""
    pool = list(PROTOCOL if methods is None else methods)
    frontier: list[tuple[list[Method], set[str]]] = [([], set())]
    grown: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    while frontier and len(grown) < limit:
        seq, have = frontier.pop(0)
        ready = [
            method for method in pool
            if method not in seq and set(method.consumes).issubset(have)
        ]
        # Prefer a call that produces a resource this sequence does not have yet.
        ready.sort(key=lambda method: (-len(set(method.produces) - have), method.label))
        for method in ready[:2]:
            nxt = seq + [method]
            labels = tuple(step.label for step in nxt)
            if labels in seen:
                continue
            seen.add(labels)
            grown.append(list(labels))
            frontier.append((nxt, have | set(method.produces)))
            if len(grown) >= limit:
                break
    return grown
