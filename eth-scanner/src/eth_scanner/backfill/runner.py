"""Checkpointed 30-day (or custom) mainnet create backfill.

Flow per chunk:
  1. Discover CREATE/CREATE2 via Alchemy trace_filter (factory creates included)
  2. Dedupe against existing eth_scan_targets
  3. Cheap Multicall3 funds floor ($100) in batches
  4. Full Lane A only for funds >= floor (known-safe / token-only drops + evidence heat)
  5. Advance cursor_block and persist stats

Read-only chain I/O. Never sends a transaction.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from eth_scanner.config import Settings, load_settings
from eth_scanner.discover.creates import (
    DEFAULT_CHUNK_BLOCKS,
    approx_blocks_for_days,
    discover_creates_in_range,
    head_block,
)
from eth_scanner.ingest.funds import (
    DEFAULT_MIN_FUNDS_USD,
    format_funds_floor_reason,
    probe_funds_batch,
)
from eth_scanner.known_safe import SAFE_ADDRESSES
from eth_scanner.lane_a import worker as lane_a
from eth_scanner.store.supabase import ScanStore, normalize_address, open_store
from eth_scanner.types import FunnelResult, Target

BACKFILL_ID = "mainnet-30d"
DEFAULT_LOOKBACK_DAYS = 30.0


@dataclass
class BackfillProgress:
    id: str = BACKFILL_ID
    status: str = "running"  # running | done | error | noop
    start_block: int = 0
    end_block: int = 0
    cursor_block: int = 0
    blocks_remaining: int = 0
    blocks_covered_this_job: int = 0
    discovered_this_job: int = 0
    deduped_this_job: int = 0
    funds_ge_floor_this_job: int = 0
    funds_below_floor_this_job: int = 0
    funds_unknown_this_job: int = 0
    fully_scanned_this_job: int = 0
    heat_positive_this_job: int = 0
    heat_positive_samples: list[dict[str, Any]] = field(default_factory=list)
    discovered_total: int = 0
    funds_ge_floor_total: int = 0
    fully_scanned_total: int = 0
    heat_positive_total: int = 0
    source: str = ""
    duration_s: float = 0.0
    eta_hours: Optional[float] = None
    message: str = ""
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_backfill_job(
    *,
    settings: Optional[Settings] = None,
    store: Optional[ScanStore] = None,
    backfill_id: str = BACKFILL_ID,
    lookback_days: float = DEFAULT_LOOKBACK_DAYS,
    chunk_blocks: int = DEFAULT_CHUNK_BLOCKS,
    workers: int = 8,
    deadline_minutes: float = 40.0,
    min_funds_usd: float = DEFAULT_MIN_FUNDS_USD,
    max_full_scans: int = 200,
    reset: bool = False,
) -> BackfillProgress:
    settings = settings or load_settings()
    store = store or open_store(settings)
    started = time.monotonic()
    deadline = started + max(60.0, float(deadline_minutes) * 60.0)
    progress = BackfillProgress(id=backfill_id)
    rpc = getattr(settings, "eth_rpc_url", "") or ""

    try:
        head = head_block(rpc)
    except Exception as exc:  # noqa: BLE001
        progress.status = "error"
        progress.last_error = "head_block: %s" % str(exc)[:200]
        progress.duration_s = round(time.monotonic() - started, 1)
        return progress

    span = approx_blocks_for_days(lookback_days)
    window_start = max(0, head - span)
    row = None
    get_bf = getattr(store, "get_backfill", None)
    if callable(get_bf) and not reset:
        try:
            row = get_bf(backfill_id)
        except Exception:  # noqa: BLE001
            row = None

    if row and str(row.get("status") or "") == "done" and int(row.get("cursor_block") or 0) >= int(row.get("end_block") or 0):
        # Refresh end_block to current head; if already caught up → noop.
        if int(row.get("cursor_block") or 0) >= head:
            progress.status = "noop"
            progress.start_block = int(row.get("start_block") or window_start)
            progress.end_block = head
            progress.cursor_block = int(row.get("cursor_block") or head)
            progress.message = "backfill caught up — no-op"
            progress.duration_s = round(time.monotonic() - started, 1)
            _persist_progress(store, progress, row)
            return progress
        # Extend end to head and resume.
        row = dict(row)
        row["end_block"] = head
        row["status"] = "running"

    if not row or reset:
        row = {
            "id": backfill_id,
            "start_block": window_start,
            "end_block": head,
            "cursor_block": window_start - 1,
            "status": "running",
            "source": "",
            "discovered": 0,
            "deduped": 0,
            "funds_ge_floor": 0,
            "funds_below_floor": 0,
            "funds_unknown": 0,
            "fully_scanned": 0,
            "heat_positive": 0,
            "stats": {},
        }
        upsert = getattr(store, "upsert_backfill", None)
        if callable(upsert):
            upsert(row)

    start_block = int(row["start_block"])
    end_block = max(int(row["end_block"]), head)
    cursor = int(row["cursor_block"])
    progress.start_block = start_block
    progress.end_block = end_block
    progress.cursor_block = cursor
    progress.discovered_total = int(row.get("discovered") or 0)
    progress.funds_ge_floor_total = int(row.get("funds_ge_floor") or 0)
    progress.fully_scanned_total = int(row.get("fully_scanned") or 0)
    progress.heat_positive_total = int(row.get("heat_positive") or 0)

    if cursor >= end_block:
        progress.status = "done"
        progress.message = "cursor reached end_block"
        progress.blocks_remaining = 0
        progress.duration_s = round(time.monotonic() - started, 1)
        _persist_progress(store, progress, row)
        return progress

    chunk = max(100, int(chunk_blocks))
    workers = max(1, min(int(workers or 1), 16))
    full_budget = max(0, int(max_full_scans))

    while cursor < end_block and time.monotonic() < deadline:
        # Soft headroom for in-flight full scans.
        left = deadline - time.monotonic()
        budget = max(1.0, deadline - started)
        headroom = min(90.0, max(5.0, budget * 0.05))
        if progress.blocks_covered_this_job > 0 and left < headroom:
            break

        from_b = cursor + 1
        to_b = min(end_block, from_b + chunk - 1)
        # If efficient discovery fails on large chunks, shrink once.
        creates, cstats = discover_creates_in_range(from_b, to_b, rpc_url=rpc)
        if cstats.source == "unavailable" and (to_b - from_b) > 400:
            mid = from_b + min(399, to_b - from_b)
            creates, cstats = discover_creates_in_range(from_b, mid, rpc_url=rpc)
            to_b = mid
        progress.source = cstats.source or progress.source
        if cstats.errors and cstats.source == "unavailable":
            progress.last_error = "; ".join(cstats.errors)[:240]
            # Still advance a tiny bit via receipt walk attempt on 100 blocks to avoid stall.
            tiny_to = min(end_block, from_b + 99)
            creates, cstats = discover_creates_in_range(from_b, tiny_to, rpc_url=rpc)
            to_b = tiny_to
            progress.source = cstats.source or progress.source

        # Dedupe against store + known-safe.
        fresh: list = []
        for row_c in creates:
            addr = normalize_address(row_c.address)
            if addr in SAFE_ADDRESSES:
                progress.deduped_this_job += 1
                continue
            existing = store.get_target(addr)
            if existing:
                progress.deduped_this_job += 1
                continue
            fresh.append(row_c)
        progress.discovered_this_job += len(fresh)

        # Cheap funds floor (batch multicall).
        fund_snaps = probe_funds_batch(
            [r.address for r in fresh],
            rpc_url=rpc,
            batch_size=40,
        ) if fresh else {}

        to_full: list[tuple[Any, float]] = []
        for row_c in fresh:
            addr = normalize_address(row_c.address)
            snap = fund_snaps.get(addr)
            funds_usd = snap.total_usd if snap and snap.status == "ok" else None
            funds_status = snap.status if snap else "unknown"
            if funds_status == "ok" and funds_usd is not None and funds_usd < min_funds_usd:
                progress.funds_below_floor_this_job += 1
                reason = format_funds_floor_reason(funds_usd, min_funds_usd)
                store.upsert_target(Target(
                    address=addr,
                    status="skipped",
                    has_code=True,
                    funds_usd=funds_usd,
                    funds_breakdown=list(snap.to_dict().get("breakdown") or []) if snap else [],
                    funds_status=funds_status,
                    funds_checked_at=snap.checked_at if snap else None,
                    deployed_block=row_c.deployed_block,
                    deployed_at=row_c.deployed_at,
                    discovery_source="backfill",
                ))
                # Persist a cool drop result for visibility.
                store.save_result(addr, FunnelResult(
                    bucket="lane-a-cool",
                    dropped=True,
                    drop_reason=reason,
                    heat=0,
                    src_confidence="low",
                    ir_confidence="low",
                    funds_usd=funds_usd,
                    funds_status=funds_status,
                    notes=["backfill cheap funds floor — full scan skipped", reason],
                ))
                continue
            if funds_status == "unknown" or funds_usd is None:
                progress.funds_unknown_this_job += 1
            else:
                progress.funds_ge_floor_this_job += 1
            store.upsert_target(Target(
                address=addr,
                status="pending",
                has_code=True,
                funds_usd=funds_usd,
                funds_breakdown=list(snap.to_dict().get("breakdown") or []) if snap else [],
                funds_status=funds_status,
                funds_checked_at=snap.checked_at if snap else None,
                tvl_usd=funds_usd,
                deployed_block=row_c.deployed_block,
                deployed_at=row_c.deployed_at,
                discovery_source="backfill",
            ))
            to_full.append((row_c, float(funds_usd or 0.0)))

        # Full Lane A for funded (or unknown) creates — capped per job.
        # Money-at-risk / known-safe / token-only drops happen inside Lane A
        # (evidence-only heat). Cheap floor already filtered dust.
        if full_budget <= 0:
            scan_rows = []
        else:
            scan_rows = to_full[:full_budget]
            full_budget -= len(scan_rows)
        if scan_rows:
            results = _run_full_parallel(
                [normalize_address(r.address) for r, _ in scan_rows],
                settings=settings,
                workers=workers,
                deadline_monotonic=deadline,
            )
            for addr, fr in results:
                progress.fully_scanned_this_job += 1
                heat = int(getattr(fr, "heat", 0) or 0)
                if heat > 0:
                    progress.heat_positive_this_job += 1
                    if len(progress.heat_positive_samples) < 20:
                        progress.heat_positive_samples.append({
                            "address": addr,
                            "heat": heat,
                            "bucket": getattr(fr, "bucket", None),
                            "contract_class": getattr(fr, "contract_class", None),
                            "drop_reason": getattr(fr, "drop_reason", None),
                            "funds_usd": getattr(fr, "funds_usd", None),
                            "heat_breakdown": getattr(fr, "heat_breakdown", None),
                        })

        # Advance cursor past this chunk and checkpoint.
        cursor = to_b
        progress.cursor_block = cursor
        progress.blocks_covered_this_job += (to_b - from_b + 1)
        progress.blocks_remaining = max(0, end_block - cursor)
        row["end_block"] = end_block
        _checkpoint(store, row, progress)

        time.sleep(0.1)

    # Fix cumulative totals on progress from store row after checkpoints.
    get_bf = getattr(store, "get_backfill", None)
    if callable(get_bf):
        try:
            latest = get_bf(backfill_id) or row
        except Exception:  # noqa: BLE001
            latest = row
    else:
        latest = row
    progress.cursor_block = int(latest.get("cursor_block") or cursor)
    progress.end_block = int(latest.get("end_block") or end_block)
    progress.discovered_total = int(latest.get("discovered") or 0)
    progress.funds_ge_floor_total = int(latest.get("funds_ge_floor") or 0)
    progress.fully_scanned_total = int(latest.get("fully_scanned") or 0)
    progress.heat_positive_total = int(latest.get("heat_positive") or 0)
    progress.blocks_remaining = max(0, progress.end_block - progress.cursor_block)
    progress.duration_s = round(time.monotonic() - started, 1)

    if progress.cursor_block >= progress.end_block:
        progress.status = "done"
        progress.message = "backfill complete"
    else:
        progress.status = "running"
        progress.message = "checkpoint saved — resume on next cron"
        # ETA from this job's throughput.
        covered = max(1, progress.blocks_covered_this_job)
        rate = covered / max(1.0, progress.duration_s)  # blocks/sec
        progress.eta_hours = round((progress.blocks_remaining / rate) / 3600.0, 2) if rate > 0 else None

    latest["status"] = progress.status
    upsert = getattr(store, "upsert_backfill", None)
    if callable(upsert):
        upsert({
            **latest,
            "status": progress.status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "stats": {
                "last_job": {
                    "blocks_covered": progress.blocks_covered_this_job,
                    "discovered": progress.discovered_this_job,
                    "funds_ge_floor": progress.funds_ge_floor_this_job,
                    "fully_scanned": progress.fully_scanned_this_job,
                    "heat_positive": progress.heat_positive_this_job,
                    "duration_s": progress.duration_s,
                    "eta_hours": progress.eta_hours,
                    "source": progress.source,
                },
                "heat_positive_samples": progress.heat_positive_samples,
            },
        })
    return progress


def _checkpoint(store: ScanStore, row: dict[str, Any], progress: BackfillProgress) -> None:
    """Update cumulative counters using deltas from this job's running totals."""
    flushed = getattr(progress, "_flushed", None)
    if flushed is None:
        flushed = {
            "discovered": 0,
            "deduped": 0,
            "ge": 0,
            "below": 0,
            "unknown": 0,
            "scanned": 0,
            "heat": 0,
        }
        setattr(progress, "_flushed", flushed)

    d_disc = progress.discovered_this_job - flushed["discovered"]
    d_dedupe = progress.deduped_this_job - flushed["deduped"]
    d_ge = progress.funds_ge_floor_this_job - flushed["ge"]
    d_below = progress.funds_below_floor_this_job - flushed["below"]
    d_unk = progress.funds_unknown_this_job - flushed["unknown"]
    d_scan = progress.fully_scanned_this_job - flushed["scanned"]
    d_heat = progress.heat_positive_this_job - flushed["heat"]

    row["cursor_block"] = progress.cursor_block
    row["discovered"] = int(row.get("discovered") or 0) + d_disc
    row["deduped"] = int(row.get("deduped") or 0) + d_dedupe
    row["funds_ge_floor"] = int(row.get("funds_ge_floor") or 0) + d_ge
    row["funds_below_floor"] = int(row.get("funds_below_floor") or 0) + d_below
    row["funds_unknown"] = int(row.get("funds_unknown") or 0) + d_unk
    row["fully_scanned"] = int(row.get("fully_scanned") or 0) + d_scan
    row["heat_positive"] = int(row.get("heat_positive") or 0) + d_heat
    row["source"] = progress.source
    row["status"] = "running"
    row["updated_at"] = datetime.now(timezone.utc).isoformat()

    flushed["discovered"] = progress.discovered_this_job
    flushed["deduped"] = progress.deduped_this_job
    flushed["ge"] = progress.funds_ge_floor_this_job
    flushed["below"] = progress.funds_below_floor_this_job
    flushed["unknown"] = progress.funds_unknown_this_job
    flushed["scanned"] = progress.fully_scanned_this_job
    flushed["heat"] = progress.heat_positive_this_job

    upsert = getattr(store, "upsert_backfill", None)
    if callable(upsert):
        upsert(row)


def _persist_progress(store: ScanStore, progress: BackfillProgress, row: dict[str, Any]) -> None:
    upsert = getattr(store, "upsert_backfill", None)
    if not callable(upsert):
        return
    upsert({
        **row,
        "status": progress.status,
        "cursor_block": progress.cursor_block,
        "end_block": progress.end_block,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def _run_full_parallel(
    addresses: list[str],
    *,
    settings: Settings,
    workers: int,
    deadline_monotonic: float,
) -> list[tuple[str, FunnelResult]]:
    if not addresses:
        return []
    out: list[tuple[str, FunnelResult]] = []

    def _one(addr: str) -> tuple[str, FunnelResult]:
        local = open_store(settings)
        fr = lane_a.run_one(addr, settings=settings, store=local)
        return addr, fr

    if workers == 1 or len(addresses) == 1:
        for addr in addresses:
            if time.monotonic() >= deadline_monotonic:
                break
            try:
                out.append(_one(addr))
            except Exception as exc:  # noqa: BLE001
                out.append((addr, FunnelResult(
                    bucket="manual-review", dropped=False, heat=0,
                    src_confidence="low", ir_confidence="low",
                    notes=["backfill full-scan error: %s" % str(exc)[:160]],
                )))
        return out

    with ThreadPoolExecutor(max_workers=min(workers, len(addresses))) as pool:
        futs = {pool.submit(_one, a): a for a in addresses}
        for fut in as_completed(futs):
            addr = futs[fut]
            try:
                out.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                out.append((addr, FunnelResult(
                    bucket="manual-review", dropped=False, heat=0,
                    src_confidence="low", ir_confidence="low",
                    notes=["backfill full-scan error: %s" % str(exc)[:160]],
                )))
            if time.monotonic() >= deadline_monotonic:
                break
    return out
