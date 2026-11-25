"""Iterate named master lists with a resumable Supabase cursor.

Each address goes through the existing Lane A path: verified source / bytecode
via Etherscan, a live funds re-check against that list's configured min/max,
then the unchanged funnel. Heat rules are not touched here.

``run_scan_cycle`` first drains pending ``fresh-deploy`` targets (brand-new
mainnet creates), then walks every list in ``lists.json`` order (List 1, then
List 2). A finished pass for the current fingerprint is not repeated. When
nothing on any list is unscanned, and random scanning is on, the same budget
picks verified contracts and runs them through Lane A plus the blend gauntlet.

Read-only chain I/O. Never sends a transaction.
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from eth_scanner.config import Settings, load_settings
from eth_scanner.feed.list_refresh import chain_of_reason
from eth_scanner.feed.lists import (
    LIST1_ID,
    bounds_for_list,
    cursor_id_for,
    dedupe_key_for,
    get_list_config,
    list_configs,
    load_named_list,
    random_phase_enabled,
    random_scan_config,
)
from eth_scanner.ingest.quota import DailyBudgetExhausted, bind_quota, release_quota
from eth_scanner.feed.master_list import MasterCandidate, list_fingerprint, load_master_candidates
from eth_scanner.lane_a import worker as lane_a
from eth_scanner.discover.fresh import FRESH_SOURCE
from eth_scanner.store.supabase import ScanStore, normalize_address, open_store, sweep_stale_claims
from eth_scanner.types import FunnelResult, Target, to_plain

CURSOR_ID = "master-list"
CYCLE_CURSOR_ID = "scan-cycle"
DISCOVERY_SOURCE = "master_list"
RANDOM_SOURCE = "random_scan"
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
    list_id: str = LIST1_ID
    list_name: str = "List 1"
    above_ceiling: int = 0
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
    max_funds_usd: Optional[float] = None,
    list_id: str = LIST1_ID,
    reset: bool = False,
    max_scans: int = 0,
    scan_one: Optional[Callable[[str], FunnelResult]] = None,
) -> MasterListProgress:
    """Scan one named list until the deadline.

    Bounds come from that list's config unless a caller passes an override.
    ``max_scans`` 0 means no per-run cap (the scheduled default). List 1 keeps
    the ``master-list`` cursor. After a full pass the cursor returns to 0.
    """
    settings = settings or load_settings()
    store = store or open_store(settings)
    spec = get_list_config(list_id)
    configured_min, configured_max = bounds_for_list(spec.id)
    min_funds = float(configured_min if min_funds_usd is None else min_funds_usd)
    max_funds = float(configured_max if max_funds_usd is None else max_funds_usd)
    # Range check only. settings.min_funds_usd stays the heat/engine floor.
    settings.range_min_usd = min_funds
    settings.range_max_usd = max_funds
    settings.scan_list_id = spec.id  # type: ignore[attr-defined]
    settings.scan_discovery_source = DISCOVERY_SOURCE  # type: ignore[attr-defined]
    cursor_id = cursor_id_for(spec.id)
    started = time.monotonic()
    deadline = (
        float(deadline_monotonic)
        if deadline_monotonic is not None
        else started + max(1.0, float(deadline_minutes) * 60.0)
    )
    progress = MasterListProgress(list_id=spec.id, list_name=spec.name)
    owner = _lease_owner()

    try:
        if path:
            candidates = load_master_candidates(path)
        else:
            candidates = load_named_list(spec.id).candidates
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

    list_sha = list_fingerprint(candidates)
    row = _read_cursor(store, cursor_id)
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
    if not _claim_lease(store, row, owner, cursor, n, list_sha, passes, cursor_id):
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

    budget_hit: Optional[DailyBudgetExhausted] = None
    try:
        bind_quota(store, settings)
        while idx < n and remaining_cap > 0 and budget_hit is None:
            if idx > cursor and time.monotonic() >= deadline:
                break
            batch_n = min(workers, n - idx, remaining_cap)
            batch = candidates[idx:idx + batch_n]
            local = [cand for cand in batch if chain_of_reason(cand.candidate_reason) == "ethereum"]
            # Other-chain rows stay on the list for their own pipeline. This
            # walker is Ethereum-only, so it advances past them without an
            # eth_call and without writing an Ethereum target.
            outcomes = _scan_batch(local, scan=scan, workers=workers) if local else []
            attempted: set[str] = {cand.address for cand in batch if cand not in local}
            for cand, result, err in outcomes:
                if isinstance(err, DailyBudgetExhausted):
                    budget_hit = err
                    continue
                attempted.add(cand.address)
                _record_outcome(
                    store,
                    cand,
                    result,
                    err,
                    progress,
                    min_funds=min_funds,
                    max_funds=max_funds,
                )
            # Only walk past a contiguous prefix. A later success must not skip
            # an address the daily cap stopped us from scanning.
            advance = 0
            for cand in batch:
                if cand.address not in attempted:
                    break
                advance += 1
            if advance <= 0:
                break
            idx += advance
            remaining_cap -= advance
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
                last=batch[advance - 1] if advance else None,
                cursor_id=cursor_id,
            )
            if finished_pass or time.monotonic() >= deadline or budget_hit is not None:
                break
        if budget_hit is not None:
            progress.status = "budget"
            progress.message = str(budget_hit)
        elif progress.cursor_next == 0 and progress.processed and idx >= n:
            progress.status = "done"
            progress.message = "full master-list pass complete"
        elif progress.processed == 0 and progress.errors:
            progress.status = "error"
            progress.message = progress.last_error or "master-list batch failed"
        else:
            progress.status = "running"
            progress.message = "checkpoint saved — resume at index %d/%d" % (
                progress.cursor_next, n,
            )
        if progress.status != "budget" and progress.processed and progress.persisted == 0 and progress.persist_failed:
            progress.status = "error"
            progress.last_error = progress.last_error or "test_scan_runs persist failed"
            progress.message = progress.last_error
    except DailyBudgetExhausted as exc:
        progress.status = "budget"
        progress.message = str(exc)
    except Exception as exc:  # noqa: BLE001
        progress.status = "error"
        progress.last_error = str(exc)[:240]
        progress.message = progress.last_error
    finally:
        release_quota()
        if held_lease:
            _release_lease(
                store, owner, progress,
                list_size=n, list_sha=list_sha, passes=progress.passes_completed,
                cursor_id=cursor_id,
            )
        progress.duration_s = round(time.monotonic() - started, 1)
    return progress


def _default_scan(address: str, settings: Settings) -> FunnelResult:
    """Lane A, then the full Blend gauntlet. Heat on the row stays Lane A's.

    The gauntlet runs every engine and every adaptation. Its own receipt heat
    moves only through the caller-profit gate and is stored beside the row,
    not added on top of Lane A.
    """
    local = open_store(settings)
    result = lane_a.run_one(address, settings=settings, store=local)
    if getattr(result, "dropped", False):
        _journal_intake(
            local,
            address,
            result,
            discovery_source=str(getattr(settings, "scan_discovery_source", None) or "blend"),
            list_id=getattr(settings, "scan_list_id", None),
            status="dropped",
        )
        return result
    summary = _run_gauntlet(address, result, settings, store=local)
    try:
        result.blend_summary = summary  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    note = str((summary or {}).get("note") or "")
    if note:
        notes = list(result.notes or [])
        if note not in notes:
            notes.append(note)
        try:
            result.notes = notes
        except Exception:  # noqa: BLE001
            pass
    return result


def _scan_batch(
    batch: list[MasterCandidate],
    *,
    scan: Callable[[str], FunnelResult],
    workers: int,
) -> list[tuple[MasterCandidate, Optional[FunnelResult], Any]]:
    if not batch:
        return []

    def _one(cand: MasterCandidate) -> tuple[MasterCandidate, Optional[FunnelResult], Any]:
        try:
            return cand, scan(cand.address), None
        except DailyBudgetExhausted as exc:
            return cand, None, exc
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
    max_funds: Optional[float] = None,
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

    if cand.evidence_note:
        notes = list(getattr(result, "notes", None) or [])
        if cand.evidence_note not in notes:
            notes.append(cand.evidence_note)
            try:
                result.notes = notes
            except Exception:  # noqa: BLE001
                pass
    heat = int(getattr(result, "heat", 0) or 0)
    bucket = getattr(result, "bucket", None)
    funds = getattr(result, "funds_usd", None)
    if heat > 0:
        progress.heat_gt0 += 1
    if bucket == "lane-b-queue":
        progress.lane_b += 1
    if result.dropped and funds is not None:
        if float(funds) < min_funds:
            progress.below_floor += 1
        elif max_funds is not None and float(funds) > max_funds:
            progress.above_ceiling += 1
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
    if status == "dropped":
        _journal_intake(
            store,
            cand.address,
            result,
            discovery_source=DISCOVERY_SOURCE,
            list_id=progress.list_id or None,
            status="dropped",
        )
    ok, fail = _persist_test_run(store, cand, result, progress, status=status, error=err)
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
    progress: MasterListProgress,
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
    list_id = progress.list_id or LIST1_ID
    list_name = progress.list_name or "List 1"
    tag = "%s tier=%s reason=%s" % (list_id, cand.tier, cand.candidate_reason or "—")
    if tag not in notes:
        notes.append(tag)
    if cand.evidence_note and cand.evidence_note not in notes:
        notes.append(cand.evidence_note)
    row: dict[str, Any] = {
        "dedupe_key": dedupe_key_for(list_id, addr),
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
        "list_id": list_id,
        "list_name": list_name,
        "candidate_reason": cand.candidate_reason or None,
        "evidence_note": cand.evidence_note or None,
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
            "list_id": list_id,
            "list_name": list_name,
            "candidate": cand.to_dict(),
            "bucket": result.bucket,
            "heat": int(result.heat or 0),
            "dropped": bool(result.dropped),
            "drop_reason": result.drop_reason,
            "funds_usd": funds,
            "error": error,
            "blend": getattr(result, "blend_summary", None),
        },
    }
    try:
        save(row)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:240]


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


def _read_cursor(store: ScanStore, cursor_id: str = CURSOR_ID) -> Optional[dict[str, Any]]:
    get_bf = getattr(store, "get_backfill", None)
    if not callable(get_bf):
        return None
    try:
        row = get_bf(cursor_id)
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
    # Missing or stale hash means the ranking changed. Start at the top.
    if stats.get("list_sha") != list_sha:
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
    cursor_id: str = CURSOR_ID,
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
        "id": cursor_id,
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
    cursor_id: str = CURSOR_ID,
) -> bool:
    body = _base_row(
        cursor=cursor, list_size=n, list_sha=list_sha, passes=passes,
        owner=owner, progress=None, last=None, lease=True, cursor_id=cursor_id,
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
    latest = _read_cursor(store, cursor_id)
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
    cursor_id: str = CURSOR_ID,
) -> None:
    body = _base_row(
        cursor=cursor, list_size=list_size, list_sha=list_sha, passes=passes,
        owner=owner, progress=progress, last=last, lease=True, cursor_id=cursor_id,
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
    cursor_id: str = CURSOR_ID,
) -> None:
    latest = _read_cursor(store, cursor_id)
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
        cursor_id=cursor_id,
    )
    body["status"] = progress.status if progress.status in {"done", "error", "running", "noop", "budget"} else "running"
    body["fully_scanned"] = progress.processed
    body["heat_positive"] = progress.heat_gt0
    body["funds_below_floor"] = progress.below_floor
    if progress.last_error:
        body["last_error"] = progress.last_error
    try:
        _write_cursor(store, body)
    except Exception:  # noqa: BLE001
        pass


def list_pass_complete(row: Optional[dict[str, Any]], n: int, list_sha: str) -> bool:
    """True when this fingerprint already has a finished pass and nothing is mid-list."""
    if not row or n <= 0:
        return False
    stats = _stats(row)
    if str(stats.get("list_sha") or "") != list_sha:
        return False
    try:
        passes = int(stats.get("passes_completed") or 0)
        cur = int(row.get("cursor_block") or 0)
    except (TypeError, ValueError):
        return False
    return passes >= 1 and (cur <= 0 or cur >= n)


@dataclass
class ScanCycleProgress:
    """One scheduler run: fresh deploys, then every configured list, then randoms."""

    status: str = "running"  # running | done | noop | error | budget
    phase: str = ""
    lists: list[dict[str, Any]] = field(default_factory=list)
    fresh_scanned: int = 0
    fresh_skipped: int = 0
    random_enabled: bool = False
    random_scanned: int = 0
    random_skipped: int = 0
    current_address: str = ""
    message: str = ""
    duration_s: float = 0.0
    quota: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_scan_cycle(
    *,
    settings: Optional[Settings] = None,
    store: Optional[ScanStore] = None,
    workers: int = 8,
    deadline_minutes: float = 40.0,
    deadline_monotonic: Optional[float] = None,
    reset: bool = False,
    scan_one: Optional[Callable[[str], FunnelResult]] = None,
    pick_random: Optional[Callable[[set[str]], Optional[str]]] = None,
    random_enabled: Optional[bool] = None,
) -> ScanCycleProgress:
    """Scan fresh deploys, then List 1, then List 2, then whatever else ``lists.json`` names.

    Pending ``eth_scan_targets`` with ``discovery_source='fresh-deploy'`` are
    claimed first so a brand-new contract is not stuck behind a list walk.
    After each list finishes the cycle checks that queue again. A list with a
    finished pass for its current fingerprint is skipped. A new or reordered
    address makes the fingerprint change, and that list is scanned again
    before any random contract. Random scanning follows
    ``random_scan.enabled`` (default on) unless ``ETH_SCANNER_RANDOM_SCAN`` is set.
    There is no per-run contract cap. The shared Etherscan ledger still applies.
    """
    settings = settings or load_settings()
    store = store or open_store(settings)
    stale = sweep_stale_claims(
        store,
        stale_seconds=getattr(settings, "claim_stale_seconds", None),
        max_resets=getattr(settings, "stale_claim_max_resets", None),
    )
    if stale:
        released = sum(1 for row in stale if row.get("action") == "released")
        skipped = sum(1 for row in stale if row.get("action") == "skipped")
        print(
            "stale-claim: released=%d skipped=%d (timeout=%ss max_resets=%s)"
            % (
                released,
                skipped,
                getattr(settings, "claim_stale_seconds", "?"),
                getattr(settings, "stale_claim_max_resets", "?"),
            ),
            file=sys.stderr,
        )
    started = time.monotonic()
    deadline = (
        float(deadline_monotonic)
        if deadline_monotonic is not None
        else started + max(1.0, float(deadline_minutes) * 60.0)
    )
    progress = ScanCycleProgress()
    owner = _lease_owner()
    if random_enabled is None:
        random_enabled = random_phase_enabled()
    progress.random_enabled = bool(random_enabled)

    if _cycle_blocked(store, owner):
        progress.status = "noop"
        progress.message = "another scan cycle holds the cursor"
        progress.duration_s = round(time.monotonic() - started, 1)
        return progress
    if not _claim_cycle(store, owner):
        progress.status = "noop"
        progress.message = "another scan cycle claimed the cursor"
        progress.duration_s = round(time.monotonic() - started, 1)
        return progress

    force_reset = {cfg.id for cfg in list_configs()} if reset else set()
    try:
        bind_quota(store, settings)
        # Seed the fast lane from the chain head before claiming those rows.
        # Skips cleanly when ETH_RPC_URL is unset. Custom scan_one hooks
        # (unit tests) and dry-run runs do not touch the network.
        if scan_one is None and not bool(getattr(settings, "dry_run", False)):
            try:
                from eth_scanner.discover.fresh import run_fresh_deploy_discovery

                disc = run_fresh_deploy_discovery(
                    store=store,
                    rpc_url=getattr(settings, "eth_rpc_url", "") or "",
                )
                print("fresh-deploys %s" % (disc.message or disc.status), file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                print("fresh-deploys discovery skipped: %s" % str(exc)[:200], file=sys.stderr)
        while time.monotonic() < deadline:
            _touch_cycle(store, owner, progress)
            progress.phase = "fresh-deploy"
            fresh_outcome = _scan_one_fresh(
                settings,
                store,
                progress,
                scan_one=scan_one,
            )
            if fresh_outcome == "ok":
                continue
            if fresh_outcome == "budget":
                progress.status = "budget"
                break
            if fresh_outcome == "stop":
                progress.status = "running"
                progress.message = progress.message or "fresh-deploy phase paused"
                break
            pending = _next_pending_list(store, force_reset=force_reset)
            if pending is not None:
                list_id, _sha, _n = pending
                progress.phase = list_id
                part = run_master_list(
                    settings=settings,
                    store=store,
                    workers=workers,
                    deadline_monotonic=deadline,
                    list_id=list_id,
                    reset=list_id in force_reset,
                    scan_one=scan_one,
                )
                force_reset.discard(list_id)
                progress.lists.append({
                    "list_id": part.list_id,
                    "list_name": part.list_name,
                    "status": part.status,
                    "list_size": part.list_size,
                    "processed": part.processed,
                    "persisted": part.persisted,
                    "cursor_start": part.cursor_start,
                    "cursor_next": part.cursor_next,
                    "passes_completed": part.passes_completed,
                    "message": part.message,
                })
                if part.list_size == 0:
                    continue
                if part.status == "budget":
                    progress.status = "budget"
                    progress.message = part.message
                    break
                if part.status in {"error", "noop"}:
                    progress.status = part.status
                    progress.message = part.message or part.last_error
                    break
                if part.status != "done":
                    progress.status = "running"
                    progress.message = part.message
                    break
                continue
            if not progress.random_enabled:
                progress.status = "done"
                progress.phase = "lists"
                progress.message = "every configured list is scanned; random phase is off"
                break
            progress.phase = "random"
            outcome = _scan_one_random(
                settings,
                store,
                progress,
                pick_random=pick_random,
                scan_one=scan_one,
            )
            if outcome == "budget":
                progress.status = "budget"
                break
            if outcome == "stop":
                progress.status = "running"
                progress.message = progress.message or "random phase paused"
                break
            if outcome == "none":
                progress.status = "running"
                progress.message = "lists are scanned; this draw found no new verified contract. The next scheduled run tries again on its own"
                break
        else:
            if progress.phase == "random":
                progress.status = "running"
                progress.message = (
                    "lists are scanned; random phase recorded %d this run. The next scheduled run continues on its own"
                    % progress.random_scanned
                )
            elif not progress.message:
                progress.status = "running"
                progress.message = "deadline reached"
        if progress.status == "running" and progress.phase == "random" and not progress.message:
            progress.message = "lists are scanned; random phase recorded %d this run. The next scheduled run continues on its own" % progress.random_scanned
    except DailyBudgetExhausted as exc:
        progress.status = "budget"
        progress.message = str(exc)
    finally:
        from eth_scanner.ingest.quota import active_ledger
        try:
            progress.quota = active_ledger().snapshot(len(getattr(settings, "etherscan_api_keys", []) or []))
        except Exception:  # noqa: BLE001
            progress.quota = {}
        release_quota()
        _release_cycle(store, owner, progress)
        progress.duration_s = round(time.monotonic() - started, 1)
    return progress


def cycle_cursor_id(chain: str = "ethereum") -> str:
    """Ethereum keeps the historical cursor id. Every other chain has its own."""
    from eth_scanner.chains.registry import normalize_chain

    name = normalize_chain(chain)
    if name == "ethereum":
        return CYCLE_CURSOR_ID
    return "%s:%s" % (CYCLE_CURSOR_ID, name)


def _cycle_blocked(store: ScanStore, owner: str, cursor_id: str = CYCLE_CURSOR_ID) -> bool:
    return _lease_blocks(_read_cursor(store, cursor_id), owner)


def _claim_cycle(store: ScanStore, owner: str, cursor_id: str = CYCLE_CURSOR_ID) -> bool:
    return _claim_lease(
        store, _read_cursor(store, cursor_id), owner,
        0, 0, "", 0, cursor_id,
    )


def _touch_cycle(
    store: ScanStore,
    owner: str,
    progress: ScanCycleProgress,
    cursor_id: str = CYCLE_CURSOR_ID,
) -> None:
    body = _base_row(
        cursor=progress.random_scanned,
        list_size=0,
        list_sha="",
        passes=0,
        owner=owner,
        progress=None,
        last=None,
        lease=True,
        cursor_id=cursor_id,
    )
    stats = body["stats"]
    stats["phase"] = progress.phase
    stats["fresh_scanned"] = progress.fresh_scanned
    stats["random_scanned"] = progress.random_scanned
    stats["current_address"] = progress.current_address
    stats["automatic"] = True
    try:
        _write_cursor(store, body)
    except Exception:  # noqa: BLE001
        return


def _release_cycle(
    store: ScanStore,
    owner: str,
    progress: ScanCycleProgress,
    cursor_id: str = CYCLE_CURSOR_ID,
) -> None:
    latest = _read_cursor(store, cursor_id)
    holder = str(_stats(latest).get("lease_owner") or "")
    if holder and holder != owner:
        return
    body = _base_row(
        cursor=progress.random_scanned,
        list_size=0,
        list_sha="",
        passes=0,
        owner=owner,
        progress=None,
        last=None,
        lease=False,
        cursor_id=cursor_id,
    )
    body["status"] = progress.status if progress.status in {"done", "error", "running", "noop", "budget"} else "running"
    if progress.message:
        body["last_error"] = progress.message[:240]
    stats = body["stats"]
    stats["phase"] = progress.phase
    stats["fresh_scanned"] = progress.fresh_scanned
    stats["random_scanned"] = progress.random_scanned
    stats["current_address"] = progress.current_address
    stats["automatic"] = True
    stats["lists"] = [
        {"list_id": row.get("list_id"), "status": row.get("status"), "processed": row.get("processed")}
        for row in progress.lists
    ]
    try:
        _write_cursor(store, body)
    except Exception:  # noqa: BLE001
        return


def acquire_scan_cycle(
    store: ScanStore,
    *,
    wait_s: float = 1200.0,
    poll_s: float = 20.0,
    chain: str = "ethereum",
) -> str:
    """Take one chain's scan-cycle lease, waiting out a holder on that chain.

    Ethereum uses the historical ``scan-cycle`` id, so the monitor and the
    signal rerun still exclude each other. Another chain never takes that id.
    Returns the owner id. Raises TimeoutError when the lease stays taken.
    """
    owner = _lease_owner()
    cursor_id = cycle_cursor_id(chain)
    deadline = time.monotonic() + max(0.0, float(wait_s))
    while True:
        if not _cycle_blocked(store, owner, cursor_id) and _claim_cycle(store, owner, cursor_id):
            return owner
        if time.monotonic() >= deadline:
            raise TimeoutError("another scan cycle holds the cursor")
        time.sleep(max(0.05, float(poll_s)))


def refresh_scan_cycle(
    store: ScanStore,
    owner: str,
    address: str = "",
    chain: str = "ethereum",
) -> None:
    """Extend the lease so a long rerun is not treated as abandoned."""
    progress = ScanCycleProgress()
    progress.phase = "signal-rerun"
    progress.status = "running"
    progress.current_address = address
    progress.message = "signal rerun"
    _touch_cycle(store, owner, progress, cycle_cursor_id(chain))


def release_scan_cycle(
    store: ScanStore,
    owner: str,
    message: str = "signal rerun finished",
    chain: str = "ethereum",
) -> None:
    progress = ScanCycleProgress()
    progress.phase = "signal-rerun"
    progress.status = "done"
    progress.message = message[:240]
    _release_cycle(store, owner, progress, cycle_cursor_id(chain))


def _next_pending_list(
    store: ScanStore,
    *,
    force_reset: set[str],
) -> Optional[tuple[str, str, int]]:
    """First configured list that still has unscanned rows, in file order."""
    for cfg in list_configs():
        try:
            named = load_named_list(cfg.id)
        except (OSError, ValueError, KeyError):
            continue
        n = len(named.candidates)
        if n <= 0:
            continue
        sha = list_fingerprint(named.candidates)
        if cfg.id in force_reset:
            return cfg.id, sha, n
        row = _read_cursor(store, cursor_id_for(cfg.id))
        if not list_pass_complete(row, n, sha):
            return cfg.id, sha, n
    return None


def random_funds_bounds(settings: Settings) -> tuple[float, Optional[float]]:
    """Funds-range sanity for a random or discovery contract.

    The intake floor is ``ETH_SCANNER_DISCOVERY_MIN_USD`` (default $100), then
    ``random_scan.min_funds_usd`` in lists.json, and does not use the Lane-B
    or List 1 floor. The upper bound stays whatever the random config sets,
    which is no ceiling when that field is absent. An explicit
    ``ETH_SCANNER_DISCOVERY_MAX_USD`` overrides only when the file has no max.
    """
    from eth_scanner.ingest.funds import discovery_min_usd

    try:
        cfg = random_scan_config()
    except (OSError, ValueError, json.JSONDecodeError):
        cfg = {}
    raw_min = cfg.get("min_funds_usd") if isinstance(cfg, dict) else None
    raw_max = cfg.get("max_funds_usd") if isinstance(cfg, dict) else None
    env_min = (os.environ.get("ETH_SCANNER_DISCOVERY_MIN_USD") or "").strip()
    if env_min:
        low = discovery_min_usd()
    elif raw_min is None:
        low = discovery_min_usd()
    else:
        low = float(raw_min)
    high = None if raw_max is None else float(raw_max)
    env_max = (os.environ.get("ETH_SCANNER_DISCOVERY_MAX_USD") or "").strip()
    if high is None and env_max:
        try:
            high = float(env_max)
        except ValueError:
            high = None
    return low, high


def _list_addresses() -> set[str]:
    seen: set[str] = set()
    for cfg in list_configs():
        try:
            named = load_named_list(cfg.id)
        except (OSError, ValueError, KeyError):
            continue
        for row in named.candidates:
            seen.add(row.address.lower())
    return seen


def _random_seen(store: ScanStore) -> set[str]:
    row = _read_cursor(store, "random-scan")
    stats = _stats(row)
    raw = stats.get("seen") or []
    if not isinstance(raw, list):
        return set()
    return {str(addr).lower() for addr in raw if str(addr).startswith("0x")}


def _remember_random(store: ScanStore, address: str) -> None:
    """Remember this random address only. List members stay in their own cursors."""
    row = _read_cursor(store, "random-scan")
    stats = _stats(row)
    ordered = [str(item).lower() for item in (stats.get("seen") or []) if str(item).startswith("0x")]
    addr = address.lower()
    if addr not in ordered:
        ordered.append(addr)
    ordered = ordered[-2000:]
    body = {
        "id": "random-scan",
        "start_block": 0,
        "end_block": 0,
        "cursor_block": len(ordered),
        "status": "running",
        "source": RANDOM_SOURCE,
        "stats": {"seen": ordered, "feed": RANDOM_SOURCE},
    }
    try:
        _write_cursor(store, body)
    except Exception:  # noqa: BLE001
        return


def _default_pick(settings: Settings, skip: set[str]) -> Optional[str]:
    keys = list(getattr(settings, "etherscan_api_keys", []) or [])
    if not keys:
        return None
    from eth_scanner.feed.random_feed import sample_verified_contract
    from eth_scanner.ingest.etherscan import EtherscanClient

    client = EtherscanClient(keys, min_interval_s=settings.etherscan_min_interval_s)
    return sample_verified_contract(client, skip=skip)


_ADAPTATIONS = (
    "syzkaller", "restler", "daikon", "lithium", "jepsen",
    "randoop", "learnlib", "stateright", "pict", "openspiel", "picire",
)


def _journal_intake(
    store: ScanStore,
    address: str,
    result: FunnelResult,
    *,
    discovery_source: str,
    list_id: Optional[str],
    status: str,
) -> None:
    """Persist an intake row, including contracts dropped before the gauntlet."""
    from eth_scanner.deep.blend.journal import BlendJournal, PersistError

    journal = BlendJournal.open(
        store,
        address=address,
        funds_usd=result.funds_usd,
        contract_name=result.contract_name or "",
        list_id=list_id,
        discovery_source=discovery_source,
    )
    try:
        journal.open_run(status=status, drop_reason=result.drop_reason)
        journal.stage("intake", {
            "address": address,
            "chain": "ethereum",
            "discovery_source": discovery_source,
            "funds_usd": result.funds_usd,
            "list_id": list_id,
            "contract_name": result.contract_name or "",
            "drop_reason": result.drop_reason,
            "bucket": result.bucket,
            "heat_contribution": 0,
            "label": "evidence only",
            "bug_classes": [result.contract_class] if result.contract_class else [],
            "findings": [],
        }, status="dropped" if status == "dropped" else "ok")
        if status == "dropped":
            journal.finish_drop(result.drop_reason or "dropped at intake")
    except PersistError:
        raise


def _run_gauntlet(
    address: str,
    result: FunnelResult,
    settings: Settings,
    store: Optional[ScanStore] = None,
) -> dict[str, Any]:
    """Engines plus every adaptation. Does not change result.heat."""
    from eth_scanner.deep.blend.journal import PersistError
    from eth_scanner.deep.blend.orchestrator import run_blend

    source = ""
    root = settings.work_dir / "sources" / address
    if root.is_dir():
        parts: list[str] = []
        for path in sorted(root.rglob("*.sol"))[:40]:
            try:
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        source = "\n\n".join(parts)
    try:
        report = run_blend(
            address=address,
            funds_usd=result.funds_usd,
            contract_name=result.contract_name or "",
            source=source,
            contracts=[result.contract_name] if result.contract_name else [],
            fork_url=settings.eth_rpc_url or "",
            list_id=getattr(settings, "scan_list_id", None),
            store=store if store is not None else open_store(settings),
            discovery_source=str(getattr(settings, "scan_discovery_source", None) or DISCOVERY_SOURCE),
        )
    except PersistError as exc:
        logger = __import__("logging").getLogger("eth_scanner.blend")
        logger.error("blend gauntlet persist failed for %s: %s", address, exc)
        return {
            "ok": False,
            "note": "blend persist failed: %s" % str(exc)[:160],
            "engines": [],
            "adaptations": {name: {"heat_contribution": 0} for name in _ADAPTATIONS},
            "heat": 0,
            "caller_profit_gate": False,
            "persist_error": str(exc)[:240],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "note": "blend gauntlet skipped: %s" % str(exc)[:160],
            "engines": [],
            "adaptations": {name: {"heat_contribution": 0} for name in _ADAPTATIONS},
            "heat": 0,
            "caller_profit_gate": False,
        }
    if not isinstance(report, dict):
        report = {}
    engines = []
    for row in report.get("engines") or []:
        if isinstance(row, dict):
            engines.append({
                "engine": row.get("engine") or row.get("id"),
                "status": row.get("status") or "skipped",
            })
    adaptations = report.get("adaptations") if isinstance(report.get("adaptations"), dict) else {}
    adapt_out = {}
    for name in _ADAPTATIONS:
        block = adaptations.get(name) if isinstance(adaptations.get(name), dict) else {}
        adapt_out[name] = {"heat_contribution": int(block.get("heat_contribution") or 0)}
    gate = bool((report.get("heat_breakdown") or {}).get("caller_profit_gate")) if isinstance(report.get("heat_breakdown"), dict) else False
    bits = ["%s=%s" % (row["engine"], row["status"]) for row in engines]
    adapt_bits = ",".join(_ADAPTATIONS)
    return {
        "ok": True,
        "bucket": report.get("bucket"),
        "heat": int(report.get("heat") or 0),
        "caller_profit_gate": gate,
        "engines": engines,
        "adaptations": adapt_out,
        "note": "blend gauntlet: %s; adaptations: %s" % (", ".join(bits) if bits else "no engines", adapt_bits),
    }


def _blend_note(address: str, result: FunnelResult, settings: Settings) -> str:
    """Compatibility wrapper. The gauntlet heat is not copied onto the scan row."""
    summary = _run_gauntlet(address, result, settings)
    try:
        result.blend_summary = summary  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    return str(summary.get("note") or "")


def _persist_random(
    store: ScanStore,
    address: str,
    result: FunnelResult,
    *,
    note: str,
) -> None:
    from eth_scanner.store.supabase import normalize_address as norm

    addr = norm(address)
    cand = MasterCandidate(
        address=addr,
        protocol=result.contract_name or "random",
        slug="random",
        category="random",
        est_usd_held=float(result.funds_usd or 0.0),
        candidate_reason="random-verified",
        tier=99,
        rank=10**9,
        source=RANDOM_SOURCE,
        contract_class=result.contract_class or "",
    )
    progress = MasterListProgress(list_id="", list_name="")
    # Tag the row so /test and /blend do not count it as List 1 or List 2.
    save = getattr(store, "save_test_scan_run", None)
    if not callable(save):
        return
    notes = list(result.notes or [])
    if note and note not in notes:
        notes.append(note)
    row: dict[str, Any] = {
        "dedupe_key": "random:%s" % addr,
        "kind": "lane-a",
        "chain": "ethereum",
        "address": addr,
        "contract_name": result.contract_name,
        "tvl_usd": result.funds_usd,
        "money_at_risk_usd": result.funds_usd,
        "funds_usd": result.funds_usd,
        "funds_breakdown": list(result.funds_breakdown or []),
        "funds_status": result.funds_status,
        "funds_checked_at": result.funds_checked_at,
        "invariant_results": list(result.invariant_results or []),
        "heat_breakdown": dict(result.heat_breakdown or {}),
        "known_safe": bool(result.known_safe),
        "discovery_source": RANDOM_SOURCE,
        "list_id": None,
        "list_name": None,
        "candidate_reason": "random-verified",
        "tier": 99,
        "bucket": result.bucket,
        "heat": int(result.heat or 0),
        "status": "dropped" if result.dropped else "done",
        "dropped": bool(result.dropped),
        "drop_reason": result.drop_reason,
        "src_confidence": result.src_confidence,
        "ir_confidence": result.ir_confidence,
        "contract_class": result.contract_class or None,
        "notes": notes,
        "live_ingest": True,
        "persist_remote": True,
        "finished_at": _now(),
        "raw": {
            "feed": RANDOM_SOURCE,
            "candidate": cand.to_dict(),
            "heat": int(result.heat or 0),
            "dropped": bool(result.dropped),
            "drop_reason": result.drop_reason,
            "funds_usd": result.funds_usd,
            "blend_note": note,
            "blend": getattr(result, "blend_summary", None),
        },
    }
    try:
        save(row)
    except Exception:  # noqa: BLE001
        return


def _scan_one_random(
    settings: Settings,
    store: ScanStore,
    progress: ScanCycleProgress,
    *,
    pick_random: Optional[Callable[[set[str]], Optional[str]]],
    scan_one: Optional[Callable[[str], FunnelResult]],
) -> str:
    """Return ok | none | stop | budget."""
    skip = _list_addresses() | _random_seen(store)
    try:
        if pick_random is not None:
            addr = pick_random(skip)
        else:
            addr = _default_pick(settings, skip)
    except DailyBudgetExhausted as exc:
        progress.message = str(exc)
        return "budget"
    if not addr:
        return "none"
    addr = str(addr).strip().lower()
    progress.current_address = addr
    _touch_cycle(store, _lease_owner(), progress)
    low, high = random_funds_bounds(settings)
    prev_min, prev_max = settings.range_min_usd, settings.range_max_usd
    prev_source = getattr(settings, "scan_discovery_source", None)
    prev_list = getattr(settings, "scan_list_id", None)
    settings.range_min_usd = low
    settings.range_max_usd = high
    settings.scan_discovery_source = RANDOM_SOURCE  # type: ignore[attr-defined]
    settings.scan_list_id = None  # type: ignore[attr-defined]
    scan = scan_one or (lambda a: _default_scan(a, settings))
    try:
        try:
            result = scan(addr)
        except DailyBudgetExhausted as exc:
            progress.message = str(exc)
            return "budget"
    finally:
        settings.range_min_usd = prev_min
        settings.range_max_usd = prev_max
        settings.scan_discovery_source = prev_source  # type: ignore[attr-defined]
        settings.scan_list_id = prev_list  # type: ignore[attr-defined]
    if result is None:
        return "stop"
    note = str(getattr(result, "blend_summary", {}).get("note") or "") if isinstance(getattr(result, "blend_summary", None), dict) else ""
    # A custom scan_one does not run the gauntlet. The default path already did.
    if scan_one is not None and not result.dropped:
        try:
            note = _blend_note(addr, result, settings)
        except Exception as exc:  # noqa: BLE001 — gauntlet skip must not sink the scan
            note = "blend gauntlet skipped: %s" % str(exc)[:160]
        if note:
            notes = list(result.notes or [])
            if note not in notes:
                notes.append(note)
            try:
                result.notes = notes
            except Exception:  # noqa: BLE001
                pass
    elif result.dropped:
        progress.random_skipped += 1
    _persist_random(store, addr, result, note=note)
    _remember_random(store, addr)
    progress.random_scanned += 1
    progress.message = "lists are scanned; random phase recorded %d this run. The next scheduled run continues on its own" % progress.random_scanned
    return "ok"


def _claim_fresh_pending(store: ScanStore, worker_id: str) -> Optional[dict[str, Any]]:
    fn = getattr(store, "claim_pending", None)
    if not callable(fn):
        return None
    try:
        rows = fn(1, worker_id, discovery_source=FRESH_SOURCE)
    except TypeError:
        rows = fn(1, worker_id)
        rows = [r for r in (rows or []) if str(r.get("discovery_source") or "") == FRESH_SOURCE]
    if not rows:
        return None
    return rows[0]


def _persist_fresh(
    store: ScanStore,
    address: str,
    result: FunnelResult,
    *,
    note: str,
    deployed_block: Optional[int] = None,
) -> None:
    from eth_scanner.store.supabase import normalize_address as norm

    addr = norm(address)
    save = getattr(store, "save_test_scan_run", None)
    notes = list(result.notes or [])
    if note and note not in notes:
        notes.append(note)
    status = "dropped" if result.dropped else "done"
    if callable(save):
        row: dict[str, Any] = {
            "dedupe_key": "fresh-deploy:%s" % addr,
            "kind": "lane-a",
            "chain": "ethereum",
            "address": addr,
            "contract_name": result.contract_name,
            "tvl_usd": result.funds_usd,
            "money_at_risk_usd": result.funds_usd,
            "funds_usd": result.funds_usd,
            "funds_breakdown": list(result.funds_breakdown or []),
            "funds_status": result.funds_status,
            "funds_checked_at": result.funds_checked_at,
            "invariant_results": list(result.invariant_results or []),
            "heat_breakdown": dict(result.heat_breakdown or {}),
            "known_safe": bool(result.known_safe),
            "discovery_source": FRESH_SOURCE,
            "list_id": None,
            "list_name": None,
            "candidate_reason": "fresh-deploy",
            "tier": 1,
            "bucket": result.bucket,
            "heat": int(result.heat or 0),
            "status": status,
            "dropped": bool(result.dropped),
            "drop_reason": result.drop_reason,
            "src_confidence": result.src_confidence,
            "ir_confidence": result.ir_confidence,
            "contract_class": result.contract_class or None,
            "notes": notes,
            "live_ingest": True,
            "persist_remote": True,
            "finished_at": _now(),
            "raw": {
                "feed": FRESH_SOURCE,
                "deployed_block": deployed_block,
                "heat": int(result.heat or 0),
                "dropped": bool(result.dropped),
                "drop_reason": result.drop_reason,
                "funds_usd": result.funds_usd,
                "blend_note": note,
                "blend": getattr(result, "blend_summary", None),
            },
        }
        try:
            save(row)
        except Exception:  # noqa: BLE001
            pass
    # Close the claim so the next cycle does not pick it up again.
    try:
        existing = store.get_target(addr) or {}
        store.upsert_target(Target(
            address=addr,
            status="skipped" if result.dropped else "done",
            funds_usd=result.funds_usd if result.funds_usd is not None else existing.get("funds_usd"),
            funds_breakdown=list(result.funds_breakdown or existing.get("funds_breakdown") or []),
            funds_status=result.funds_status or existing.get("funds_status"),
            funds_checked_at=result.funds_checked_at or existing.get("funds_checked_at"),
            tvl_usd=result.funds_usd if result.funds_usd is not None else existing.get("tvl_usd"),
            deployed_block=existing.get("deployed_block") or deployed_block,
            deployed_at=existing.get("deployed_at"),
            discovery_source=FRESH_SOURCE,
        ))
    except Exception:  # noqa: BLE001
        return


def _scan_one_fresh(
    settings: Settings,
    store: ScanStore,
    progress: ScanCycleProgress,
    *,
    scan_one: Optional[Callable[[str], FunnelResult]],
) -> str:
    """Claim and scan one pending fresh-deploy. Return ok | none | stop | budget."""
    from eth_scanner.ingest.funds import discovery_min_usd

    worker_id = str(getattr(settings, "worker_id", None) or _lease_owner())
    try:
        row = _claim_fresh_pending(store, worker_id)
    except DailyBudgetExhausted as exc:
        progress.message = str(exc)
        return "budget"
    if not row:
        return "none"
    addr = normalize_address(str(row.get("address") or ""))
    if not addr:
        return "none"
    progress.current_address = addr
    _touch_cycle(store, _lease_owner(), progress)
    low = discovery_min_usd()
    prev_min, prev_max = settings.range_min_usd, settings.range_max_usd
    prev_source = getattr(settings, "scan_discovery_source", None)
    prev_list = getattr(settings, "scan_list_id", None)
    settings.range_min_usd = low
    settings.range_max_usd = None
    settings.scan_discovery_source = FRESH_SOURCE  # type: ignore[attr-defined]
    settings.scan_list_id = None  # type: ignore[attr-defined]
    scan = scan_one or (lambda a: _default_scan(a, settings))
    try:
        try:
            result = scan(addr)
        except DailyBudgetExhausted as exc:
            progress.message = str(exc)
            return "budget"
    finally:
        settings.range_min_usd = prev_min
        settings.range_max_usd = prev_max
        settings.scan_discovery_source = prev_source  # type: ignore[attr-defined]
        settings.scan_list_id = prev_list  # type: ignore[attr-defined]
    if result is None:
        return "stop"
    note = str(getattr(result, "blend_summary", {}).get("note") or "") if isinstance(getattr(result, "blend_summary", None), dict) else ""
    if scan_one is not None and not result.dropped:
        try:
            note = _blend_note(addr, result, settings)
        except Exception as exc:  # noqa: BLE001 — gauntlet skip must not sink the scan
            note = "blend gauntlet skipped: %s" % str(exc)[:160]
        if note:
            notes = list(result.notes or [])
            if note not in notes:
                notes.append(note)
            try:
                result.notes = notes
            except Exception:  # noqa: BLE001
                pass
    elif result.dropped:
        progress.fresh_skipped += 1
    deployed_block = row.get("deployed_block")
    try:
        deployed_block = int(deployed_block) if deployed_block is not None else None
    except (TypeError, ValueError):
        deployed_block = None
    _persist_fresh(store, addr, result, note=note, deployed_block=deployed_block)
    progress.fresh_scanned += 1
    progress.message = "fresh-deploy phase recorded %d this run" % progress.fresh_scanned
    return "ok"
