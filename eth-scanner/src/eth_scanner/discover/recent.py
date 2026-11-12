"""Discover newly deployed mainnet contracts (read-only).

Primary path: walk recent blocks over ETH_RPC_URL / public RPC for
contract-creation receipts (`to` is null). Optional: Etherscan verified
contract helpers when ETHERSCAN_API_KEYS is set.

Never sends a transaction. Free-tier only.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from eth_scanner.ingest.funds import PUBLIC_RPCS, resolve_rpc_urls
from eth_scanner.known_safe import SAFE_ADDRESSES

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
CHAIN_ID = "1"
# ~12s blocks → 24h ≈ 7200, 72h ≈ 21600
DEFAULT_LOOKBACK_HOURS = 48
MAX_BLOCKS_TO_SCAN = 120  # keep Actions free-tier bounded
MAX_CREATES_PER_RUN = 40


@dataclass
class DiscoveredContract:
    address: str
    deployed_block: int
    deployed_at: Optional[str] = None  # ISO8601 UTC
    tx_hash: Optional[str] = None
    verified: Optional[bool] = None
    contract_name: Optional[str] = None
    source: str = "rpc-create"  # rpc-create | etherscan-verified
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def discover_recent_deployments(
    *,
    rpc_url: str = "",
    etherscan_keys: str = "",
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    max_blocks: int = MAX_BLOCKS_TO_SCAN,
    max_results: int = MAX_CREATES_PER_RUN,
    prefer_verified: bool = True,
) -> list[DiscoveredContract]:
    """Return newest-first contract creations, excluding known-safe addresses."""
    rpc = _pick_rpc(rpc_url)
    keys = [k.strip() for k in (etherscan_keys or os.environ.get("ETHERSCAN_API_KEYS") or "").split(",") if k.strip()]
    out: list[DiscoveredContract] = []
    seen: set[str] = set()

    # 1) RPC block walk for creates (works without Etherscan).
    if rpc:
        try:
            out.extend(_discover_via_rpc(
                rpc,
                lookback_hours=lookback_hours,
                max_blocks=max_blocks,
                max_results=max_results,
            ))
        except Exception as exc:  # noqa: BLE001
            out.append(DiscoveredContract(
                address="0x0000000000000000000000000000000000000000",
                deployed_block=0,
                source="rpc-create",
                notes=["rpc discovery error: %s" % str(exc)[:160]],
            ))
            # Drop the placeholder error row from results.
            out = [r for r in out if r.deployed_block > 0]

    # 2) Optional Etherscan enrichment / verified-only filter.
    filtered: list[DiscoveredContract] = []
    for row in out:
        addr = row.address.lower()
        if addr in seen or addr in SAFE_ADDRESSES:
            continue
        seen.add(addr)
        if keys and prefer_verified:
            ok, name = _etherscan_verified(addr, keys[0])
            row.verified = ok
            if name:
                row.contract_name = name
            if prefer_verified and ok is False:
                row.notes.append("unverified — skipped when prefer_verified")
                continue
        filtered.append(row)
        if len(filtered) >= max_results:
            break

    # Newest first.
    filtered.sort(key=lambda r: r.deployed_block, reverse=True)
    return filtered[:max_results]


def _discover_via_rpc(
    rpc: str,
    *,
    lookback_hours: int,
    max_blocks: int,
    max_results: int,
) -> list[DiscoveredContract]:
    head_hex = _rpc(rpc, "eth_blockNumber", [])
    head = int(head_hex, 16)
    # Sample recent blocks: stride so we cover lookback without scanning every block.
    approx_blocks = max(100, int(lookback_hours * 3600 / 12))
    stride = max(1, approx_blocks // max(1, max_blocks))
    creates: list[DiscoveredContract] = []
    blocks_tried = 0
    for i in range(max_blocks):
        bn = head - (i * stride)
        if bn <= 0:
            break
        blocks_tried += 1
        block = _rpc(rpc, "eth_getBlockByNumber", [hex(bn), True])
        if not isinstance(block, dict):
            continue
        ts = int(block.get("timestamp") or "0x0", 16)
        deployed_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None
        for tx in block.get("transactions") or []:
            if not isinstance(tx, dict):
                continue
            if tx.get("to") not in (None, "", "0x"):
                continue
            # Contract creation — resolve address from receipt.
            tx_hash = tx.get("hash")
            if not tx_hash:
                continue
            try:
                receipt = _rpc(rpc, "eth_getTransactionReceipt", [tx_hash])
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(receipt, dict):
                continue
            created = (receipt.get("contractAddress") or "").lower()
            if not created or created == "0x" + "0" * 40:
                continue
            if created in SAFE_ADDRESSES:
                continue
            creates.append(DiscoveredContract(
                address=created,
                deployed_block=bn,
                deployed_at=deployed_at,
                tx_hash=str(tx_hash),
                source="rpc-create",
            ))
            if len(creates) >= max_results * 2:
                break
        if len(creates) >= max_results * 2:
            break
        # Be gentle on public RPCs.
        if i and i % 10 == 0:
            time.sleep(0.15)
    creates.sort(key=lambda r: r.deployed_block, reverse=True)
    for c in creates:
        c.notes.append("scanned_blocks=%d stride=%d head=%d" % (blocks_tried, stride, head))
    return creates


def _etherscan_verified(address: str, api_key: str) -> tuple[Optional[bool], Optional[str]]:
    qs = urllib.parse.urlencode({
        "chainid": CHAIN_ID,
        "module": "contract",
        "action": "getsourcecode",
        "address": address,
        "apikey": api_key,
    })
    url = "%s?%s" % (ETHERSCAN_V2, qs)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "eth-scanner-discover/0.1"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None, None
    result = body.get("result")
    if isinstance(result, list) and result:
        row = result[0]
        src = (row.get("SourceCode") or "").strip()
        name = (row.get("ContractName") or "").strip() or None
        return (bool(src), name)
    return None, None


def _pick_rpc(preferred: str) -> str:
    urls = resolve_rpc_urls(preferred)
    if urls:
        return urls[0]
    return PUBLIC_RPCS[0] if PUBLIC_RPCS else ""


def _rpc(url: str, method: str, params: list[Any], timeout_s: float = 12.0) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "eth-scanner-discover/0.1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    if body.get("error"):
        raise RuntimeError(str(body["error"])[:200])
    return body.get("result")
