"""Flag contracts that already paid out to an unknown EOA and then went quiet.

Reads ``alchemy_getAssetTransfers`` (external ETH only) and confirms the
recipient has no code. A large confirmed outflow plus a collapsed balance
is evidence that the contract is already drained. It does not add heat.
The desk uses the flag to keep the row off the hot ranking.

If the endpoint has no asset-transfer API, or it returns 429, the status
stays ``unknown`` and the row is ranked as before.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

from eth_scanner.chain.cu_budget import (
    DEFAULT_LIVENESS_CU,
    CuBudget,
    CuBudgetExceeded,
    cap_from_env,
)
from eth_scanner.chain.trace_seeds import _call, _fail_note, _rate_limited, _unsupported
from eth_scanner.feed.lists import normalize_address
from eth_scanner.ingest.rpc_client import RpcTransientError, RpcUnavailable

RpcFn = Callable[..., Any]

# One ether out, and at most 5% of that outflow still sitting on the contract.
MIN_OUTFLOW_WEI = 10**18
COLLAPSE_NUMERATOR = 1
COLLAPSE_DENOMINATOR = 20
_MAX_RECIPIENTS = 4


def assess_outflows(
    transfers: list[dict[str, Any]],
    balance_wei: int,
    codes: dict[str, str],
) -> dict[str, Any]:
    """Decide liveness from transfers whose recipients were proven to be EOAs."""
    outflow = 0
    evidence: list[dict[str, Any]] = []
    for row in transfers or []:
        if str(row.get("category") or "external") != "external":
            continue
        recipient = normalize_address(str(row.get("to") or ""))
        code = codes.get(recipient)
        if not recipient or code is None or not _is_eoa(code):
            continue
        wei = _eth_to_wei(row.get("value"))
        if wei <= 0:
            continue
        outflow += wei
        evidence.append({
            "to": recipient,
            "wei": wei,
            "tx": str(row.get("hash") or ""),
        })
    balance = max(0, int(balance_wei or 0))
    collapsed = outflow >= MIN_OUTFLOW_WEI and balance * COLLAPSE_DENOMINATOR <= outflow * COLLAPSE_NUMERATOR
    if collapsed and balance == 0:
        status = "dead"
    elif collapsed:
        status = "already-exploited"
    else:
        status = "live"
    return {
        "status": status,
        "heat_contribution": 0,
        "label": "evidence only",
        "outflow_wei": outflow,
        "balance_wei": balance,
        "evidence": evidence[:8],
        "degraded": False,
    }


def scan_liveness(
    address: str,
    rpc_url: str = "",
    *,
    budget: Optional[CuBudget] = None,
    rpc: Optional[RpcFn] = None,
) -> dict[str, Any]:
    """Read-only outflow check. Unknown when the RPC cannot answer."""
    target = normalize_address(address)
    book = budget or CuBudget(cap_from_env("ETH_SCANNER_LIVENESS_CU", DEFAULT_LIVENESS_CU))
    caller = rpc or _default_rpc
    body = _unknown(target, "ETH_RPC_URL unset — row stays in the normal ranking")
    if not target:
        body["note"] = "address missing"
        body["cu"] = book.snapshot()
        return body
    if not (rpc_url or "").strip():
        body["cu"] = book.snapshot()
        return body
    try:
        transfers = _transfers(caller, rpc_url, target, book)
        codes = _codes(caller, rpc_url, transfers, book)
        balance = _balance(caller, rpc_url, target, book)
    except CuBudgetExceeded:
        body = _unknown(target, "compute-unit cap reached — row stays in the normal ranking")
        body["degraded"] = True
        body["cu"] = book.snapshot()
        return body
    except (RpcUnavailable, RpcTransientError, RuntimeError, OSError, TimeoutError) as exc:
        body = _unknown(target, _fail_note(exc) + " — row stays in the normal ranking")
        body["degraded"] = True
        body["cu"] = book.snapshot()
        return body
    decided = assess_outflows(transfers, balance, codes)
    decided["address"] = target
    decided["note"] = {
        "dead": "historical ETH outflow to an EOA and the balance is now zero",
        "already-exploited": "historical ETH outflow to an EOA and the balance has collapsed",
        "live": "no collapsed EOA outflow in the sample",
    }[decided["status"]]
    decided["cu"] = book.snapshot()
    return decided


def _transfers(rpc: RpcFn, url: str, target: str, budget: CuBudget) -> list[dict[str, Any]]:
    try:
        result = _call(rpc, url, "alchemy_getAssetTransfers", [{
            "fromBlock": "0x0",
            "toBlock": "latest",
            "fromAddress": target,
            "category": ["external"],
            "maxCount": "0x20",
            "order": "desc",
            "excludeZeroValue": True,
            "withMetadata": False,
        }], budget)
    except (RpcUnavailable, RpcTransientError, RuntimeError, OSError, TimeoutError) as exc:
        if _unsupported(exc) or _rate_limited(exc):
            raise RuntimeError(str(exc)) from exc
        raise
    rows = result.get("transfers") if isinstance(result, dict) else None
    return [row for row in (rows or []) if isinstance(row, dict)]


def _codes(rpc: RpcFn, url: str, transfers: list[dict[str, Any]], budget: CuBudget) -> dict[str, str]:
    ranked: list[tuple[int, str]] = []
    for row in transfers:
        recipient = normalize_address(str(row.get("to") or ""))
        if not recipient:
            continue
        ranked.append((_eth_to_wei(row.get("value")), recipient))
    ranked.sort(reverse=True)
    codes: dict[str, str] = {}
    for _wei, recipient in ranked:
        if recipient in codes:
            continue
        if len(codes) >= _MAX_RECIPIENTS or not budget.allow("eth_getCode"):
            break
        raw = _call(rpc, url, "eth_getCode", [recipient, "latest"], budget)
        codes[recipient] = str(raw or "0x").lower()
    return codes


def _balance(rpc: RpcFn, url: str, target: str, budget: CuBudget) -> int:
    raw = _call(rpc, url, "eth_getBalance", [target, "latest"], budget)
    text = str(raw or "0x0")
    try:
        return int(text, 16) if text.startswith("0x") else int(text)
    except (TypeError, ValueError):
        return 0


def _unknown(address: str, note: str) -> dict[str, Any]:
    return {
        "status": "unknown",
        "heat_contribution": 0,
        "label": "evidence only",
        "address": address,
        "outflow_wei": 0,
        "balance_wei": 0,
        "evidence": [],
        "degraded": False,
        "note": note,
    }


def _is_eoa(code: str) -> bool:
    text = (code or "").strip().lower()
    return text in {"", "0x", "0x0"}


def _eth_to_wei(value: Any) -> int:
    """Alchemy ``value`` is a decimal ETH amount. Hex strings are wei."""
    if value is None or value == "":
        return 0
    text = str(value).strip()
    try:
        if text.startswith("0x"):
            return int(text, 16)
        return int(float(text) * 10**18)
    except (TypeError, ValueError):
        return 0


def _default_rpc(url: str, method: str, params: list[Any], timeout_s: float = 8.0) -> Any:
    from eth_scanner.ingest.rpc_client import rpc_call
    return rpc_call(url, method, params, timeout_s=timeout_s)


def liveness_from_env(address: str) -> dict[str, Any]:
    try:
        return scan_liveness(address, os.environ.get("ETH_RPC_URL") or "")
    except Exception as exc:  # noqa: BLE001
        row = _unknown(normalize_address(address), "liveness skipped: %s" % str(exc)[:140])
        row["degraded"] = True
        return row
