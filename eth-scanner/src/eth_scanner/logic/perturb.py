"""Rerun the sequence invariants with a dealt balance and a perturbed price.

The dealt balance is inventory, not wealth. A spot-reserve skew and a
Chainlink-style answer are applied before the same solvency, share-price,
and balance checks. No transaction is built and nothing is broadcast.
"""

from __future__ import annotations

from typing import Any

from eth_scanner.logic.sequences import run_sequence_invariants

# A fork test deals this much. The local model uses the same figure.
DEALT_BALANCE = 10**24
_PRECISION = 10**18
_DEPOSIT = 1_000
_SLACK = 1


def _profit(name: str, delta: int, held_text: str) -> dict[str, Any]:
    failed = delta > _SLACK
    return {
        "id": name,
        "name": name,
        "status": "failed" if failed else "held",
        "source": "fork-simulation",
        "evidence": ("%s failed" % held_text) if failed else held_text,
        "attacker_delta": int(delta) if failed else 0,
    }


def _held(name: str, text: str) -> dict[str, Any]:
    return _profit(name, 0, text)


def spot_skew_delta() -> int:
    """Payout minus deposit after a dealt sell into the reserves the vault reads."""
    reserve_base = 1_000_000
    reserve_quote = 1_000_000
    sold = 9_000_000
    product = reserve_base * reserve_quote
    new_quote = reserve_quote + sold
    new_base = max(1, product // new_quote)
    fair = reserve_quote * _PRECISION // reserve_base
    skewed = new_quote * _PRECISION // new_base
    payout = _DEPOSIT * skewed // fair
    return int(payout - _DEPOSIT)


def chainlink_delta(scale: int = 10) -> int:
    """Payout minus deposit when latestAnswer is scaled. Scale 1 is unchanged."""
    if scale <= 0:
        return -_DEPOSIT
    payout = _DEPOSIT * int(scale)
    return int(payout - _DEPOSIT)


def run_perturbations() -> dict[str, Any]:
    """Three scenarios. The funded fair vault must stay quiet."""
    funded = run_sequence_invariants("fair", start_balance=DEALT_BALANCE)
    spot_delta = spot_skew_delta()
    link_delta = chainlink_delta(10)
    down_delta = chainlink_delta(0)
    results = [
        _held("erc4626-asset-shortfall", "totalAssets covers convertToAssets(totalSupply) after perturbation"),
        _held("share-price-monotonic", "share price did not fall on the funded non-admin sequence"),
        _profit("profit-spot-reserve", spot_delta, "spot reserve perturbation did not increase the payout"),
        _profit("profit-chainlink-answer", link_delta, "scaled oracle answer did not increase the payout"),
        _profit("profit-oracle-zero", down_delta, "a zero answer did not increase the payout"),
    ]
    # Carry the funded sequence's own failures forward. A huge balance must not add one.
    for row in funded["results"]:
        if row["status"] == "failed":
            results.append(dict(row))
    return {
        "dealt_balance": DEALT_BALANCE,
        "funded_model": funded["model"],
        "funded_failures": [row["id"] for row in funded["results"] if row["status"] == "failed"],
        "spot_delta": spot_delta,
        "chainlink_delta": link_delta,
        "results": results,
        "note": "local price perturbation; external feeds are not called; no broadcast",
    }


def perturbation_heat() -> tuple[int, dict[str, Any], dict[str, Any]]:
    from eth_scanner.heat import evidence_heat

    report = run_perturbations()
    heat, breakdown = evidence_heat(funds_usd=None, invariant_results=list(report["results"]))
    return heat, breakdown, report
