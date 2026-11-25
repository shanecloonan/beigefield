"""Find funded contracts on BNB Chain, Arbitrum, Base, Optimism, and Polygon. Read-only.

Dollars come from DefiLlama's per-chain TVL, not the protocol's total.
A bare address is used only when that protocol lists this chain alone.
A prefixed address (``bsc:``, ``arbitrum:``, ``base:``) is used as given.
``eth_getCode`` decides whether the account is a contract. An account
with no code is evidence only and is not queued. Ethereum discovery is
unchanged and this module refuses to run it.

Nothing here is heat. The $100 floor is unchanged. The same address is
never written over an Ethereum row.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from eth_scanner.chains.evm import call_with_backoff, evm_chain
from eth_scanner.chains.registry import normalize_chain
from eth_scanner.chain.cu_budget import (
    CuBudget,
    chain_daily_scans,
    discover_run_cap,
    multi_chain_monthly_cu,
)
from eth_scanner.types import DEFAULT_MIN_FUNDS_USD, Target

LLAMA_PROTOCOLS = "https://api.llama.fi/protocols"
LLAMA_NAME = {
    "bsc": "Binance",
    "arbitrum": "Arbitrum",
    "base": "Base",
    "optimism": "Optimism",
    "polygon": "Polygon",
}
PREFIXES = {
    "bsc": ("bsc:", "binance:"),
    "arbitrum": ("arbitrum:",),
    "base": ("base:",),
    "optimism": ("optimism:", "op:"),
    "polygon": ("polygon:", "matic:"),
}
DEFAULT_LIMIT = 10
MAX_LIMIT = 20

Fetch = Callable[[str], Any]
Rpc = Callable[[str, str, list[Any]], Any]


def discover(
    chain: str,
    *,
    limit: int = DEFAULT_LIMIT,
    min_usd: float = DEFAULT_MIN_FUNDS_USD,
    fetch: Optional[Fetch] = None,
    rpc: Optional[Rpc] = None,
    pause: Callable[[float], None] = lambda _seconds: None,
) -> dict[str, Any]:
    """Return candidates. heat_contribution is always 0."""
    name = normalize_chain(chain)
    if name == "ethereum":
        return {
            "chain": "ethereum",
            "refused": True,
            "reason": "ethereum discovery is unchanged",
            "heat_contribution": 0,
            "candidates": [],
            "enqueued": [],
        }
    cfg = evm_chain(name)
    cap = max(1, min(MAX_LIMIT, int(limit or DEFAULT_LIMIT)))
    floor = max(float(DEFAULT_MIN_FUNDS_USD), float(min_usd or 0))
    picked = _select(_protocols(fetch), name, floor)[:cap]
    degraded = False
    guard = CuBudget(discover_run_cap(name))
    for row in picked:
        if not guard.allow("eth_getCode"):
            degraded = True
            row["degraded"] = True
            row["has_code"] = None
            row["rpc_note"] = "CU budget reached; TVL evidence kept"
            continue
        guard.charge("eth_getCode")
        if rpc is None:
            def live(url: str, method: str, params: list[Any]) -> Any:
                return _rpc_call(url, method, params)

            caller = live
        else:
            caller = rpc
        try:
            code = call_with_backoff(name, "eth_getCode", [row["address"], "latest"], rpc=caller, pause=pause)
        except Exception as exc:  # noqa: BLE001
            degraded = True
            row["degraded"] = True
            row["has_code"] = None
            row["rpc_note"] = "code read failed; TVL evidence kept"
            row["rpc_error"] = type(exc).__name__
            continue
        text = _hex(code)
        row["has_code"] = bool(text) and text not in {"0x", "0x0"}
        row["evidence"].append({"source": "eth_getCode", "has_code": row["has_code"]})
        if not row["has_code"]:
            row["rpc_note"] = "listed address has no code; TVL evidence kept"
    budget = multi_chain_monthly_cu()
    return {
        "chain": cfg.name,
        "chain_id": cfg.chain_id,
        "refused": False,
        "heat_contribution": 0,
        "min_usd": floor,
        "degraded": degraded,
        "candidates": picked,
        "daily_scans": chain_daily_scans(cfg.name),
        "cu_spent": guard.spent,
        "cu_cap": guard.cap,
        "monthly_cu": budget["monthly_cu"],
        "ethereum_monthly_cu": budget["ethereum_monthly_cu"],
        "within_cap": budget["within_cap"],
        "note": "Per-chain TVL is evidence. This stage adds no heat.",
    }


def enqueue(store: Any, report: dict[str, Any]) -> dict[str, Any]:
    """Queue contracts on their own chain. An Ethereum row with the same address stays put."""
    saved: list[str] = []
    skipped: list[dict[str, str]] = []
    if report.get("refused") or report.get("chain") == "ethereum":
        return {"enqueued": [], "skipped": [], "heat_contribution": 0}
    for row in report.get("candidates") or []:
        if row.get("has_code") is not True:
            skipped.append({"address": row["address"], "reason": "no code"})
            continue
        try:
            store.upsert_target(Target(
                address=row["address"],
                chain=report["chain"],
                status="pending",
                funds_usd=row["funds_usd"],
                funds_breakdown=list(row.get("evidence") or []),
                funds_status="ok",
                discovery_source="evm-tvl",
            ))
        except ValueError:
            skipped.append({"address": row["address"], "reason": "address belongs to another chain"})
            continue
        saved.append(row["address"])
    return {"enqueued": saved, "skipped": skipped, "heat_contribution": 0}


def select_work(rows: list[dict[str, Any]], chain: str, limit: Optional[int] = None) -> list[dict[str, Any]]:
    """Pending rows a chain worker may take today. Ethereum is not selected."""
    name = normalize_chain(chain)
    cap = chain_daily_scans(name)
    if name == "ethereum" or cap <= 0:
        return []
    room = cap if limit is None else min(cap, max(0, int(limit)))
    from eth_scanner.chains.registry import row_chain

    pending = [
        row for row in rows
        if row.get("status") == "pending" and row_chain(row) == name
    ]
    return pending[:room]


def _protocols(fetch: Optional[Fetch]) -> list[dict[str, Any]]:
    payload = fetch(LLAMA_PROTOCOLS) if fetch is not None else _http_json(LLAMA_PROTOCOLS)
    if isinstance(payload, dict):
        payload = payload.get("protocols") or payload.get("data") or []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _select(protocols: list[dict[str, Any]], chain: str, floor: float) -> list[dict[str, Any]]:
    llama = LLAMA_NAME[chain]
    chosen: dict[str, dict[str, Any]] = {}
    for row in protocols:
        address = _address_for(row, chain, llama)
        if not address:
            continue
        usd = _chain_usd(row, llama)
        if usd is None or usd < floor:
            continue
        current = chosen.get(address)
        if current is not None and float(current["funds_usd"]) >= float(usd):
            continue
        chosen[address] = {
            "address": address,
            "chain": chain,
            "name": str(row.get("name") or "")[:80],
            "funds_usd": round(float(usd), 2),
            "funds_status": "ok",
            "has_code": None,
            "heat_contribution": 0,
            "evidence": [{
                "source": "defillama",
                "kind": "%s-tvl" % chain,
                "usd": round(float(usd), 2),
            }],
        }
    ordered = list(chosen.values())
    ordered.sort(key=lambda item: (-float(item["funds_usd"]), item["address"]))
    return ordered


def _address_for(row: dict[str, Any], chain: str, llama: str) -> Optional[str]:
    raw = str(row.get("address") or "").strip()
    if not raw or raw.lower() in {"none", "null"}:
        return None
    low = raw.lower()
    for prefix in PREFIXES[chain]:
        if low.startswith(prefix):
            return _evm(raw.split(":", 1)[1])
    chains = [str(item) for item in (row.get("chains") or [])]
    if len(chains) == 1 and chains[0] == llama:
        return _evm(raw)
    return None


def _chain_usd(row: dict[str, Any], llama: str) -> Optional[float]:
    tvls = row.get("chainTvls") or {}
    if not isinstance(tvls, dict):
        return None
    value = tvls.get(llama)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _evm(text: str) -> Optional[str]:
    raw = (text or "").strip().lower()
    if len(raw) == 42 and raw.startswith("0x"):
        try:
            int(raw[2:], 16)
        except ValueError:
            return None
        return raw
    return None


def _hex(result: Any) -> str:
    if isinstance(result, dict):
        result = result.get("result", "")
    return str(result or "").strip().lower()


def _rpc_call(url: str, method: str, params: list[Any]) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "beigefield-scanner"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError("http %s" % exc.code) from None
    if isinstance(body, dict) and body.get("error"):
        err = body["error"]
        raise RuntimeError("%s %s" % (err.get("code"), err.get("message")))
    return body.get("result") if isinstance(body, dict) else body


def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "beigefield-scanner"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))
