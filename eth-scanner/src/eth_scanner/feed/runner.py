"""Iterate the curated master list with a resumable Supabase cursor.

Each address goes through the existing Lane A path: verified source / bytecode
via Etherscan, live funds re-check against the $2,000 floor, then the
unchanged funnel. Heat rules are not touched here.

Read-only chain I/O. Never sends a transaction.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from eth_scanner.config import Settings, load_settings
from eth_scanner.feed.master_list import MasterCandidate, load_master_candidates
from eth_scanner.ingest.funds import DEFAULT_MIN_FUNDS_USD
from eth_scanner.lane_a import worker as lane_a
from eth_scanner.store.supabase import ScanStore, normalize_address, open_store
from eth_scanner.types import FunnelResult, Target, to_plain

CURSOR_ID = "master-list"
DISCOVERY_SOURCE = "master_list"
# Keep the lease alive across a slow Lane A batch; cleared when the job exits.
LEASE_BUFFER_S = 900


@dataclass
class MasterListProgress:
    status: str = "running"  # running | done | noop | error
    list_size: int = 0
    cursor_start: int = 0
    cursor_next: int = 0
    processed: int = 0
    persisted: int = 0
    persist_failed: int = 0
    below_floor: int = 0
    heat_gt0: int = 0
    lane_b: int = 0
    errors: int = 0
    passes_completed: int = 0
    resumed: bool = False
    duration_s: float = 0.0
    message: str = ""
    last_error: str = ""
    source: str = DISCOVERY_SOURCE
    samples: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_master_list(
    *,
    settings: Optional[Settings] = None,
    store: Optional[ScanStore] = None,
    path: Optional[Path | str] = None,
    workers: int = 8,
    deadline_minutes: float = 40.0,
    deadline_monotonic: Optional[float] = None,
    min_funds_usd: Optional[float] = None,
    reset: bool = False,
    max_scans: int = 0,
    scan_one: Optional[Callable[[str], FunnelResult]] = None,
) -> MasterListProgress:
    """Scan master-list addresses in rank order until the deadline or the list ends.

    ``max_scans`` 0 means no per-run cap (the scheduled default). A cursor in
    ``eth_scan_backfill`` id ``master-list`` resumes the next run. After a full
    pass the cursor returns to 0 so the following run re-checks live balances.
    """
    settings = settings or load_settings()
    store = store or open_store(settings)
    if min_funds_usd is not None:
        settings.min_funds_usd = float(min_funds_usd)
    min_funds = float(getattr(settings, "min_funds_usd", DEFAULT_MIN_FUNDS_USD) or DEFAULT_MIN_FUNDS_USD)
    started = time.monotonic()
    deadline = (
        float(deadline_monotonic)
        if deadline_monotonic is not None
        else started + max(1.0, float(deadline_minutes) * 60.0)
    )
    progress = MasterListProgress()
    owner = _lease_owner()

    try:
        candidates = load_master_candidates(path)
    except Exception as exc:  # noqa: BLE001
        progress.status = "error"
        progress.last_error = "load master list: %s" % str(exc)[:240]
        progress.message = progress.last_error
        progress.duration_s = round(time.monotonic() - started, 1)
        return progress

    n = len(candidates)
    progress.list_size = n
    if n == 0:
        progress.status = "error"
        progress.message = "master list is empty"
        progress.duration_s = round(time.monotonic() - started, 1)
        return progress

    list_sha = _list_sha(candidates)
    row = _read_cursor(store)
    if not reset and _lease_blocks(row, owner):
        progress.status = "noop"
        progress.message = "another master-list run holds the cursor"
        progress.cursor_start = int((row or {}).get("cursor_block") or 0)
        progress.cursor_next = progress.cursor_start
        stats = _stats(row)
        progress.passes_completed = int(stats.get("passes_completed") or 0)
        progress.duration_s = round(time.monotonic() - started, 1)
        return progress

    cursor, passes = _cursor_index(row, n, list_sha, reset=reset)
    progress.cursor_start = cursor
    progress.cursor_next = cursor
    progress.resumed = cursor > 0 and not reset
    progress.passes_completed = passes
    if not _claim_lease(store, row, owner, cursor, n, list_sha, passes):
        progress.status = "noop"
        progress.message = "another master-list run claimed the cursor"
        progress.cursor_next = cursor
        progress.duration_s = round(time.monotonic() - started, 1)
        return progress

    workers = max(1, min(int(workers or 1), 16))
    # 0 = no cap. A positive test hook stops after N addresses this run.
    remaining_cap = int(max_scans) if int(max_scans or 0) > 0 else n
    scan = scan_one or (lambda addr: _default_scan(addr, settings))
    idx = cursor
    held_lease = True

    try:
        while idx < n and remaining_cap > 0:
            if idx > cursor and time.monotonic() >= deadline:
                break
            batch_n = min(workers, n - idx, remaining_cap)
            batch = candidates[idx:idx + batch_n]
            outcomes = _scan_batch(batch, scan=scan, workers=workers)
            for cand, result, err in outcomes:
                _record_outcome(
                    store,
                    cand,
                    result,
                    err,
                    progress,
                    min_funds=min_funds,
                )
            idx += len(batch)
            remaining_cap -= len(batch)
            finished_pass = idx >= n
            if finished_pass:
                passes += 1
                progress.passes_completed = passes
            progress.cursor_next = 0 if finished_pass else idx
            _checkpoint(
                store,
                owner=owner,
                cursor=progress.cursor_next,
                list_size=n,
                list_sha=list_sha,
                passes=passes,
                progress=progress,
                last=batch[-1] if batch else None,
            )
            if finished_pass or time.monotonic() >= deadline:
                break
        if progress.cursor_next == 0 and progress.processed and idx >= n:
            progress.status = "done"
            progress.message = "full master-list pass complete — next run starts at rank 1"
        elif progress.processed == 0 and progress.errors:
            progress.status = "error"
            progress.message = progress.last_error or "master-list batch failed"
        else:
            progress.status = "running"
            progress.message = "checkpoint saved — resume at index %d/%d" % (
                progress.cursor_next, n,
            )
        if progress.processed and progress.persisted == 0 and progress.persist_failed:
            progress.status = "error"
            progress.last_error = progress.last_error or "test_scan_runs persist failed"
            progress.message = progress.last_error
    except Exception as exc:  # noqa: BLE001
        progress.status = "error"
        progress.last_error = str(exc)[:240]
        progress.message = progress.last_error
    finally:
        if held_lease:
            _release_lease(store, owner, progress, list_size=n, list_sha=list_sha, passes=progress.passes_completed)
        progress.duration_s = round(time.monotonic() - started, 1)
    return progress


def _default_scan(address: str, settings: Settings) -> FunnelResult:
    """Existing Lane A worker: funds floor, Etherscan source, unchanged funnel."""
    local = open_store(settings)
    return lane_a.run_one(address, settings=settings, store=local)


def _scan_batch(
    batch: list[MasterCandidate],
    *,
    scan: Callable[[str], FunnelResult],
    workers: int,
) -> list[tuple[MasterCandidate, Optional[FunnelResult], Optional[str]]]:
    if not batch:
        return []

    def _one(cand: MasterCandidate) -> tuple[MasterCandidate, Optional[FunnelResult], Optional[str]]:
        try:
            return cand, scan(cand.address), None
        except Exception as exc:  # noqa: BLE001
            return cand, None, str(exc)[:240]

    if workers == 1 or len(batch) == 1:
        return [_one(c) for c in batch]

    out: list[tuple[MasterCandidate, Optional[FunnelResult], Optional[str]]] = []
    with ThreadPoolExecutor(max_workers=min(workers, len(batch))) as pool:
        futs = [pool.submit(_one, c) for c in batch]
        for fut in as_completed(futs):
            out.append(fut.result())
    # Preserve rank order in the persisted sequence.
    order = {c.address: i for i, c in enumerate(batch)}
    out.sort(key=lambda item: order.get(item[0].address, 0))
    return out


def _record_outcome(
    store: ScanStore,
    cand: MasterCandidate,
    result: Optional[FunnelResult],
    err: Optional[str],
    progress: MasterListProgress,
    *,
    min_funds: float,
) -> None:
    progress.processed += 1
    if err or result is None:
        progress.errors += 1
        progress.last_error = err or "empty scan result"
        result = FunnelResult(
            bucket="manual-review",
            dropped=False,
            drop_reason=None,
            heat=0,
            src_confidence="low",
            ir_confidence="low",
            notes=["master-list scan error: %s" % (err or "unknown")[:180]],
        )
        status = "error"
    else:
        status = "dropped" if result.dropped else "done"

    heat = int(getattr(result, "heat", 0) or 0)
    bucket = getattr(result, "bucket", None)
    funds = getattr(result, "funds_usd", None)
    if heat > 0:
        progress.heat_gt0 += 1
    if bucket == "lane-b-queue":
        progress.lane_b += 1
    if (
        result.dropped
        and funds is not None
        and float(funds) < min_funds
    ):
        progress.below_floor += 1
    if heat > 0 or bucket == "lane-b-queue":
        if len(progress.samples) < 30:
            progress.samples.append({
                "address": cand.address,
                "heat": heat,
                "bucket": bucket,
                "funds_usd": funds,
                "tier": cand.tier,
                "candidate_reason": cand.candidate_reason,
                "protocol": cand.protocol,
                "contract_class": getattr(result, "contract_class", None),
                "drop_reason": getattr(result, "drop_reason", None),
            })

    _stamp_target(store, cand, result, status=status)
    ok, fail = _persist_test_run(store, cand, result, status=status, error=err)
    if ok:
        progress.persisted += 1
    elif fail:
        progress.persist_failed += 1
        progress.last_error = fail


def _stamp_target(
    store: ScanStore,
    cand: MasterCandidate,
    result: FunnelResult,
    *,
    status: str,
) -> None:
    """Record discovery_source on the queue row without clobbering bytecode."""
    addr = cand.address
    target_status = "skipped" if status == "dropped" else ("error" if status == "error" else "done")
    fields = {
        "discovery_source": DISCOVERY_SOURCE,
        "status": target_status,
    }
    if result.funds_usd is not None:
        fields["funds_usd"] = result.funds_usd
        fields["tvl_usd"] = result.funds_usd
    if result.funds_status:
        fields["funds_status"] = result.funds_status
    if result.funds_checked_at:
        fields["funds_checked_at"] = result.funds_checked_at
    patch = getattr(store, "patch_target", None)
    existing = None
    try:
        existing = store.get_target(addr)
    except Exception:  # noqa: BLE001
        existing = None
    if existing and callable(patch):
        try:
            patch(addr, fields)
        except Exception:  # noqa: BLE001
            pass
        return
    if existing:
        return
    try:
        store.upsert_target(Target(
            address=addr,
            status=target_status,  # type: ignore[arg-type]
            has_code=True,
            discovery_source=DISCOVERY_SOURCE,
            funds_usd=result.funds_usd,
            funds_status=result.funds_status,
            funds_checked_at=result.funds_checked_at,
            tvl_usd=result.funds_usd,
        ))
    except Exception:  # noqa: BLE001
        return


def _persist_test_run(
    store: ScanStore,
    cand: MasterCandidate,
    result: FunnelResult,
    *,
    status: str,
    error: Optional[str],
) -> tuple[bool, str]:
    save = getattr(store, "save_test_scan_run", None)
    if not callable(save):
        return False, "store cannot write test_scan_runs"
    addr = normalize_address(cand.address)
    funds = result.funds_usd
    notes = list(result.notes or [])
    tag = "master-list tier=%s reason=%s" % (cand.tier, cand.candidate_reason or "—")
    if tag not in notes:
        notes.append(tag)
    row: dict[str, Any] = {
        "dedupe_key": "master-list:%s" % addr,
        "kind": "lane-a",
        "chain": "ethereum",
        "address": addr,
        "contract_name": result.contract_name or cand.protocol or None,
        "tvl_usd": funds,
        "money_at_risk_usd": funds,
        "funds_usd": funds,
        "funds_breakdown": list(result.funds_breakdown or []),
        "funds_status": result.funds_status,
        "funds_checked_at": result.funds_checked_at,
        "invariant_results": list(result.invariant_results or []),
        "heat_breakdown": dict(result.heat_breakdown or {}),
        "known_safe": bool(result.known_safe),
        "discovery_source": DISCOVERY_SOURCE,
        "candidate_reason": cand.candidate_reason or None,
        "tier": int(cand.tier),
        "bucket": result.bucket,
        "heat": int(result.heat or 0),
        "status": status,
        "dropped": bool(result.dropped),
        "drop_reason": result.drop_reason,
        "src_confidence": result.src_confidence,
        "ir_confidence": result.ir_confidence,
        "contract_class": result.contract_class or None,
        "scope": result.scope or None,
        "value_movers": list(result.value_movers or []),
        "stage_trace": to_plain(result.stage_trace),
        "hypotheses": to_plain(result.hypotheses),
        "pattern_leads": to_plain(result.pattern_leads),
        "notes": notes,
        "live_ingest": True,
        "persist_remote": True,
        "error": (error or None),
        "finished_at": _now(),
        "raw": {
            "feed": DISCOVERY_SOURCE,
            "candidate": cand.to_dict(),
            "bucket": result.bucket,
            "heat": int(result.heat or 0),
            "dropped": bool(result.dropped),
            "drop_reason": result.drop_reason,
            "funds_usd": funds,
            "error": error,
        },
    }
    try:
        save(row)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:240]


def _list_sha(candidates: list[MasterCandidate]) -> str:
    blob = "\n".join("%s|%s|%s" % (c.tier, c.address, c.rank) for c in candidates)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _lease_owner() -> str:
    run = (os.environ.get("GITHUB_RUN_ID") or "").strip()
    if run:
        return "gha:%s" % run
    return "local:%s:%s" % (os.uname().nodename if hasattr(os, "uname") else "host", os.getpid())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _stats(row: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not row:
        return {}
    stats = row.get("stats") or {}
    if isinstance(stats, str):
        try:
            stats = json.loads(stats)
        except json.JSONDecodeError:
            return {}
    return dict(stats) if isinstance(stats, dict) else {}


def _read_cursor(store: ScanStore) -> Optional[dict[str, Any]]:
    get_bf = getattr(store, "get_backfill", None)
    if not callable(get_bf):
        return None
    try:
        row = get_bf(CURSOR_ID)
    except Exception:  # noqa: BLE001
        return None
    return dict(row) if row else None


def _lease_blocks(row: Optional[dict[str, Any]], owner: str) -> bool:
    stats = _stats(row)
    holder = str(stats.get("lease_owner") or "")
    if not holder or holder == owner:
        return False
    until = _parse_time(stats.get("lease_until"))
    if until is None:
        return False
    return until > datetime.now(timezone.utc)


def _cursor_index(
    row: Optional[dict[str, Any]],
    n: int,
    list_sha: str,
    *,
    reset: bool,
) -> tuple[int, int]:
    if reset or not row:
        return 0, 0 if reset else int(_stats(row).get("passes_completed") or 0)
    stats = _stats(row)
    passes = int(stats.get("passes_completed") or 0)
    if stats.get("list_sha") and stats.get("list_sha") != list_sha:
        return 0, passes
    cur = int(row.get("cursor_block") or 0)
    if cur <= 0 or cur >= n:
        return 0, passes
    return cur, passes


def _base_row(
    *,
    cursor: int,
    list_size: int,
    list_sha: str,
    passes: int,
    owner: str,
    progress: Optional[MasterListProgress],
    last: Optional[MasterCandidate],
    lease: bool,
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "list_sha": list_sha,
        "list_size": list_size,
        "passes_completed": passes,
        "feed": DISCOVERY_SOURCE,
    }
    if lease:
        stats["lease_owner"] = owner
        stats["lease_until"] = (
            datetime.now(timezone.utc) + timedelta(seconds=LEASE_BUFFER_S)
        ).isoformat()
    else:
        stats["lease_owner"] = None
        stats["lease_until"] = None
    if last is not None:
        stats["last_address"] = last.address
        stats["last_tier"] = last.tier
        stats["last_reason"] = last.candidate_reason
    if progress is not None:
        stats["last_job"] = {
            "processed": progress.processed,
            "persisted": progress.persisted,
            "below_floor": progress.below_floor,
            "heat_gt0": progress.heat_gt0,
            "lane_b": progress.lane_b,
            "errors": progress.errors,
            "samples": progress.samples[:20],
        }
    return {
        "id": CURSOR_ID,
        "start_block": 0,
        "end_block": int(list_size),
        "cursor_block": int(cursor),
        "status": "running" if lease else "done",
        "source": DISCOVERY_SOURCE,
        "stats": stats,
        "last_error": (progress.last_error if progress else "") or None,
    }


def _write_cursor(store: ScanStore, body: dict[str, Any]) -> None:
    upsert = getattr(store, "upsert_backfill", None)
    if not callable(upsert):
        return
    upsert(body)


def _claim_lease(
    store: ScanStore,
    row: Optional[dict[str, Any]],
    owner: str,
    cursor: int,
    n: int,
    list_sha: str,
    passes: int,
) -> bool:
    body = _base_row(
        cursor=cursor, list_size=n, list_sha=list_sha, passes=passes,
        owner=owner, progress=None, last=None, lease=True,
    )
    if row:
        for key in (
            "discovered", "deduped", "funds_ge_floor", "funds_below_floor",
            "funds_unknown", "fully_scanned", "heat_positive",
        ):
            if row.get(key) is not None:
                body[key] = row.get(key)
    try:
        _write_cursor(store, body)
    except Exception:  # noqa: BLE001
        return True  # local / unmigrated store: still scan this process
    latest = _read_cursor(store)
    holder = str(_stats(latest).get("lease_owner") or "")
    if holder and holder != owner and _lease_blocks(latest, owner):
        return False
    return True


def _checkpoint(
    store: ScanStore,
    *,
    owner: str,
    cursor: int,
    list_size: int,
    list_sha: str,
    passes: int,
    progress: MasterListProgress,
    last: Optional[MasterCandidate],
) -> None:
    body = _base_row(
        cursor=cursor, list_size=list_size, list_sha=list_sha, passes=passes,
        owner=owner, progress=progress, last=last, lease=True,
    )
    # Job totals, not a running sum of checkpoints (those would double-count).
    body["fully_scanned"] = progress.processed
    body["heat_positive"] = progress.heat_gt0
    body["funds_below_floor"] = progress.below_floor
    body["status"] = "done" if cursor == 0 and progress.processed else "running"
    try:
        _write_cursor(store, body)
    except Exception as exc:  # noqa: BLE001
        progress.last_error = "cursor checkpoint: %s" % str(exc)[:180]


def _release_lease(
    store: ScanStore,
    owner: str,
    progress: MasterListProgress,
    *,
    list_size: int,
    list_sha: str,
    passes: int,
) -> None:
    latest = _read_cursor(store)
    holder = str(_stats(latest).get("lease_owner") or "")
    if holder and holder != owner:
        return
    body = _base_row(
        cursor=progress.cursor_next,
        list_size=list_size,
        list_sha=list_sha,
        passes=passes,
        owner=owner,
        progress=progress,
        last=None,
        lease=False,
    )
    body["status"] = progress.status if progress.status in {"done", "error", "running", "noop"} else "running"
    body["fully_scanned"] = progress.processed
    body["heat_positive"] = progress.heat_gt0
    body["funds_below_floor"] = progress.below_floor
    if progress.last_error:
        body["last_error"] = progress.last_error
    try:
        _write_cursor(store, body)
    except Exception:  # noqa: BLE001
        pass
