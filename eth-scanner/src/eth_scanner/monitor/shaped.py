"""Mined-block watch for fresh TVL and exploit-shaped transactions.

New creates are ordered so a contract that gained TVL is scanned before a
flat one. A mined transaction that contains a flash-loan log and many
other logs, and that touches a watched address, is a shape. Clones with
the same runtime hash are enqueued with it.

Mempool methods are refused. Traces are not used. Nothing is broadcast
and nothing here adds heat.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from eth_scanner.chain.cu_budget import CuBudget
from eth_scanner.research.keccak import keccak256

# Public event signatures. The topic is a label, not a call.
_FLASH_SIGNATURES = (
    "FlashLoan(address,address,uint256,uint256)",
    "Flash(address,address,uint256,uint256,uint256,uint256)",
    "FlashLoan(address,address,address,uint256,uint256,uint16)",
)
MANY_LOGS = 8
DEFAULT_WATCH_CU = 800
DEFAULT_BLOCKS = 20
_MEMPOOL = {
    "eth_newPendingTransactionFilter",
    "eth_getFilterChanges",
    "txpool_content",
    "txpool_inspect",
    "eth_subscribe",
}


def flash_topics() -> set[str]:
    return {"0x" + keccak256(sig.encode("ascii")).hex() for sig in _FLASH_SIGNATURES}


def _addr(value: Any) -> str:
    text = str(value or "").strip().lower()
    if len(text) == 42 and text.startswith("0x"):
        return text
    return ""


def creations_from_receipts(receipts: Iterable[dict[str, Any]]) -> list[str]:
    """Successful contract-creation receipts. Call data is not kept."""
    found: list[str] = []
    seen: set[str] = set()
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        status = str(receipt.get("status") or "0x1").lower()
        if status in {"0x0", "0", "0x00"}:
            continue
        addr = _addr(receipt.get("contractAddress"))
        if addr and addr not in seen:
            seen.add(addr)
            found.append(addr)
    return found


def prioritize(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shaped hits first, then TVL gained, then current funds, then newer."""
    ordered = [dict(row) for row in rows if isinstance(row, dict) and _addr(row.get("address"))]
    for row in ordered:
        row["address"] = _addr(row.get("address"))
        funds = _num(row.get("funds_usd"))
        prev = _num(row.get("prev_funds_usd"))
        row["funds_gain"] = max(0.0, funds - prev)
        row["heat_contribution"] = 0
    ordered.sort(
        key=lambda row: (
            1 if row.get("shaped") else 0,
            row["funds_gain"],
            _num(row.get("funds_usd")),
            -_num(row.get("age_hours")),
        ),
        reverse=True,
    )
    return ordered


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _touched(receipt: dict[str, Any], watched: set[str]) -> list[str]:
    found: list[str] = []
    for key in ("to", "from", "contractAddress"):
        addr = _addr(receipt.get(key))
        if addr in watched and addr not in found:
            found.append(addr)
    for log in receipt.get("logs") or []:
        if not isinstance(log, dict):
            continue
        addr = _addr(log.get("address"))
        if addr in watched and addr not in found:
            found.append(addr)
    return found


def shaped_transactions(
    receipts: Iterable[dict[str, Any]],
    watched: Iterable[str],
) -> list[dict[str, Any]]:
    """Flash-loan log plus many logs, touching a watched address.

    The transaction input is dropped. A pending-transaction object is ignored.
    """
    topics = flash_topics()
    watch = {_addr(addr) for addr in watched}
    watch.discard("")
    if not watch:
        return []
    hits: list[dict[str, Any]] = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        if receipt.get("blockNumber") in (None, "", "pending"):
            continue
        logs = [log for log in (receipt.get("logs") or []) if isinstance(log, dict)]
        flash = False
        for log in logs:
            topic = ""
            topics_in = log.get("topics") or []
            if topics_in:
                topic = str(topics_in[0]).lower()
            if topic in topics:
                flash = True
                break
        if not flash or len(logs) < MANY_LOGS:
            continue
        touched = _touched(receipt, watch)
        if watch and not touched:
            continue
        hits.append({
            "transaction": str(receipt.get("transactionHash") or "")[:66],
            "block": receipt.get("blockNumber"),
            "log_count": len(logs),
            "touched": touched,
            "heat_contribution": 0,
        })
    return hits


def clones_for(code_hash: str, index: Iterable[dict[str, Any]], *, exclude: str = "") -> list[str]:
    """Addresses in a local index with the same runtime hash. No bytecode is copied."""
    wanted = (code_hash or "").lower()
    skip = _addr(exclude)
    found: list[str] = []
    if not wanted:
        return found
    for row in index:
        if not isinstance(row, dict):
            continue
        if str(row.get("runtime_hash") or "").lower() != wanted:
            continue
        addr = _addr(row.get("address"))
        if addr and addr != skip and addr not in found:
            found.append(addr)
    return found


def plan_watch(
    *,
    creates: Iterable[dict[str, Any]] = (),
    receipts: Iterable[dict[str, Any]] = (),
    watched: Iterable[str] = (),
    clone_index: Iterable[dict[str, Any]] = (),
    hashes: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Order fresh contracts and enqueue clones of a shaped hit. Heat stays 0."""
    hits = shaped_transactions(receipts, watched)
    touched = {addr for hit in hits for addr in hit["touched"]}
    rows = []
    for row in creates:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        addr = _addr(item.get("address"))
        item["address"] = addr
        item["shaped"] = addr in touched
        item["source"] = "shaped" if item["shaped"] else "fresh-deploy"
        rows.append(item)
    for addr in touched:
        if any(row["address"] == addr for row in rows):
            continue
        rows.append({
            "address": addr,
            "shaped": True,
            "source": "shaped",
            "funds_usd": 0,
            "prev_funds_usd": 0,
        })
    ranked = prioritize(rows)
    clones: list[dict[str, Any]] = []
    hashes = { _addr(key): value for key, value in (hashes or {}).items() }
    for addr in touched:
        digest = hashes.get(addr) or ""
        for clone in clones_for(digest, clone_index, exclude=addr):
            clones.append({
                "address": clone,
                "source": "clone-of-shaped",
                "matches": addr,
                "heat_contribution": 0,
            })
    for clone in clones:
        if not any(row["address"] == clone["address"] for row in ranked):
            ranked.append({
                "address": clone["address"],
                "shaped": True,
                "source": "clone-of-shaped",
                "funds_usd": 0,
                "funds_gain": 0,
                "heat_contribution": 0,
            })
    return {
        "status": "ok",
        "heat_contribution": 0,
        "shaped": True if hits else False,
        "hits": hits,
        "queue": ranked,
        "clones": clones,
        "note": "Mined receipts only. A flash-loan log with many logs enqueues the watched contract and its bytecode clones. Heat stays 0.",
    }


def live_logs(
    caller: Callable[[str, list[Any]], Any],
    *,
    head: int,
    blocks: int = DEFAULT_BLOCKS,
    budget: Optional[CuBudget] = None,
) -> dict[str, Any]:
    """One eth_getLogs over a short mined range. Mempool methods are refused."""
    budget = budget or CuBudget(DEFAULT_WATCH_CU)
    span = max(1, min(50, int(blocks)))
    start = max(0, int(head) - span + 1)
    if not budget.allow("eth_getLogs"):
        return {"status": "budget", "logs": [], "heat_contribution": 0, "cu": budget.snapshot()}
    budget.charge("eth_getLogs")
    params = [{
        "fromBlock": hex(start),
        "toBlock": hex(int(head)),
        "topics": [sorted(flash_topics())],
    }]
    try:
        logs = caller("eth_getLogs", params)
    except Exception as exc:
        return {
            "status": "error",
            "logs": [],
            "heat_contribution": 0,
            "cu": budget.snapshot(),
            "note": type(exc).__name__,
        }
    if not isinstance(logs, list):
        logs = []
    return {
        "status": "ok",
        "logs": logs,
        "from_block": start,
        "to_block": int(head),
        "heat_contribution": 0,
        "cu": budget.snapshot(),
    }


def refuse_mempool(method: str) -> None:
    if method in _MEMPOOL:
        raise ValueError("mempool methods are not used")


def fetch_receipts(
    caller: Callable[[str, list[Any]], Any],
    tx_hashes: Iterable[str],
    budget: CuBudget,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Read a few mined receipts. The transaction input is discarded."""
    refuse_mempool("eth_getTransactionReceipt")
    kept: list[dict[str, Any]] = []
    for tx in list(tx_hashes)[: max(0, limit)]:
        if not budget.allow("eth_getTransactionReceipt"):
            break
        budget.charge("eth_getTransactionReceipt")
        try:
            receipt = caller("eth_getTransactionReceipt", [tx])
        except Exception:
            continue
        if not isinstance(receipt, dict):
            continue
        logs = []
        for log in receipt.get("logs") or []:
            if isinstance(log, dict):
                logs.append({
                    "address": log.get("address"),
                    "topics": list(log.get("topics") or [])[:1],
                })
        kept.append({
            "transactionHash": receipt.get("transactionHash"),
            "blockNumber": receipt.get("blockNumber"),
            "to": receipt.get("to"),
            "from": receipt.get("from"),
            "contractAddress": receipt.get("contractAddress"),
            "status": receipt.get("status"),
            "logs": logs,
        })
    return kept
