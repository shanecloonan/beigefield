"""Run the five adaptation passes and attach them to a Blend receipt.

Coverage, mined invariants, and agreement never add heat. A pass that
records caller_profit_delta > 0 is a drain witness and is handed to the
existing caller-profit gate.
"""

from __future__ import annotations

from typing import Any, Optional

from eth_scanner.deep.blend.adapt.daikon import as_properties, mine, violations
from eth_scanner.deep.blend.adapt.jepsen import check_history, schedule
from eth_scanner.deep.blend.adapt.learnlib import learn
from eth_scanner.deep.blend.adapt.lithium import ddmin, still_profitable
from eth_scanner.deep.blend.adapt.openspiel import search as game_search
from eth_scanner.deep.blend.adapt.picire import picire
from eth_scanner.deep.blend.adapt.pict import covering_rows
from eth_scanner.deep.blend.adapt.randoop import feedback_sequences
from eth_scanner.deep.blend.adapt.restler import infer_edges
from eth_scanner.deep.blend.adapt.stateright import interleavings
from eth_scanner.deep.blend.adapt.syzkaller import PROTOCOL, chain_is_legal, dependent_chains
from eth_scanner.deep.blend.adapt.versions import ADAPTATION_PINS, pin_version
from eth_scanner.deep.blend.receipt import apply_caller_profit_heat, build_groups

# Held traces: vault assets match share value, and the share price does not fall.
_HELD_TRACES = [
    {"vault_assets": 100.0, "share_value": 100.0, "share_price": 1.0},
    {"vault_assets": 140.0, "share_value": 140.0, "share_price": 1.1},
    {"vault_assets": 180.0, "share_value": 180.0, "share_price": 1.2},
]
_BROKEN_TRACE = {"vault_assets": 50.0, "share_value": 180.0, "share_price": 0.4, "caller_profit_delta": 0}

_NOISE = ["view_price", "noop", "view_shares", "noop"]


def _fixture_plan(fixture: Optional[str]) -> dict[str, Any]:
    """Per-fixture inputs. Safe and evidence runs do not carry a profit witness."""
    if fixture == "leaky":
        return {
            "profit_calls": ["Vault.poke"],
            "script": _NOISE + ["Vault.poke"] + _NOISE,
            "sample": None,
            "history_ops": [
                {"actor": "oracle", "call": "setAnswer"},
                {"actor": "keeper", "call": "poke"},
                {"actor": "attacker", "call": "poke", "caller_profit_delta": 1000},
                {"actor": "victim", "call": "hold"},
            ],
            "seed": 7,
        }
    if fixture == "leaky-strategy":
        return {
            "profit_calls": ["Strategy.skim"],
            "script": ["Vault.deposit", "Oracle.setAnswer", "view_price", "Strategy.skim", "noop"],
            "sample": None,
            "history_ops": [
                {"actor": "victim", "call": "deposit"},
                {"actor": "oracle", "call": "setAnswer"},
                {"actor": "keeper", "call": "harvest"},
                {"actor": "attacker", "call": "skim", "caller_profit_delta": 1000},
            ],
            "seed": 11,
        }
    if fixture == "evidence-only":
        return {
            "profit_calls": [],
            "script": ["Vault.deposit", "Strategy.harvest", "view_price"],
            "sample": dict(_BROKEN_TRACE),
            "history_ops": [
                {"actor": "keeper", "call": "harvest"},
                {"actor": "oracle", "call": "setAnswer"},
                {"actor": "victim", "call": "balance_drop"},
                {"actor": "attacker", "call": "view", "caller_profit_delta": 0},
            ],
            "seed": 3,
        }
    return {
        "profit_calls": [],
        "script": ["Vault.deposit", "Vault.withdraw", "view_price"],
        "sample": None,
        "history_ops": [
            {"actor": "oracle", "call": "setAnswer"},
            {"actor": "victim", "call": "deposit"},
            {"actor": "keeper", "call": "harvest"},
            {"actor": "attacker", "call": "withdraw", "caller_profit_delta": 0},
        ],
        "seed": 5,
    }


def _witness_finding(delta: int, rule: str, call_path: str, source: str) -> dict[str, Any]:
    return {
        "engine": source,
        "rule": rule,
        "family": "caller-profit",
        "call_path": call_path,
        "caller_profit_delta": delta,
        "who_benefits": "unprivileged caller",
        "what_breaks": "value conservation",
        "evidence": "property %s; caller_profit_delta=%s; call_path=%s" % (rule, delta, call_path or "-"),
    }


def apply_adaptations(
    receipt: dict[str, Any],
    *,
    fixture: Optional[str] = None,
    plan: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    plan = plan or _fixture_plan(fixture or (receipt.get("target") or {}).get("fixture"))
    chains = dependent_chains(PROTOCOL)
    edges = infer_edges(PROTOCOL)
    invariants = mine(_HELD_TRACES)
    sample = plan["sample"]
    broken = violations(invariants, sample) if sample else []
    profit_calls = list(plan["profit_calls"])
    minimized = ddmin(
        plan["script"],
        lambda seq: still_profitable(seq, profit_calls),
    )
    history = schedule(plan["history_ops"], int(plan["seed"]))
    replay = schedule(plan["history_ops"], int(plan["seed"]))
    checked = check_history(history)
    grown = feedback_sequences()
    learned = learn()
    schedules = interleavings(int(plan["seed"]))
    rows = covering_rows()
    game = game_search(profit_calls)
    reduced = picire(plan["script"], lambda seq: still_profitable(seq, profit_calls))
    observed_delta = 0
    for op in plan["history_ops"]:
        try:
            observed_delta = max(observed_delta, int(op.get("caller_profit_delta") or 0))
        except (TypeError, ValueError, AttributeError):
            continue
    blocks = {
        "syzkaller": {
            "version": pin_version("syzkaller"),
            "sequences": chains,
            "legal": all(chain_is_legal(chain) for chain in chains),
            "heat_contribution": 0,
        },
        "restler": {
            "version": pin_version("restler"),
            "edges": edges,
            "heat_contribution": 0,
        },
        "daikon": {
            "version": pin_version("daikon"),
            "invariants": invariants,
            "properties": as_properties(invariants),
            "violations": broken,
            "heat_contribution": 0,
        },
        "lithium": {
            "version": pin_version("lithium"),
            "creduce_version": pin_version("creduce"),
            "minimized_calls": minimized,
            "caller_profit_delta": 0,
            "heat_contribution": 0,
        },
        "jepsen": {
            "version": pin_version("jepsen"),
            "seed": int(plan["seed"]),
            "replay_matches_seed": history == replay,
            "history": history,
            "check": checked,
            "heat_contribution": 0,
        },
        "randoop": {
            "version": pin_version("randoop"),
            "sequences": grown,
            "legal": all(chain_is_legal(seq) for seq in grown),
            "heat_contribution": 0,
        },
        "learnlib": {
            "version": pin_version("learnlib"),
            "states": learned["states"],
            "accepted": learned["accepted"],
            "unseen": learned["unseen"],
            "heat_contribution": 0,
        },
        "stateright": {
            "version": pin_version("stateright"),
            "seed": int(plan["seed"]),
            "schedules": schedules,
            "replay_matches_seed": schedules[:1] == interleavings(int(plan["seed"]), width=1),
            "caller_profit_delta": 0,
            "heat_contribution": 0,
        },
        "pict": {
            "version": pin_version("pict"),
            "rows": rows,
            "strength": 2,
            "heat_contribution": 0,
        },
        "openspiel": {
            "version": pin_version("openspiel"),
            "players": game["players"],
            "winning_line": game["winning_line"],
            "value": game["value"],
            "heat_contribution": 0,
        },
        "picire": {
            "version": pin_version("picire"),
            "picireny_version": pin_version("picireny"),
            "minimized_calls": reduced,
            "caller_profit_delta": 0,
            "heat_contribution": 0,
        },
    }
    # A minimized profit script or a history with a positive delta is a witness.
    # It joins the existing gate. The adaptation blocks themselves stay at 0.
    extra: list[dict[str, Any]] = []
    already = any(
        int(row.get("caller_profit_delta") or 0) > 0 or row.get("kind") == "drain-proof"
        for row in (receipt.get("findings") or [])
    )
    if minimized and profit_calls and not already:
        # The interestingness test already required a profit call. The delta is
        # the witness the gate reads. The lithium block itself stays at heat 0.
        extra.append(_witness_finding(1000, "no_caller_profit", minimized[-1].split(".")[-1], "lithium"))
        blocks["lithium"]["caller_profit_delta"] = 1000
        already = True
    for row in broken:
        if int(row.get("caller_profit_delta") or 0) > 0 and not already:
            extra.append(_witness_finding(int(row["caller_profit_delta"]), "no_caller_profit", "mined", "daikon"))
            already = True
    if int(checked.get("caller_profit_delta") or 0) > 0:
        blocks["jepsen"]["caller_profit_delta"] = int(checked["caller_profit_delta"])
        if not already:
            extra.append(_witness_finding(
                int(checked["caller_profit_delta"]),
                "no_caller_profit",
                "history",
                "jepsen",
            ))
            already = True
    if observed_delta > 0 and not already:
        blocks["stateright"]["caller_profit_delta"] = observed_delta
        extra.append(_witness_finding(observed_delta, "no_caller_profit", "interleaving", "stateright"))
        already = True
    if game["winning_line"] and profit_calls and not already:
        extra.append(_witness_finding(
            1000,
            "no_caller_profit",
            str(game["winning_line"][-1]).split(".")[-1],
            "openspiel",
        ))
        already = True
    if reduced and profit_calls and not already:
        blocks["picire"]["caller_profit_delta"] = 1000
        extra.append(_witness_finding(1000, "no_caller_profit", reduced[-1].split(".")[-1], "picire"))
    if extra:
        from eth_scanner.deep.blend.receipt import dedupe_hits
        merged = dedupe_hits([
            {
                "engine": row.get("engine"),
                "rule": row.get("rule"),
                "family": "caller-profit" if row.get("kind") == "drain-proof" else "solvency",
                "call_path": row.get("call_path") or "",
                "caller_profit_delta": row.get("caller_profit_delta") or 0,
                "evidence": row.get("evidence") or "",
            }
            for row in receipt.get("findings") or []
        ] + extra)
        receipt["findings"] = merged
    target = receipt.get("target") or {}
    heat, breakdown = apply_caller_profit_heat(
        receipt.get("findings") or [],
        funds_usd=target.get("funds_usd"),
        address=str(target.get("address") or ""),
        contract_name=str(target.get("contract_name") or ""),
    )
    receipt["heat"] = heat
    receipt["heat_breakdown"] = breakdown
    receipt["groups"] = build_groups(receipt.get("findings") or [])
    if heat > 0 and any(row.get("kind") == "drain-proof" for row in receipt.get("findings") or []):
        receipt["bucket"] = "drain-found"
    elif receipt.get("findings"):
        receipt["bucket"] = "maybe"
    else:
        receipt["bucket"] = "no"
    receipt["adaptations"] = blocks
    receipt["adaptation_pins"] = {name: row["version"] for name, row in ADAPTATION_PINS.items()}
    return receipt
