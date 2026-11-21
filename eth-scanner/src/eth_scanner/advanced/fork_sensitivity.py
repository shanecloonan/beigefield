"""Read one view twice on a local fork. Nothing is broadcast.

The second read may override a single storage word inside eth_call. That
is not a transaction, not a flash-loan call, and not a profit calculation.
A changed return value is a lead. Heat stays 0.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Callable, Optional

# totalAssets()
_VIEW = "0x01e1d114"
Rpc = Callable[[str, str, list[Any]], str]


def _local(url: str) -> bool:
    host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    return host in {"127.0.0.1", "localhost"}


def _call(rpc: Rpc, url: str, address: str, slot: str = "", word: str = "") -> str:
    tx: dict[str, Any] = {"to": address, "data": _VIEW}
    params: list[Any] = [tx, "latest"]
    if slot and word:
        params.append({address: {"stateDiff": {slot: word}}})
    return rpc(url, "eth_call", params)


def compare_view(
    fork_url: str,
    address: str,
    *,
    slot: str = "",
    word: str = "",
    rpc: Optional[Rpc] = None,
) -> dict[str, Any]:
    if not _local(fork_url):
        return {
            "status": "skipped",
            "reason": "fork is not local",
            "changed": False,
            "heat_contribution": 0,
            "calls": [],
        }
    if rpc is None:
        return {
            "status": "skipped",
            "reason": "no local fork client",
            "changed": False,
            "heat_contribution": 0,
            "calls": [],
        }
    seen: list[str] = []

    def wrapped(url: str, method: str, params: list[Any]) -> str:
        seen.append(method)
        return rpc(url, method, params)

    base = _call(wrapped, fork_url, address)
    other = _call(wrapped, fork_url, address, slot, word) if slot and word else base
    return {
        "status": "ok",
        "reason": "",
        "changed": base != other,
        "heat_contribution": 0,
        "calls": seen,
        "note": "eth_call only. No flash-loan call and no broadcast.",
    }
