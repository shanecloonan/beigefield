"""Jepsen-style multi-actor history check on a simulated fork.

Actors are attacker, victim, keeper, and oracle. Replay is seed-stable.
An ordering or balance note is evidence. Heat stays at zero unless the
attacker ends ahead by a recorded caller_profit_delta.
"""

from __future__ import annotations

import random
from typing import Any


ACTORS = ("attacker", "victim", "keeper", "oracle")


def schedule(ops: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """Deterministic shuffle. The same seed replays the same history."""
    rng = random.Random(int(seed))
    ordered = list(ops)
    rng.shuffle(ordered)
    history: list[dict[str, Any]] = []
    for index, op in enumerate(ordered):
        history.append({
            "index": index,
            "actor": str(op.get("actor") or ""),
            "call": str(op.get("call") or ""),
            "caller_profit_delta": int(op.get("caller_profit_delta") or 0),
        })
    return history


def check_history(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Balance and ordering notes. No transaction is built."""
    notes: list[dict[str, Any]] = []
    attacker_delta = 0
    oracle_at: list[int] = []
    keeper_at: list[int] = []
    for event in history:
        if event["actor"] == "attacker":
            attacker_delta += int(event.get("caller_profit_delta") or 0)
        if event["actor"] == "oracle":
            oracle_at.append(int(event["index"]))
        if event["actor"] == "keeper":
            keeper_at.append(int(event["index"]))
    if keeper_at and oracle_at and min(oracle_at) > min(keeper_at):
        notes.append({
            "kind": "ordering",
            "summary": "keeper acted before the oracle answer in this history",
            "caller_profit_delta": attacker_delta if attacker_delta > 0 else 0,
            "label": "drain proof" if attacker_delta > 0 else "evidence only",
        })
    if attacker_delta > 0:
        notes.append({
            "kind": "balance",
            "summary": "attacker ended ahead of their start on the simulated history",
            "caller_profit_delta": attacker_delta,
            "label": "drain proof",
        })
    elif any(event["actor"] == "victim" and event["call"] == "balance_drop" for event in history):
        notes.append({
            "kind": "balance",
            "summary": "victim balance moved with no attacker profit in this history",
            "caller_profit_delta": 0,
            "label": "evidence only",
        })
    return {
        "anomalies": notes,
        "caller_profit_delta": attacker_delta if attacker_delta > 0 else 0,
        "kind": "drain-proof" if attacker_delta > 0 else ("evidence-only" if notes else "held"),
        "label": "drain proof" if attacker_delta > 0 else "evidence only",
        "heat_contribution": 0,
    }
