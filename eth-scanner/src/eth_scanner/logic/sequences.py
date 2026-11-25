"""Multi-call conservation checks for an unprivileged actor.

The catalog is a fixed list of deposit, donate, withdraw, and redeem steps.
It replaces a one-call drain probe with short sequences. A broken property
is a name and a balance delta. No calldata and no chain writes.
"""

from __future__ import annotations

from typing import Any, Optional

MAX_SEQUENCES = 8
MAX_DEPTH = 4
_SLACK = 1
_PRECISION = 10**18
_START = 1_000_000

# (action, actor, amount). amount 0 on redeem means "all of that actor's shares".
SEQUENCES: tuple[tuple[tuple[str, str, int], ...], ...] = (
    (("deposit", "attacker", 100),),
    (("deposit", "attacker", 100), ("withdraw", "attacker", 100)),
    (("deposit", "victim", 500), ("withdraw", "attacker", 1)),
    (
        ("deposit", "attacker", 1),
        ("donate", "attacker", 10_000),
        ("deposit", "victim", 5_000),
        ("redeem", "attacker", 0),
    ),
    (
        ("deposit", "attacker", 100),
        ("donate", "attacker", 1_000),
        ("deposit", "victim", 100),
    ),
)

_MODELS = frozenset({"fair", "dilute", "inflation", "leaky", "short"})


class _Books:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.assets = 0
        self.supply = 0
        self.shares = {"attacker": 0, "victim": 0}
        self.wallet = {"attacker": _START, "victim": _START}


def _fair_claim(state: _Books, shares: int) -> int:
    if shares <= 0 or state.supply <= 0 or state.assets <= 0:
        return 0
    return shares * state.assets // state.supply


def _view_claim(state: _Books, shares: int) -> int:
    """What convertToAssets reports. `short` overstates the claim."""
    if shares <= 0 or state.supply <= 0:
        return 0
    assets = state.assets + (1000 if state.kind == "short" else 0)
    if assets <= 0:
        return 0
    return shares * assets // state.supply


def _price(state: _Books) -> int:
    if state.supply <= 0:
        return 0
    return state.assets * _PRECISION // state.supply


def _deposit(state: _Books, actor: str, amount: int) -> None:
    if amount <= 0 or state.wallet.get(actor, 0) < amount:
        return
    if state.kind == "dilute" and state.supply > 0 and state.assets > 0:
        shares = amount
    elif state.supply <= 0 or state.assets <= 0:
        shares = amount
    else:
        shares = amount * state.supply // state.assets
    if shares <= 0 and state.kind != "inflation":
        return
    state.wallet[actor] -= amount
    state.assets += amount
    state.supply += shares
    state.shares[actor] = state.shares.get(actor, 0) + max(shares, 0)


def _donate(state: _Books, actor: str, amount: int) -> None:
    if amount <= 0 or state.wallet.get(actor, 0) < amount:
        return
    if state.supply <= 0 and state.kind not in {"inflation", "short"}:
        return
    state.wallet[actor] -= amount
    state.assets += amount


def _withdraw(state: _Books, actor: str, shares: int) -> None:
    if state.kind == "leaky":
        gained = state.assets
        state.assets = 0
        state.wallet[actor] = state.wallet.get(actor, 0) + gained
        return
    have = state.shares.get(actor, 0)
    if shares <= 0:
        shares = have
    shares = min(shares, have)
    if shares <= 0 or state.supply <= 0 or state.assets <= 0:
        return
    out = min(state.assets, shares * state.assets // state.supply)
    state.shares[actor] = have - shares
    state.supply -= shares
    state.assets -= out
    state.wallet[actor] = state.wallet.get(actor, 0) + out


def _step(state: _Books, action: str, actor: str, amount: int) -> None:
    if action == "deposit":
        _deposit(state, actor, amount)
    elif action == "donate":
        _donate(state, actor, amount)
    elif action in {"withdraw", "redeem"}:
        _withdraw(state, actor, amount)
    # Unknown actions are ignored. The catalog is the only caller.


def _wealth(state: _Books, actor: str = "attacker") -> int:
    return state.wallet.get(actor, 0) + _fair_claim(state, state.shares.get(actor, 0))


def run_sequence_invariants(kind: str = "fair") -> dict[str, Any]:
    """Run the capped catalog. `kind` is a local model, not a live contract."""
    model = kind if kind in _MODELS else "fair"
    solvency = True
    monotonic = True
    profit = True
    attacker_delta = 0
    ran = 0
    for sequence in SEQUENCES[:MAX_SEQUENCES]:
        steps = tuple(sequence[:MAX_DEPTH])
        if not steps:
            continue
        ran += 1
        state = _Books(model)
        start = _wealth(state)
        seen_price = 0
        for action, actor, amount in steps:
            _step(state, action, actor, int(amount))
            if not ( _view_claim(state, state.supply) <= state.assets + _SLACK or state.supply == 0):
                solvency = False
            price = _price(state)
            if seen_price and price and price + _SLACK < seen_price:
                monotonic = False
            if price:
                seen_price = price
        delta = _wealth(state) - start
        if delta > attacker_delta:
            attacker_delta = delta
        if delta > _SLACK:
            profit = False
    rows = [
        _row("erc4626-asset-shortfall", solvency, "totalAssets covers convertToAssets(totalSupply)"),
        _row("share-price-monotonic", monotonic, "share price did not fall on a non-admin sequence"),
        _row(
            "profit-attacker-balance",
            profit,
            "unprivileged balance did not rise",
            attacker_delta=attacker_delta if not profit else 0,
        ),
    ]
    return {
        "model": model,
        "sequences": ran,
        "depth_cap": MAX_DEPTH,
        "results": rows,
        "heat_note": "local sequence model; no chain writes",
    }


def _row(name: str, held: bool, text: str, attacker_delta: int = 0) -> dict[str, Any]:
    return {
        "id": name,
        "name": name,
        "status": "held" if held else "failed",
        "source": "fork-simulation",
        "evidence": text if held else "%s failed" % text,
        "attacker_delta": int(attacker_delta),
    }


def sequence_heat(kind: str = "fair") -> tuple[int, dict[str, Any], dict[str, Any]]:
    """Heat from the local sequence model. Funds stay out of the score."""
    from eth_scanner.heat import evidence_heat

    report = run_sequence_invariants(kind)
    heat, breakdown = evidence_heat(funds_usd=None, invariant_results=list(report["results"]))
    return heat, breakdown, report


def known_models() -> list[str]:
    return sorted(_MODELS)
