"""Detect implementation changes, large funds deltas, and seed recent deploys.

Read-only eth_getStorageAt / eth_call / funds probe / block walk.
Never sends transactions. Alerts are deduped by address + change fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from eth_scanner.discover.recent import (
    DiscoveredContract,
    DiscoveryStats,
    discover_recent_deployments,
)
from eth_scanner.ingest.funds import probe_contract_funds
from eth_scanner.store.supabase import ScanStore, normalize_address
from eth_scanner.types import Target


# EIP-1967 implementation slot
_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"


@dataclass
class MonitorAlert:
    address: str
    kind: str  # upgrade | funds-delta | discovery
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
        headers={"Content-Type": "application/json", "User-Agent": "eth-scanner-monitor/0.2"},
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


def seed_recent_deployments(
    store: ScanStore,
    *,
    rpc_url: str = "",
    etherscan_keys: str = "",
    lookback_hours: int = 2,
    max_blocks: int = 800,
    max_results: int = 1000,
    prefer_verified: Optional[bool] = None,
) -> tuple[list[DiscoveredContract], DiscoveryStats]:
    """Discover recent creates and upsert them as pending targets (newest first)."""
    found, stats = discover_recent_deployments(
        rpc_url=rpc_url,
        etherscan_keys=etherscan_keys,
        lookback_hours=lookback_hours,
        max_blocks=max_blocks,
        max_results=max_results,
        prefer_verified=prefer_verified,
    )
    for row in found:
        store.upsert_target(Target(
            address=row.address,
            status="pending",
            has_code=True,
            deployed_block=row.deployed_block,
            deployed_at=row.deployed_at,
            discovery_source=row.source,
        ))
    return found, stats


def scan_watchlist(
    store: ScanStore,
    *,
    rpc_url: str = "",
    min_funds_usd: Optional[float] = None,
    funds_delta_ratio: float = 0.25,
    limit: int = 1000,
    seed_discoveries: bool = True,
    lookback_hours: int = 2,
    max_blocks: int = 800,
    prefer_verified: Optional[bool] = None,
) -> tuple[list[MonitorAlert], DiscoveryStats, list[DiscoveredContract]]:
    """Seed recent deployments (default), then compare stored targets for upgrades/TVL.

    Returns (alerts, discovery_stats, discovered_rows).
    """
    if min_funds_usd is None:
        from eth_scanner.ingest.funds import discovery_min_usd
        min_funds_usd = discovery_min_usd()
    rpc = (rpc_url or os.environ.get("ETH_RPC_URL") or "").strip()
    alerts: list[MonitorAlert] = []
    seen = set()
    stats = DiscoveryStats()
    found: list[DiscoveredContract] = []

    if seed_discoveries:
        try:
            found, stats = seed_recent_deployments(
                store,
                rpc_url=rpc,
                etherscan_keys=os.environ.get("ETHERSCAN_API_KEYS") or "",
                lookback_hours=lookback_hours,
                max_blocks=max_blocks,
                max_results=max(limit, 1),
                prefer_verified=prefer_verified,
            )
            for row in found:
                fp = _fp(row.address, "discover", row.deployed_block)
                if fp in seen:
                    continue
                seen.add(fp)
                alerts.append(MonitorAlert(
                    address=row.address,
                    kind="discovery",
                    fingerprint=fp,
                    detail="recent deploy block=%s source=%s verified=%s name=%s"
                    % (row.deployed_block, row.source, row.verified, row.contract_name or "—"),
                    previous=None,
                    current=row.deployed_block,
                ))
        except Exception as exc:  # noqa: BLE001
            alerts.append(MonitorAlert(
                address="0x0000000000000000000000000000000000000000",
                kind="discovery",
                fingerprint=_fp("discover-error", str(exc)[:80]),
                detail="discovery error: %s" % str(exc)[:160],
            ))

    rows = store.list_targets(limit=limit)
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
    return alerts, stats, found
