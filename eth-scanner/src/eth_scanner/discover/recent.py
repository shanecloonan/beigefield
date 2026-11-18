"""Discover newly deployed mainnet contracts (read-only).

Primary path: walk recent blocks over ETH_RPC_URL / public RPC for
contract-creation receipts (`to` is null). When ETHERSCAN_API_KEYS is set,
prefer verified source only (skip unverified creates).

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
# ~12s blocks → 1h ≈ 300, 2h ≈ 600. Monitor cron is */10 so a short dense
# lookback covers "everything since last run" with overlap if a run is skipped.
DEFAULT_LOOKBACK_HOURS = 2
MAX_BLOCKS_TO_SCAN = 800  # Alchemy can walk ~2h of blocks densely
MAX_CREATES_PER_RUN = 1000


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


@dataclass
class DiscoveryStats:
    creates_found: int = 0
    verified_kept: int = 0
    unverified_skipped: int = 0
    known_safe_skipped: int = 0
    etherscan_checked: int = 0
    etherscan_errors: int = 0
    prefer_verified: bool = False
    keys_configured: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def discover_recent_deployments(
    *,
    rpc_url: str = "",
    etherscan_keys: str = "",
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    max_blocks: int = MAX_BLOCKS_TO_SCAN,
    max_results: int = MAX_CREATES_PER_RUN,
    prefer_verified: Optional[bool] = None,
) -> tuple[list[DiscoveredContract], DiscoveryStats]:
    """Return (newest-first creates, stats).

    When ETHERSCAN_API_KEYS is set, prefer_verified defaults to True and
    unverified creates are skipped. Without keys, all creates are kept.
    """
    rpc = _pick_rpc(rpc_url)
    keys = [k.strip() for k in (etherscan_keys or os.environ.get("ETHERSCAN_API_KEYS") or "").split(",") if k.strip()]
    stats = DiscoveryStats(keys_configured=bool(keys))
    # Auto-enable verified filter when keys exist unless caller forces False.
    if prefer_verified is None:
        prefer_verified = bool(keys)
    stats.prefer_verified = bool(prefer_verified and keys)

    raw: list[DiscoveredContract] = []
    seen: set[str] = set()

    # 1) RPC block walk for creates (works without Etherscan).
    if rpc:
        try:
            raw.extend(_discover_via_rpc(
                rpc,
                lookback_hours=lookback_hours,
                max_blocks=max_blocks,
                max_results=max(max_results * 3, max_results),
            ))
        except Exception as exc:  # noqa: BLE001
            # Soft-fail: return empty with note via stats only.
            stats.creates_found = 0
            return [], stats

    # Dedupe + known-safe.
    candidates: list[DiscoveredContract] = []
    for row in raw:
        addr = row.address.lower()
        if addr in seen:
            continue
        seen.add(addr)
        if addr in SAFE_ADDRESSES:
            stats.known_safe_skipped += 1
            continue
        candidates.append(row)
    stats.creates_found = len(candidates)

    # 2) Optional Etherscan enrichment / verified-only filter.
    filtered: list[DiscoveredContract] = []
    for row in candidates:
        if stats.prefer_verified:
            stats.etherscan_checked += 1
            ok, name = _etherscan_verified(row.address, keys[0])
            if ok is None:
                stats.etherscan_errors += 1
                # Soft-keep on API error so a flaky key does not empty the queue.
                row.notes.append("etherscan verify error — kept pending recheck")
            else:
                row.verified = ok
                if name:
                    row.contract_name = name
                if not ok:
                    stats.unverified_skipped += 1
                    row.notes.append("unverified — skipped (ETHERSCAN_API_KEYS prefer_verified)")
                    continue
                row.source = "etherscan-verified"
                stats.verified_kept += 1
        elif keys:
            # Enrich name when keys exist but prefer_verified is off.
            stats.etherscan_checked += 1
            ok, name = _etherscan_verified(row.address, keys[0])
            if ok is not None:
                row.verified = ok
            if name:
                row.contract_name = name
            if ok:
                stats.verified_kept += 1
                row.source = "etherscan-verified"
        filtered.append(row)
        if len(filtered) >= max_results:
            break

    filtered.sort(key=lambda r: r.deployed_block, reverse=True)
    return filtered[:max_results], stats


def _discover_via_rpc(
    rpc: str,
    *,
    lookback_hours: int,
    max_blocks: int,
    max_results: int,
) -> list[DiscoveredContract]:
    head_hex = _rpc(rpc, "eth_blockNumber", [])
    head = int(head_hex, 16)
    # Prefer a dense walk when lookback fits in max_blocks (monitor "since last run").
    approx_blocks = max(50, int(lookback_hours * 3600 / 12))
    blocks_to_walk = min(max_blocks, approx_blocks)
    stride = 1 if approx_blocks <= max_blocks else max(1, approx_blocks // max(1, max_blocks))
    creates: list[DiscoveredContract] = []
    blocks_tried = 0
    for i in range(blocks_to_walk if stride == 1 else max_blocks):
        bn = head - (i * stride)
        if bn <= 0:
            break
        blocks_tried += 1
        try:
            block = _rpc(rpc, "eth_getBlockByNumber", [hex(bn), True])
        except Exception:  # noqa: BLE001 — soft-skip flaky RPC block
            time.sleep(0.2)
            continue
        if not isinstance(block, dict):
            continue
        ts = int(block.get("timestamp") or "0x0", 16)
        deployed_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None
        for tx in block.get("transactions") or []:
            if not isinstance(tx, dict):
                continue
            if tx.get("to") not in (None, "", "0x"):
                continue
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
            if len(creates) >= max_results:
                break
        if len(creates) >= max_results:
            break
        if i and i % 25 == 0:
            time.sleep(0.05)
    creates.sort(key=lambda r: r.deployed_block, reverse=True)
    for c in creates:
        c.notes.append("scanned_blocks=%d stride=%d head=%d" % (blocks_tried, stride, head))
    return creates


_VERIFY_LAST_CALL = 0.0
_VERIFY_MIN_INTERVAL_S = 0.35


def _etherscan_verified(address: str, api_key: str) -> tuple[Optional[bool], Optional[str]]:
    global _VERIFY_LAST_CALL
    # Pace verified-source checks so prefer_verified does not trip free-tier 429s.
    gap = _VERIFY_MIN_INTERVAL_S - (time.monotonic() - _VERIFY_LAST_CALL)
    if gap > 0:
        time.sleep(gap)
    _VERIFY_LAST_CALL = time.monotonic()
    qs = urllib.parse.urlencode({
        "chainid": CHAIN_ID,
        "module": "contract",
        "action": "getsourcecode",
        "address": address,
        "apikey": api_key,
    })
    url = "%s?%s" % (ETHERSCAN_V2, qs)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "eth-scanner-discover/0.2"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                body = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                time.sleep(min(30.0, 1.5 ** (attempt + 1)))
                continue
            return None, None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
            return None, None
        result = body.get("result")
        msg = str(body.get("message") or "")
        if isinstance(result, str) and "rate limit" in (result + msg).lower():
            time.sleep(min(30.0, 1.5 ** (attempt + 1)))
            continue
        if isinstance(result, list) and result:
            row = result[0]
            src = (row.get("SourceCode") or "").strip()
            name = (row.get("ContractName") or "").strip() or None
            return (bool(src), name)
        return None, None
    return None, None


def _pick_rpc(preferred: str) -> str:
    urls = resolve_rpc_urls(preferred)
    if urls:
        return urls[0]
    return PUBLIC_RPCS[0] if PUBLIC_RPCS else ""


def _rpc(url: str, method: str, params: list[Any], timeout_s: float = 12.0) -> Any:
    from eth_scanner.ingest.rpc_client import rpc_call
    return rpc_call(url, method, params, timeout_s=timeout_s, user_agent="eth-scanner-discover/0.2")
