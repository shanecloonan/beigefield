"""Detect implementation changes and large funds deltas for funded targets.

Read-only eth_getStorageAt / eth_call / funds probe. Never sends transactions.
Alerts are deduped by address + change fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from eth_scanner.ingest.funds import probe_contract_funds
from eth_scanner.store.supabase import ScanStore, normalize_address


# EIP-1967 implementation slot
_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"


@dataclass
class MonitorAlert:
    address: str
    kind: str  # upgrade | funds-delta
    fingerprint: str
    detail: str
    previous: Any = None
    current: Any = None
    funds_usd: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rpc(url: str, method: str, params: list[Any], timeout_s: float = 12.0) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "eth-scanner-monitor/0.1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    if body.get("error"):
        raise RuntimeError(str(body["error"]))
    return body.get("result")


def read_implementation(rpc_url: str, address: str) -> Optional[str]:
    try:
        raw = _rpc(rpc_url, "eth_getStorageAt", [address, _IMPL_SLOT, "latest"])
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, str) or raw in {"0x", "0x" + "0" * 64}:
        return None
    return "0x" + raw[-40:].lower()


def _fp(*parts: Any) -> str:
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()
    return h[:16]


def scan_watchlist(
    store: ScanStore,
    *,
    rpc_url: str = "",
    min_funds_usd: float = 2_000.0,
    funds_delta_ratio: float = 0.25,
    limit: int = 40,
) -> list[MonitorAlert]:
    """Compare stored targets against live implementation + funds."""
    rpc = (rpc_url or os.environ.get("ETH_RPC_URL") or "").strip()
    rows = store.list_targets(limit=limit)
    alerts: list[MonitorAlert] = []
    seen = set()

    for row in rows:
        addr = normalize_address(str(row.get("address") or ""))
        prev_funds = row.get("funds_usd")
        try:
            prev_funds_f = float(prev_funds) if prev_funds is not None else None
        except (TypeError, ValueError):
            prev_funds_f = None

        # Skip dust.
        if prev_funds_f is not None and prev_funds_f < min_funds_usd:
            continue

        # Upgrade monitor.
        if rpc:
            impl = read_implementation(rpc, addr)
            prev_impl = (row.get("implementation") or row.get("protocol_graph", {}) or {})
            if isinstance(prev_impl, dict):
                prev_impl = None
                for n in (row.get("protocol_graph") or {}).get("nodes") or []:
                    if isinstance(n, dict) and n.get("kind") == "implementation":
                        prev_impl = n.get("address")
                        break
            if impl and prev_impl and str(prev_impl).lower() != impl:
                fp = _fp(addr, "upgrade", prev_impl, impl)
                if fp not in seen:
                    seen.add(fp)
                    alerts.append(MonitorAlert(
                        address=addr,
                        kind="upgrade",
                        fingerprint=fp,
                        detail="implementation changed %s → %s" % (prev_impl, impl),
                        previous=prev_impl,
                        current=impl,
                        funds_usd=prev_funds_f,
                    ))

        # Funds delta monitor.
        if rpc:
            try:
                snap = probe_contract_funds(addr, rpc_url=rpc)
                cur = float(snap.total_usd) if snap.total_usd is not None else None
            except Exception:  # noqa: BLE001
                cur = None
            if cur is not None and prev_funds_f is not None and prev_funds_f > 0:
                delta = abs(cur - prev_funds_f) / prev_funds_f
                if delta >= funds_delta_ratio and max(cur, prev_funds_f) >= min_funds_usd:
                    fp = _fp(addr, "funds", round(prev_funds_f, 2), round(cur, 2))
                    if fp not in seen:
                        seen.add(fp)
                        alerts.append(MonitorAlert(
                            address=addr,
                            kind="funds-delta",
                            fingerprint=fp,
                            detail="funds moved by %.0f%% ($%.0f → $%.0f)" % (delta * 100, prev_funds_f, cur),
                            previous=prev_funds_f,
                            current=cur,
                            funds_usd=cur,
                        ))
    return alerts
