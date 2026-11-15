"""Cross-layer corroboration. Raises a drain-probability prior, never heat.

Agreeing facts, properties, symbolic results, fuzzer evidence, mutation
survivors, and the eleven adaptation passes move the prior used to order
work. A caller-profit witness is returned so the existing anvil-fork gate
can see it. This function does not call the gate and does not set heat.
"""

from __future__ import annotations

from typing import Any


def _signals(block: dict[str, Any]) -> bool:
    if not isinstance(block, dict):
        return False
    if block.get("facts") or block.get("findings") or block.get("selected"):
        return True
    if int(block.get("counterexample") or 0) or block.get("counterexample") is True:
        return True
    if block.get("survivors") or block.get("killed"):
        return True
    status = str(block.get("status") or "")
    return status == "ok"


def fuse(
    *,
    findings: list[dict[str, Any]],
    layers: dict[str, Any],
    adaptations: dict[str, Any],
) -> dict[str, Any]:
    agreeing: list[str] = []
    for name, block in (layers or {}).items():
        if name == "fusion":
            continue
        if _signals(block if isinstance(block, dict) else {}):
            agreeing.append(name)
    for name, block in (adaptations or {}).items():
        if isinstance(block, dict) and (
            block.get("sequences") or block.get("invariants") or block.get("violations")
            or block.get("edges") or block.get("rows") or block.get("schedules")
            or block.get("minimized_calls") or block.get("accepted")
        ):
            agreeing.append("adapt:%s" % name)
    proofs = [
        row for row in findings or []
        if row.get("kind") == "drain-proof" and int(row.get("caller_profit_delta") or 0) > 0
    ]
    evidence = [row for row in findings or [] if row.get("kind") != "drain-proof"]
    prior = 0.05
    facts = (layers or {}).get("facts") if isinstance((layers or {}).get("facts"), dict) else {}
    if facts.get("shape") in {"erc4626", "erc20", "vault"}:
        prior += 0.12
    if any(str(row.get("kind")) == "abstract-bound" for row in (facts.get("facts") or [])):
        prior += 0.08
    prior += min(0.24, 0.04 * len([name for name in agreeing if not name.startswith("adapt:")]))
    if evidence:
        prior += 0.1
    if proofs:
        prior += 0.35
    # Without a caller-profit witness the prior stays a ranking signal.
    cap = 0.97 if proofs else 0.8
    prior = round(min(cap, prior), 2)
    score = 0.0
    if agreeing:
        score = round(min(1.0, len(agreeing) / 8.0), 2)
    witnesses = []
    for block_name in ("symbolic", "mutation", "fuzz"):
        block = (layers or {}).get(block_name) if isinstance((layers or {}).get(block_name), dict) else {}
        for row in block.get("witnesses") or []:
            if int(row.get("caller_profit_delta") or 0) > 0:
                witnesses.append(dict(row))
        nested = block.get("smtchecker") if isinstance(block.get("smtchecker"), dict) else None
        if nested and int(nested.get("caller_profit_delta") or 0) > 0:
            witnesses.append({
                "engine": "smtchecker",
                "rule": "no_caller_profit",
                "family": "caller-profit",
                "call_path": "smt",
                "caller_profit_delta": int(nested["caller_profit_delta"]),
                "heat_contribution": 0,
            })
    return {
        "status": "ok",
        "heat_contribution": 0,
        "label": "evidence only",
        "drain_probability": prior,
        "prior_raised": prior > 0.05,
        "passes_agreeing": agreeing,
        "agreement_score": score,
        "proven_caller_profit": bool(proofs),
        "witnesses": witnesses,
        "note": "prior is a ranking signal; heat stays on the caller-profit gate",
    }
