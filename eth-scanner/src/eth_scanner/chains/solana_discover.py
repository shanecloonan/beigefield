"""Find Solana programs with dollars at risk. Read-only.

Dollars come from the public DefiLlama protocol list (Solana chain TVL).
That list's address is often the protocol token, not the program. An RPC
read records whether the account is executable. Only an executable account
is enqueued, and only then does a bounded read of accounts it owns run.
Nothing here is heat. A 429 or a missing method keeps the TVL evidence and
stops the RPC reads.

SOLANA_RPC_URL is optional. Without it the public mainnet-beta endpoint
is used, with one backoff. The URL is never logged.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from eth_scanner.chains.registry import normalize_solana_address
from eth_scanner.types import DEFAULT_MIN_FUNDS_USD

LLAMA_PROTOCOLS = "https://api.llama.fi/protocols"
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
DEFAULT_LIMIT = 20
MAX_LIMIT = 40
MAX_TOKEN_PROGRAMS = 5
MAX_TOKEN_ACCOUNTS = 4

Fetch = Callable[[str], Any]
Rpc = Callable[[str, list[Any]], Any]


class RpcLimited(RuntimeError):
    """The RPC asked us to slow down. Keep what we already have."""


def rpc_url() -> tuple[str, str]:
    """Return (url, label). The label is safe to print."""
    configured = (os.environ.get("SOLANA_RPC_URL") or "").strip()
    if configured:
        return configured, "configured"
    return PUBLIC_RPC, "public"


def discover(
    *,
    limit: int = DEFAULT_LIMIT,
    min_usd: float = DEFAULT_MIN_FUNDS_USD,
    fetch: Optional[Fetch] = None,
    rpc: Optional[Rpc] = None,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Return candidates. heat_contribution is always 0."""
    cap = max(1, min(MAX_LIMIT, int(limit or DEFAULT_LIMIT)))
    floor = max(float(DEFAULT_MIN_FUNDS_USD), float(min_usd or 0))
    url, label = rpc_url()
    protocols = _protocols(fetch)
    picked = _select(protocols, floor)[:cap]
    token_left = MAX_TOKEN_PROGRAMS
    degraded = False
    stopped = False

    def live(method: str, params: list[Any]) -> Any:
        return _rpc_call(url, method, params, pause)

    for row in picked:
        if stopped:
            degraded = True
            row["degraded"] = True
            row["rpc_note"] = "RPC rate limited; TVL evidence kept"
            continue
        caller = rpc if rpc is not None else live
        try:
            token_left = _enrich(row, caller, token_left, pause)
        except RpcLimited:
            stopped = True
            degraded = True
            row["degraded"] = True
            row["rpc_note"] = "RPC rate limited; TVL evidence kept"
        except Exception as exc:  # noqa: BLE001
            row["degraded"] = True
            row["rpc_note"] = "RPC read failed; TVL evidence kept"
            row["rpc_error"] = type(exc).__name__
    return {
        "chain": "solana",
        "heat_contribution": 0,
        "min_usd": floor,
        "rpc": label,
        "degraded": degraded,
        "candidates": picked,
        "note": "Dollars at risk are evidence. This stage adds no heat.",
    }


def _protocols(fetch: Optional[Fetch]) -> list[dict[str, Any]]:
    if fetch is not None:
        payload = fetch(LLAMA_PROTOCOLS)
    else:
        payload = _http_json(LLAMA_PROTOCOLS)
    if isinstance(payload, dict):
        payload = payload.get("protocols") or payload.get("data") or []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _select(protocols: list[dict[str, Any]], floor: float) -> list[dict[str, Any]]:
    chosen: dict[str, dict[str, Any]] = {}
    for row in protocols:
        address = _program_id(row.get("address"))
        if not address:
            continue
        chains = _chains(row)
        if "solana" not in chains and not _chain_tvl(row):
            continue
        usd = _solana_usd(row, chains)
        if usd is None or usd < floor:
            continue
        current = chosen.get(address)
        if current is not None and float(current["funds_usd"]) >= float(usd):
            continue
        chosen[address] = {
            "address": address,
            "chain": "solana",
            "name": str(row.get("name") or "")[:80],
            "category": str(row.get("category") or "")[:40],
            "funds_usd": round(float(usd), 2),
            "funds_status": "ok",
            "executable": None,
            "owner": None,
            "lamports": None,
            "token_accounts": [],
            "heat_contribution": 0,
            "evidence": [{
                "source": "defillama",
                "kind": "solana-tvl",
                "usd": round(float(usd), 2),
            }],
        }
    ordered = list(chosen.values())
    ordered.sort(key=lambda item: (-float(item["funds_usd"]), item["address"]))
    return ordered


def _enrich(row: dict[str, Any], rpc: Rpc, token_left: int, pause: Callable[[float], None]) -> int:
    info = rpc("getAccountInfo", [row["address"], {"encoding": "base64"}])
    value = _value(info)
    if isinstance(value, dict):
        row["executable"] = bool(value.get("executable"))
        row["owner"] = value.get("owner")
        row["lamports"] = value.get("lamports")
        row["evidence"].append({
            "source": "getAccountInfo",
            "executable": row["executable"],
            "owner": row["owner"],
            "lamports": row["lamports"],
        })
    if row.get("executable") is not True:
        row["rpc_note"] = "listed address is not an executable program; TVL evidence kept"
        return token_left
    if token_left <= 0:
        row["rpc_note"] = "token-account sample cap reached"
        return token_left
    token_left -= 1
    try:
        listed = rpc("getProgramAccounts", [row["address"], {
            "encoding": "base64",
            "dataSlice": {"offset": 0, "length": 0},
            "filters": [{"dataSize": 165}],
        }])
    except RpcLimited:
        raise
    except Exception:  # noqa: BLE001
        row["rpc_note"] = "program account list unavailable; TVL evidence kept"
        return token_left
    accounts = listed if isinstance(listed, list) else _value(listed)
    if not isinstance(accounts, list):
        row["rpc_note"] = "program account list unavailable; TVL evidence kept"
        return token_left
    for item in accounts[:MAX_TOKEN_ACCOUNTS]:
        pubkey = item.get("pubkey") if isinstance(item, dict) else None
        if not pubkey:
            continue
        balance = rpc("getTokenAccountBalance", [pubkey])
        amount = _value(balance) if isinstance(balance, dict) else None
        ui = amount.get("uiAmount") if isinstance(amount, dict) else None
        row["token_accounts"].append({
            "pubkey": pubkey,
            "amount": amount.get("amount") if isinstance(amount, dict) else None,
            "ui_amount": ui,
        })
        row["evidence"].append({
            "source": "getTokenAccountBalance",
            "pubkey": pubkey,
            "ui_amount": ui,
            "usd": None,
        })
    return token_left


def _program_id(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if ":" in text:
        prefix, rest = text.split(":", 1)
        if prefix.strip().lower() in {"solana", "sol"}:
            text = rest.strip()
    try:
        return normalize_solana_address(text)
    except ValueError:
        return None


def _chains(row: dict[str, Any]) -> set[str]:
    names = []
    raw = row.get("chains")
    if isinstance(raw, list):
        names.extend(raw)
    if row.get("chain"):
        names.append(row.get("chain"))
    return {str(name or "").strip().lower() for name in names if str(name or "").strip()}


def _chain_tvl(row: dict[str, Any]) -> Optional[float]:
    block = row.get("chainTvls")
    if not isinstance(block, dict):
        return None
    for key, value in block.items():
        if str(key).strip().lower() == "solana":
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _solana_usd(row: dict[str, Any], chains: set[str]) -> Optional[float]:
    specific = _chain_tvl(row)
    if specific is not None:
        return specific
    if chains == {"solana"}:
        try:
            return float(row.get("tvl"))
        except (TypeError, ValueError):
            return None
    return None


def _value(payload: Any) -> Any:
    if isinstance(payload, dict) and "value" in payload:
        return payload.get("value")
    if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        return payload["result"].get("value")
    return payload


def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "beigefield-scanner"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _rpc_call(
    url: str,
    method: str,
    params: list[Any],
    pause: Callable[[float], None] = time.sleep,
    _attempt: int = 0,
) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429 and _attempt < 1:
            pause(1.0)
            return _rpc_call(url, method, params, pause, _attempt + 1)
        if exc.code == 429:
            raise RpcLimited("429") from exc
        raise
    if isinstance(payload, dict) and payload.get("error"):
        err = payload["error"]
        code = err.get("code") if isinstance(err, dict) else None
        message = str(err.get("message") if isinstance(err, dict) else err)
        limited = code == 429 or "429" in message or "rate" in message.lower()
        if limited and _attempt < 1:
            pause(1.0)
            return _rpc_call(url, method, params, pause, _attempt + 1)
        if limited:
            raise RpcLimited(message)
        raise RuntimeError(message)
    if isinstance(payload, dict) and "result" in payload:
        return payload["result"]
    return payload


def enqueue(store: Any, report: dict[str, Any]) -> list[str]:
    """Store candidates as pending Solana targets. Heat stays 0."""
    from eth_scanner.types import Target

    saved: list[str] = []
    for row in report.get("candidates") or []:
        # A listed mint is evidence, not a program to scan.
        if row.get("executable") is False:
            continue
        target = Target(
            address=str(row["address"]),
            chain="solana",
            status="pending",
            funds_usd=float(row.get("funds_usd") or 0),
            funds_breakdown=list(row.get("evidence") or []),
            funds_status=str(row.get("funds_status") or "ok"),
            discovery_source="solana-tvl",
        )
        store.upsert_target(target)
        saved.append(target.address)
    return saved
