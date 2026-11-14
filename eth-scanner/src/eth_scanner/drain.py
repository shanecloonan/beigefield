"""Drain-probability score from value-conservation results.

A score is high only when an unprivileged caller’s balance rises on a
read-only fork, or a public call breaks a value invariant. Accounting
mismatches with no profit path stay low. Engine output and harness setup
failures add nothing. No transaction is broadcast and no calldata is kept.
"""

from __future__ import annotations

from typing import Any, Optional

# Invariants whose failure means an unprivileged balance increased.
PROFIT_IDS = frozenset({
    "profit-free-value",
    "profit-attacker-balance",
    "value-unprivileged-extraction",
})

# Solvency/shape checks. They describe accounting, not a profit path.
ACCOUNTING_PREFIXES = (
    "erc4626-",
    "fuzz-",
    "symbolic-",
    "cdp-",
    "vault-donation",
    "share-",
)

ENGINE_SOURCES = frozenset({
    "fuzz", "symbolic", "halmos", "slither", "mythril", "semgrep", "aderyn",
})


def _status(row: dict[str, Any]) -> str:
    return str(row.get("status") or "").lower()


def _rid(row: dict[str, Any]) -> str:
    return str(row.get("id") or row.get("name") or "")


def is_harness_noise(row: dict[str, Any]) -> bool:
    blob = " ".join([_rid(row), str(row.get("evidence") or "")]).lower()
    return any(tok in blob for tok in ("setup()", "setup", "constructor"))


def is_profit_break(row: dict[str, Any]) -> bool:
    if _status(row) != "failed" or is_harness_noise(row):
        return False
    if str(row.get("source") or "").lower() in ENGINE_SOURCES:
        return False
    rid = _rid(row)
    if rid in PROFIT_IDS or rid.startswith("profit-"):
        return True
    # Explicit state delta recorded by the conservation checker.
    delta = row.get("attacker_delta")
    try:
        return delta is not None and int(delta) > 0
    except (TypeError, ValueError):
        return False


def is_accounting_only(row: dict[str, Any]) -> bool:
    if _status(row) != "failed" or is_profit_break(row) or is_harness_noise(row):
        return False
    if str(row.get("source") or "").lower() in ENGINE_SOURCES:
        return False
    rid = _rid(row)
    return any(rid.startswith(p) for p in ACCOUNTING_PREFIXES)


def score_drain(
    *,
    funds_usd: Optional[float] = None,
    invariant_results: Optional[list[dict[str, Any]]] = None,
    privileged_callable: bool = False,
    eoa_admin: bool = False,
    known_safe: bool = False,
    contract_class: str = "",
) -> dict[str, Any]:
    """0–100 rank. Profit breaks dominate. Accounting quirks stay ≤ 15."""
    if known_safe:
        return {
            "drain_probability": 0,
            "profit_invariant_broke": False,
            "band": "cold",
            "reason": "audited standard / known-safe",
        }
    rows = list(invariant_results or [])
    profit = [r for r in rows if is_profit_break(r)]
    accounting = [r for r in rows if is_accounting_only(r)]
    funds = float(funds_usd or 0.0)
    funds_pts = 0
    if funds >= 100_000:
        funds_pts = 12
    elif funds >= 10_000:
        funds_pts = 6
    elif funds >= 2_000:
        funds_pts = 2
    klass = (contract_class or "").lower()
    surface = 0
    if klass in {"bridge", "uniswap-amm", "custom-amm", "compound-lending", "aave-lending"}:
        surface = 4
    if profit:
        score = min(100, 88 + funds_pts)
        band = "profit"
        reason = "unprivileged balance increased on a read-only check (%s)" % _rid(profit[0])
    elif privileged_callable:
        score = min(70, 48 + funds_pts + surface)
        band = "reachable"
        reason = "public call from a random address did not revert"
    elif eoa_admin and funds >= 100_000:
        score = min(40, 22 + funds_pts)
        band = "admin"
        reason = "single-key admin on a large balance; no profit invariant broke"
    elif accounting:
        score = min(15, 4 + funds_pts // 2)
        band = "accounting"
        reason = "solvency shape only; no simulated profit path (%s)" % _rid(accounting[0])
    else:
        score = min(8, surface)
        band = "low"
        reason = "no value invariant broke within bounds"
    return {
        "drain_probability": int(score),
        "profit_invariant_broke": bool(profit),
        "band": band,
        "reason": reason,
    }


def simulate_local_vault(kind: str) -> dict[str, Any]:
    """Test-tree model of a vault step. No chain, no calldata.

    ``safe`` deposits and withdraws one-for-one.
    ``leaky`` moves the vault balance to a zero-start caller in one public step.
    """
    vault = 1_000
    attacker = 0
    if kind == "safe":
        # Caller deposits 100 of their own (not free value) then withdraws 100.
        vault += 100
        attacker -= 100
        vault -= 100
        attacker += 100
    elif kind == "leaky":
        attacker += vault
        vault = 0
    else:
        raise ValueError("unknown fixture")
    broke = attacker > 0 and kind == "leaky"
    row = {
        "id": "profit-free-value" if broke else "profit-free-value",
        "status": "failed" if broke else "held",
        "source": "fork-simulation",
        "attacker_delta": attacker if broke else 0,
        "evidence": (
            "caller balance rose by %s while vault fell to %s"
            % (attacker, vault)
            if broke
            else "caller gained nothing it did not deposit; vault=%s" % vault
        ),
    }
    scored = score_drain(funds_usd=vault if not broke else 1_000, invariant_results=[row])
    return {"invariant": row, **scored}
