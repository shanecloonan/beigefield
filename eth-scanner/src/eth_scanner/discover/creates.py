"""Efficient mainnet contract-create discovery (read-only).

Prefer Alchemy `trace_filter` (includes CREATE/CREATE2, including factory
internals). Fall back to `alchemy_getAssetTransfers` (top-level creates) then
a dense receipt walk for small chunks when traces are unavailable.

Never sends a transaction.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from eth_scanner.discover.recent import DiscoveredContract
from eth_scanner.ingest.funds import resolve_rpc_urls
from eth_scanner.known_safe import SAFE_ADDRESSES

DEFAULT_CHUNK_BLOCKS = 2_000
TRACE_PAGE = 1_000


@dataclass
class CreateChunkStats:
    from_block: int = 0
    to_block: int = 0
    creates: int = 0
    source: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def approx_blocks_for_days(days: float = 30.0) -> int:
    return max(1, int(days * 24 * 3600 / 12))


def head_block(rpc_url: str = "") -> int:
    rpc = _pick_rpc(rpc_url)
    raw = _rpc(rpc, "eth_blockNumber", [])
    return int(raw, 16)


def discover_creates_in_range(
    from_block: int,
    to_block: int,
    *,
    rpc_url: str = "",
    max_results: int = 50_000,
) -> tuple[list[DiscoveredContract], CreateChunkStats]:
    """Return creates in [from_block, to_block] inclusive (newest-first)."""
    if to_block < from_block:
        return [], CreateChunkStats(from_block=from_block, to_block=to_block, source="empty")
    rpc = _pick_rpc(rpc_url)
    stats = CreateChunkStats(from_block=from_block, to_block=to_block)
    rows: list[DiscoveredContract] = []

    # 1) Alchemy / OpenEthereum-style trace_filter (factory creates included).
    try:
        rows = _via_trace_filter(rpc, from_block, to_block, max_results=max_results)
        if rows is not None:
            stats.source = "trace_filter"
            stats.creates = len(rows)
            return _finalize(rows, max_results), stats
    except Exception as exc:  # noqa: BLE001
        stats.errors.append("trace_filter: %s" % str(exc)[:160])

    # 2) Alchemy asset transfers — top-level creates only (to is null).
    try:
        rows = _via_asset_transfers(rpc, from_block, to_block, max_results=max_results)
        if rows is not None:
            stats.source = "alchemy_getAssetTransfers"
            stats.creates = len(rows)
            return _finalize(rows, max_results), stats
    except Exception as exc:  # noqa: BLE001
        stats.errors.append("asset_transfers: %s" % str(exc)[:160])

    # 3) Dense receipt walk — only for modest chunks (rate-limit safe).
    span = to_block - from_block + 1
    if span <= 400:
        try:
            rows = _via_receipt_walk(rpc, from_block, to_block, max_results=max_results)
            stats.source = "rpc-receipt-walk"
            stats.creates = len(rows)
            return _finalize(rows, max_results), stats
        except Exception as exc:  # noqa: BLE001
            stats.errors.append("receipt_walk: %s" % str(exc)[:160])
    else:
        stats.errors.append(
            "no efficient create source; chunk %d blocks too large for receipt walk" % span
        )

    stats.source = "unavailable"
    return [], stats


def _via_trace_filter(
    rpc: str,
    from_block: int,
    to_block: int,
    *,
    max_results: int,
) -> Optional[list[DiscoveredContract]]:
    out: list[DiscoveredContract] = []
    after = 0
    while len(out) < max_results:
        params = [{
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "after": after,
            "count": min(TRACE_PAGE, max_results - len(out)),
        }]
        try:
            result = _rpc(rpc, "trace_filter", params, timeout_s=60.0)
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "not available" in msg or "method not found" in msg or "not supported" in msg:
                return None
            # Shrink hint: caller may retry smaller chunks; surface error.
            raise
        if result is None:
            return None
        if not isinstance(result, list):
            return None
        if not result:
            break
        for tr in result:
            if not isinstance(tr, dict):
                continue
            typ = str(tr.get("type") or "").lower()
            if typ not in {"create", "create2"}:
                continue
            res = tr.get("result") or {}
            addr = ""
            if isinstance(res, dict):
                addr = (res.get("address") or "").lower()
            if not addr or addr == "0x" + "0" * 40:
                continue
            if addr in SAFE_ADDRESSES:
                continue
            bn = tr.get("blockNumber")
            try:
                block = int(bn, 16) if isinstance(bn, str) else int(bn or 0)
            except (TypeError, ValueError):
                block = from_block
            out.append(DiscoveredContract(
                address=addr,
                deployed_block=block,
                tx_hash=str(tr.get("transactionHash") or "") or None,
                source="trace-%s" % typ,
                notes=["factory-or-top-level create via trace_filter"],
            ))
        after += len(result)
        if len(result) < TRACE_PAGE:
            break
        time.sleep(0.05)
    return out


def _via_asset_transfers(
    rpc: str,
    from_block: int,
    to_block: int,
    *,
    max_results: int,
) -> Optional[list[DiscoveredContract]]:
    out: list[DiscoveredContract] = []
    page_key: Optional[str] = None
    while len(out) < max_results:
        params: dict[str, Any] = {
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "category": ["external"],
            "excludeZeroValue": False,
            "withMetadata": False,
            "maxCount": hex(min(1000, max_results - len(out))),
        }
        if page_key:
            params["pageKey"] = page_key
        try:
            result = _rpc(rpc, "alchemy_getAssetTransfers", [params], timeout_s=45.0)
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "not available" in msg or "method not found" in msg or "alchemy" in msg and "unauthorized" in msg:
                return None
            if "method not found" in msg or "-32601" in msg:
                return None
            raise
        if not isinstance(result, dict):
            return None
        transfers = result.get("transfers") or []
        for tr in transfers:
            if not isinstance(tr, dict):
                continue
            # Contract creation: external transfer with null `to`.
            if tr.get("to") not in (None, "", "0x"):
                continue
            tx_hash = tr.get("hash")
            if not tx_hash:
                continue
            try:
                receipt = _rpc(rpc, "eth_getTransactionReceipt", [tx_hash], timeout_s=20.0)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(receipt, dict):
                continue
            addr = (receipt.get("contractAddress") or "").lower()
            if not addr or addr == "0x" + "0" * 40 or len(addr) != 42:
                continue
            if addr in SAFE_ADDRESSES:
                continue
            bn = tr.get("blockNum")
            try:
                block = int(bn, 16) if isinstance(bn, str) else int(bn or 0)
            except (TypeError, ValueError):
                block = from_block
            out.append(DiscoveredContract(
                address=addr,
                deployed_block=block,
                tx_hash=str(tx_hash),
                source="alchemy-transfer-create",
                notes=["top-level create via alchemy_getAssetTransfers+receipt"],
            ))
            if len(out) >= max_results:
                break
        page_key = result.get("pageKey")
        if not page_key or len(out) >= max_results:
            break
        time.sleep(0.05)
    return out


def _via_receipt_walk(
    rpc: str,
    from_block: int,
    to_block: int,
    *,
    max_results: int,
) -> list[DiscoveredContract]:
    out: list[DiscoveredContract] = []
    for bn in range(to_block, from_block - 1, -1):
        block = _rpc(rpc, "eth_getBlockByNumber", [hex(bn), True], timeout_s=30.0)
        if not isinstance(block, dict):
            continue
        for tx in block.get("transactions") or []:
            if not isinstance(tx, dict):
                continue
            if tx.get("to") not in (None, "", "0x"):
                continue
            tx_hash = tx.get("hash")
            if not tx_hash:
                continue
            try:
                receipt = _rpc(rpc, "eth_getTransactionReceipt", [tx_hash], timeout_s=20.0)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(receipt, dict):
                continue
            created = (receipt.get("contractAddress") or "").lower()
            if not created or created == "0x" + "0" * 40:
                continue
            if created in SAFE_ADDRESSES:
                continue
            out.append(DiscoveredContract(
                address=created,
                deployed_block=bn,
                tx_hash=str(tx_hash),
                source="rpc-create",
            ))
            if len(out) >= max_results:
                return out
        if (to_block - bn) % 40 == 0:
            time.sleep(0.05)
    return out


def _finalize(rows: list[DiscoveredContract], max_results: int) -> list[DiscoveredContract]:
    seen: set[str] = set()
    out: list[DiscoveredContract] = []
    rows = sorted(rows, key=lambda r: r.deployed_block, reverse=True)
    for row in rows:
        addr = row.address.lower()
        if addr in seen:
            continue
        seen.add(addr)
        out.append(row)
        if len(out) >= max_results:
            break
    return out


def _pick_rpc(preferred: str) -> str:
    urls = resolve_rpc_urls(preferred)
    if not urls:
        raise RuntimeError("no RPC URL available")
    return urls[0]


def _rpc(url: str, method: str, params: list[Any], timeout_s: float = 30.0) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "eth-scanner-backfill/0.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError("HTTP %s %s" % (exc.code, err)) from exc
    if body.get("error"):
        raise RuntimeError(str(body["error"])[:240])
    return body.get("result")
