"""Compare an L2 header with the L1 head it claims to follow.

Arbitrum and Base are the L2s. A missing L1 number stays unknown. An L1
number past the supplied L1 head is a lead. Heat stays 0: this is a
comparison of two reads, not a local fuzzer or prover failure.
"""

from __future__ import annotations

from typing import Any, Optional

from eth_scanner.chains.registry import normalize_chain

_L2 = {"arbitrum", "base"}


def _num(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("invalid number")
    if isinstance(value, int):
        number = value
    else:
        number = int(str(value).strip(), 0)
    if number < 0:
        raise ValueError("invalid number")
    return number


def _check(name: str, state: str) -> dict[str, Any]:
    return {"id": name, "state": state, "heat_contribution": 0}


def l2_invariants(
    chain: str,
    *,
    l2_head: Any = None,
    l1_block: Any = None,
    l1_head: Any = None,
) -> dict[str, Any]:
    name = normalize_chain(chain)
    if name not in _L2:
        return {
            "status": "skipped",
            "reason": "not an l2",
            "chain": name,
            "checks": [],
            "heat_contribution": 0,
        }
    try:
        head = _num(l2_head)
        sequenced = _num(l1_block)
        parent = _num(l1_head)
    except ValueError:
        return {
            "status": "skipped",
            "reason": "invalid number",
            "chain": name,
            "checks": [],
            "heat_contribution": 0,
        }
    present = "held" if sequenced is not None else "unknown"
    if sequenced is None or parent is None:
        ahead = "unknown"
    elif sequenced <= parent:
        ahead = "held"
    else:
        ahead = "violated"
    return {
        "status": "ok",
        "reason": "",
        "chain": name,
        "l2_head": head,
        "l1_block": sequenced,
        "l1_head": parent,
        "checks": [
            _check("l1-present", present),
            _check("l1-not-ahead", ahead),
        ],
        "heat_contribution": 0,
        "note": "Two reads compared. A violated check is a lead and adds no heat.",
    }
