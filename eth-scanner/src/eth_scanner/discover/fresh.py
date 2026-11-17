"""Fast-lane discovery of brand-new mainnet contract deployments.

Polls the chain head for CREATE transactions (top-level ``tx.to is null``,
plus internal CREATE/CREATE2 when the RPC supports traces), cheap-triages
each address with the existing funds probe, and upserts survivors into
``eth_scan_targets`` with ``discovery_source='fresh-deploy'`` so the scan
cycle can pick them up ahead of curated lists and randoms.

Read-only. Never sends a transaction. Skips cleanly when ``ETH_RPC_URL``
is unset — this path does not fall back to public RPCs (those are too
flaky for a tight head-of-chain walk).
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from eth_scanner.discover.creates import discover_creates_in_range, head_block
from eth_scanner.discover.recent import DiscoveredContract
from eth_scanner.ingest.funds import (
    discovery_min_usd,
    format_funds_floor_reason,
    probe_funds_batch,
)
from eth_scanner.known_safe import SAFE_ADDRESSES
from eth_scanner.store.supabase import ScanStore, normalize_address
from eth_scanner.types import FunnelResult, Target

FRESH_SOURCE = "fresh-deploy"
FRESH_CURSOR_ID = "fresh-deploys-head"
# First run (no cursor) looks back ~10 minutes of 12s blocks, with overlap
# across the 5-minute cron so a missed tick still gets covered.
DEFAULT_LOOKBACK_BLOCKS = 50
DEFAULT_MAX_BLOCKS = 100
DEFAULT_REQUEUE_HOURS = 24.0
ZERO_ADDRESS = "0x" + "0" * 40


@dataclass
class CreationTx:
    """A top-level contract-creation transaction extracted from a block."""

    tx_hash: str
    block_number: int
    deployed_at: Optional[str] = None
    sender: Optional[str] = None
    nonce: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FreshDeployStats:
    status: str = "running"  # running | done | noop | error
    rpc_configured: bool = False
    from_block: int = 0
    to_block: int = 0
    head_block: int = 0
    cursor_start: int = 0
    cursor_next: int = 0
    creates_found: int = 0
    known_safe_skipped: int = 0
    already_present: int = 0
    enqueued: int = 0
    requeued: int = 0
    below_floor: int = 0
    funds_unknown: int = 0
    source: str = ""
    message: str = ""
    errors: list[str] = field(default_factory=list)
    enqueued_addresses: list[str] = field(default_factory=list)
    below_floor_addresses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_creation_tx(tx: Any) -> bool:
    """True when a transaction is a top-level contract creation (``to`` is null)."""
    if not isinstance(tx, dict):
        return False
    to = tx.get("to")
    return to in (None, "", "0x")


def block_timestamp_iso(block: dict[str, Any]) -> Optional[str]:
    raw = block.get("timestamp") if isinstance(block, dict) else None
    ts = _as_int(raw)
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def extract_creation_txs(block: dict[str, Any]) -> list[CreationTx]:
    """Pull top-level create candidates from an ``eth_getBlockByNumber(..., true)`` result."""
    if not isinstance(block, dict):
        return []
    number = _as_int(block.get("number") or block.get("blockNumber"))
    deployed_at = block_timestamp_iso(block)
    out: list[CreationTx] = []
    for tx in block.get("transactions") or []:
        if not is_creation_tx(tx):
            continue
        tx_hash = str(tx.get("hash") or "").strip()
        if not tx_hash:
            continue
        nonce = _as_int(tx.get("nonce")) if tx.get("nonce") is not None else None
        sender = str(tx.get("from") or "") or None
        out.append(CreationTx(
            tx_hash=tx_hash,
            block_number=number,
            deployed_at=deployed_at,
            sender=sender.lower() if sender else None,
            nonce=nonce,
        ))
    return out


def contract_address_from_receipt(receipt: Any) -> Optional[str]:
    """Return the created contract address from a receipt, or None if it failed / isn't a create."""
    if not isinstance(receipt, dict):
        return None
    status = receipt.get("status")
    if status in (0, "0", "0x0", "0x00"):
        return None
    addr = (receipt.get("contractAddress") or "").strip().lower()
    if not addr or addr == ZERO_ADDRESS or len(addr) != 42 or not addr.startswith("0x"):
        return None
    return addr


def contracts_from_block(
    block: dict[str, Any],
    receipts: dict[str, Any],
) -> list[DiscoveredContract]:
    """Combine a full block with a ``tx_hash -> receipt`` map into discovered creates."""
    deployed_at = block_timestamp_iso(block) if isinstance(block, dict) else None
    number = _as_int((block or {}).get("number") or (block or {}).get("blockNumber"))
    out: list[DiscoveredContract] = []
    seen: set[str] = set()
    for tx in extract_creation_txs(block or {}):
        receipt = receipts.get(tx.tx_hash) if isinstance(receipts, dict) else None
        addr = contract_address_from_receipt(receipt)
        if not addr or addr in seen:
            continue
        seen.add(addr)
        out.append(DiscoveredContract(
            address=addr,
            deployed_block=tx.block_number or number,
            deployed_at=tx.deployed_at or deployed_at,
            tx_hash=tx.tx_hash,
            source="rpc-create",
        ))
    return out


def rpc_url_from_env(explicit: str = "") -> str:
    """The fresh-deploy lane requires an explicit RPC; no public fallback."""
    url = (explicit or os.environ.get("ETH_RPC_URL") or "").strip()
    return url.rstrip("/")


def lookback_blocks() -> int:
    return _env_int("ETH_SCANNER_FRESH_LOOKBACK_BLOCKS", DEFAULT_LOOKBACK_BLOCKS, minimum=1)


def max_blocks_per_run() -> int:
    return _env_int("ETH_SCANNER_FRESH_MAX_BLOCKS", DEFAULT_MAX_BLOCKS, minimum=1)


def requeue_hours() -> float:
    raw = (os.environ.get("ETH_SCANNER_FRESH_REQUEUE_HOURS") or "").strip()
    if not raw:
        return DEFAULT_REQUEUE_HOURS
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_REQUEUE_HOURS


def cursor_id() -> str:
    return (os.environ.get("ETH_SCANNER_FRESH_CURSOR_ID") or FRESH_CURSOR_ID).strip() or FRESH_CURSOR_ID


def run_fresh_deploy_discovery(
    *,
    store: ScanStore,
    rpc_url: str = "",
    lookback: Optional[int] = None,
    max_blocks: Optional[int] = None,
    min_funds_usd: Optional[float] = None,
    reset: bool = False,
    now: Optional[datetime] = None,
    discover_fn=None,
    head_fn=None,
    probe_fn=None,
) -> FreshDeployStats:
    """Walk [cursor+1, head] (capped), triage, upsert, then advance the cursor.

    When ``ETH_RPC_URL`` (or ``rpc_url``) is unset the run is a no-op: the
    cursor is left alone and no exception is raised.
    """
    stats = FreshDeployStats()
    rpc = rpc_url_from_env(rpc_url)
    stats.rpc_configured = bool(rpc)
    if not rpc:
        stats.status = "noop"
        stats.message = "ETH_RPC_URL unset — fresh-deploy discovery skipped"
        return stats

    floor = discovery_min_usd() if min_funds_usd is None else max(0.0, float(min_funds_usd))
    window = lookback_blocks() if lookback is None else max(1, int(lookback))
    cap = max_blocks_per_run() if max_blocks is None else max(1, int(max_blocks))
    cid = cursor_id()
    head_fn = head_fn or (lambda: head_block(rpc))
    discover_fn = discover_fn or (
        lambda lo, hi: discover_creates_in_range(lo, hi, rpc_url=rpc)
    )

    try:
        head = int(head_fn())
    except Exception as exc:  # noqa: BLE001
        stats.status = "error"
        stats.message = "head lookup failed: %s" % str(exc)[:200]
        stats.errors.append(stats.message)
        return stats
    stats.head_block = head
    if head <= 0:
        stats.status = "error"
        stats.message = "RPC returned an empty head block"
        return stats

    stored = _read_cursor(store, cid)
    if reset or not stored:
        start = max(0, head - window)
        cursor = start - 1 if start > 0 else 0
    else:
        cursor = int(stored.get("cursor_block") or 0)
        # If we fell far behind, catch up in cap-sized chunks rather than
        # skipping the gap (missing a funded deploy would defeat the lane).
    stats.cursor_start = cursor
    from_block = cursor + 1
    if from_block > head:
        stats.status = "done"
        stats.from_block = from_block
        stats.to_block = head
        stats.cursor_next = cursor
        stats.message = "cursor is already at the chain head"
        return stats
    to_block = min(head, from_block + cap - 1)
    stats.from_block = from_block
    stats.to_block = to_block

    try:
        discovered, chunk_stats = discover_fn(from_block, to_block)
    except Exception as exc:  # noqa: BLE001
        stats.status = "error"
        stats.message = "create walk failed: %s" % str(exc)[:200]
        stats.errors.append(stats.message)
        return stats

    if hasattr(chunk_stats, "source"):
        stats.source = str(getattr(chunk_stats, "source") or "")
    if hasattr(chunk_stats, "errors"):
        for err in getattr(chunk_stats, "errors") or []:
            stats.errors.append(str(err)[:200])
    if stats.source == "unavailable":
        stats.status = "error"
        stats.message = "no create source available for blocks %d-%d" % (from_block, to_block)
        return stats

    rows = list(discovered or [])
    stats.creates_found = len(rows)
    triage = enqueue_fresh_contracts(
        store,
        rows,
        rpc_url=rpc,
        min_funds_usd=floor,
        now=now,
        probe_fn=probe_fn,
    )
    stats.known_safe_skipped = triage["known_safe_skipped"]
    stats.already_present = triage["already_present"]
    stats.enqueued = triage["enqueued"]
    stats.requeued = triage["requeued"]
    stats.below_floor = triage["below_floor"]
    stats.funds_unknown = triage["funds_unknown"]
    stats.enqueued_addresses = list(triage["enqueued_addresses"])
    stats.below_floor_addresses = list(triage["below_floor_addresses"])

    _write_cursor(
        store,
        cid,
        cursor_block=to_block,
        start_block=int((stored or {}).get("start_block") or from_block),
        end_block=head,
        stats=stats,
    )
    stats.cursor_next = to_block
    stats.status = "done"
    stats.message = (
        "fresh-deploys blocks=%d-%d creates=%d enqueued=%d requeued=%d "
        "below_floor=%d already=%d source=%s"
        % (
            from_block,
            to_block,
            stats.creates_found,
            stats.enqueued,
            stats.requeued,
            stats.below_floor,
            stats.already_present,
            stats.source or "unknown",
        )
    )
    return stats


def enqueue_fresh_contracts(
    store: ScanStore,
    rows: list[DiscoveredContract],
    *,
    rpc_url: str = "",
    min_funds_usd: Optional[float] = None,
    now: Optional[datetime] = None,
    probe_fn=None,
) -> dict[str, Any]:
    """Cheap-triage discovered creates and upsert new / re-funded rows.

    Floor policy (same as the backfill lane):
    - Known balance below the $100 intake floor → status=skipped + cool result.
    - Unknown / failed probe → enqueue as pending (never a silent drop).
    - Already pending/running/done/error → leave the row alone (idempotent).
    - Previously skipped for the floor, now funded, and still young → re-queue.
    """
    floor = discovery_min_usd() if min_funds_usd is None else max(0.0, float(min_funds_usd))
    moment = now or datetime.now(timezone.utc)
    out = {
        "known_safe_skipped": 0,
        "already_present": 0,
        "enqueued": 0,
        "requeued": 0,
        "below_floor": 0,
        "funds_unknown": 0,
        "enqueued_addresses": [],
        "below_floor_addresses": [],
    }
    unique: list[DiscoveredContract] = []
    seen: set[str] = set()
    for row in rows or []:
        addr = normalize_address(getattr(row, "address", "") or "")
        if not addr or addr == ZERO_ADDRESS:
            continue
        if addr in seen:
            continue
        seen.add(addr)
        if addr in SAFE_ADDRESSES:
            out["known_safe_skipped"] += 1
            continue
        unique.append(row)

    if not unique:
        return out

    addrs = [normalize_address(r.address) for r in unique]
    probe = probe_fn or (
        lambda addresses: probe_funds_batch(addresses, rpc_url=rpc_url, batch_size=40)
    )
    snaps = probe(addrs) or {}

    for row in unique:
        addr = normalize_address(row.address)
        snap = _snap_for(snaps, addr)
        funds_usd = snap.total_usd if snap and getattr(snap, "status", "") == "ok" else None
        funds_status = getattr(snap, "status", None) if snap else "unknown"
        funds_checked = getattr(snap, "checked_at", None) if snap else None
        breakdown = list((snap.to_dict().get("breakdown") or []) if snap and hasattr(snap, "to_dict") else [])
        existing = store.get_target(addr)
        action = _plan_enqueue(
            existing,
            funds_usd=funds_usd,
            funds_status=funds_status,
            floor=floor,
            now=moment,
        )
        if action == "exists":
            out["already_present"] += 1
            continue
        if action == "below_floor":
            _write_skipped_floor(
                store, addr, row, funds_usd, funds_status, funds_checked, breakdown, floor,
            )
            out["below_floor"] += 1
            out["below_floor_addresses"].append(addr)
            continue
        if funds_status == "unknown" or funds_usd is None:
            out["funds_unknown"] += 1
        store.upsert_target(Target(
            address=addr,
            status="pending",
            has_code=True,
            funds_usd=funds_usd,
            funds_breakdown=breakdown,
            funds_status=funds_status,
            funds_checked_at=funds_checked,
            tvl_usd=funds_usd,
            deployed_block=getattr(row, "deployed_block", None),
            deployed_at=getattr(row, "deployed_at", None),
            discovery_source=FRESH_SOURCE,
        ))
        if action == "requeue":
            out["requeued"] += 1
        else:
            out["enqueued"] += 1
        out["enqueued_addresses"].append(addr)
    return out


def _plan_enqueue(
    existing: Optional[dict[str, Any]],
    *,
    funds_usd: Optional[float],
    funds_status: Optional[str],
    floor: float,
    now: datetime,
) -> str:
    """Return 'enqueue' | 'requeue' | 'below_floor' | 'exists'."""
    below = funds_status == "ok" and funds_usd is not None and funds_usd < floor
    if not existing:
        return "below_floor" if below else "enqueue"
    status = str(existing.get("status") or "")
    if status in {"pending", "running", "done", "error"}:
        return "exists"
    if status == "skipped" and _floor_skip(existing):
        if not below and _still_young(existing, now):
            return "requeue"
        # Still dusty, or past the young-deploy window: leave (or refresh) skipped.
        return "below_floor" if below else "exists"
    if status == "skipped":
        return "exists"
    # Unknown prior status with no row conflict.
    return "below_floor" if below else "enqueue"


def _floor_skip(row: dict[str, Any]) -> bool:
    source = str(row.get("discovery_source") or "")
    if source not in {FRESH_SOURCE, "backfill", "rpc-create", "etherscan-verified"}:
        # Don't promote unrelated skips (stale-claim cap, known-safe, etc.).
        if source:
            return False
    reason = str(row.get("drop_reason") or "")
    notes = row.get("notes") or []
    blob = " ".join([reason] + [str(n) for n in notes])
    if "below funds floor" in blob:
        return True
    if str(row.get("funds_status") or "") == "ok":
        try:
            usd = float(row.get("funds_usd"))
        except (TypeError, ValueError):
            return False
        return usd < discovery_min_usd()
    return False


def _still_young(row: dict[str, Any], now: datetime) -> bool:
    hours = requeue_hours()
    if hours <= 0:
        return False
    raw = row.get("deployed_at") or row.get("created_at") or row.get("updated_at")
    if not raw:
        # No timestamp: allow one re-queue so a late funder is not stuck.
        return True
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return now - stamp <= timedelta(hours=hours)


def _write_skipped_floor(
    store: ScanStore,
    addr: str,
    row: DiscoveredContract,
    funds_usd: Optional[float],
    funds_status: Optional[str],
    funds_checked: Optional[str],
    breakdown: list[dict[str, Any]],
    floor: float,
) -> None:
    reason = format_funds_floor_reason(float(funds_usd or 0.0), floor)
    store.upsert_target(Target(
        address=addr,
        status="skipped",
        has_code=True,
        funds_usd=funds_usd,
        funds_breakdown=breakdown,
        funds_status=funds_status,
        funds_checked_at=funds_checked,
        tvl_usd=funds_usd,
        deployed_block=getattr(row, "deployed_block", None),
        deployed_at=getattr(row, "deployed_at", None),
        discovery_source=FRESH_SOURCE,
    ))
    store.save_result(addr, FunnelResult(
        bucket="lane-a-cool",
        dropped=True,
        drop_reason=reason,
        heat=0,
        src_confidence="low",
        ir_confidence="low",
        funds_usd=funds_usd,
        funds_status=funds_status,
        funds_checked_at=funds_checked,
        funds_breakdown=breakdown,
        notes=["fresh-deploy cheap funds floor — full scan skipped", reason],
    ))


def _snap_for(snaps: dict[str, Any], addr: str) -> Any:
    if not isinstance(snaps, dict):
        return None
    if addr in snaps:
        return snaps[addr]
    low = addr.lower()
    for key, value in snaps.items():
        if str(key).lower() == low:
            return value
    return None


def _read_cursor(store: ScanStore, cid: str) -> Optional[dict[str, Any]]:
    fn = getattr(store, "get_backfill", None)
    if not callable(fn):
        return None
    try:
        row = fn(cid)
    except Exception:  # noqa: BLE001
        return None
    return row if isinstance(row, dict) else None


def _write_cursor(
    store: ScanStore,
    cid: str,
    *,
    cursor_block: int,
    start_block: int,
    end_block: int,
    stats: FreshDeployStats,
) -> None:
    fn = getattr(store, "upsert_backfill", None)
    if not callable(fn):
        return
    body = {
        "id": cid,
        "start_block": int(start_block),
        "end_block": int(end_block),
        "cursor_block": int(cursor_block),
        "status": "running" if cursor_block < end_block else "done",
        "source": FRESH_SOURCE,
        "stats": {
            "creates_found": stats.creates_found,
            "enqueued": stats.enqueued,
            "requeued": stats.requeued,
            "below_floor": stats.below_floor,
            "already_present": stats.already_present,
            "funds_unknown": stats.funds_unknown,
            "source": stats.source,
            "head_block": stats.head_block,
            "from_block": stats.from_block,
            "to_block": stats.to_block,
        },
        "last_error": (stats.errors[0] if stats.errors else "")[:240],
    }
    try:
        fn(body)
    except Exception:  # noqa: BLE001
        return


def _as_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, int):
        return value
    text = str(value).strip()
    try:
        if text.startswith("0x") or text.startswith("0X"):
            return int(text, 16)
        return int(text)
    except (TypeError, ValueError):
        return 0


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return max(minimum, int(default))
    try:
        return max(minimum, int(raw, 10))
    except (TypeError, ValueError):
        return max(minimum, int(default))
