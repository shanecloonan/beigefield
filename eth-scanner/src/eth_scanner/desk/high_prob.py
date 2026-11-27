"""Scan the next high-probability contracts that are not already on the board.

The order is the master list's own ranking (drain probability, then tier,
then dollars) for rows at or above $5,000, then the DefiLlama tranche in
``data/high_prob_next.json``. Finished ``test_scan_runs`` rows are skipped.
The master list and the hand-ranked overlay are not rewritten, so the
monitor cursor stays where it is.

Phase 1 is a normal Lane A scan: fork verify and the full-path gate stay
off. Phase 2 runs fork verify and fuzz only for contracts whose new heat
is above 0, hottest first, then dollars. A provider stop or the CU cap
does not write a verdict for the contract that was in flight. Heat stays
the fresh evidence sum. Nothing here promotes a row to Yes.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from eth_scanner.desk.signal_rerun import (
    PER_CONTRACT_CU,
    _page,
    apply_evidence_heat,
    candidate_for_address,
    desk_verdict,
    explain_fork,
    fork_from_result,
    fuzz_from_result,
    persist_desk,
    provider_stopped,
    record_executed_stages,
    redact,
    result_row,
    safe_address,
)

MIN_FUNDS_USD = 5_000
DEFAULT_LIMIT = 300
DEFAULT_BUDGET_CU = 400_000
_TRANCHE = Path(__file__).resolve().parents[3] / "data" / "high_prob_next.json"
_PHASE_KEYS = (
    "ETH_SCANNER_FORK_VERIFY",
    "ETH_SCANNER_FORK_VERIFY_REDACT",
    "ETH_SCANNER_FUZZ_MIN_HEAT",
    "ETH_SCANNER_FULL_PATH",
)


def load_tranche(path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Ordered expansion rows. Missing file is an empty list."""
    target = path or _TRANCHE
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("candidates") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def finished_addresses(store: Any) -> tuple[set[str], str]:
    """Addresses that already have a desk row. An unreadable table is an error.

    A memory store has no remote query. Its ``test_runs`` list is the board.
    """
    rows, err = _page(store, "test_scan_runs", "address,status")
    found: set[str] = set()
    for row in rows:
        addr = safe_address(row.get("address"))
        if addr:
            found.add(addr)
    if err == "store has no remote query":
        memory = getattr(store, "test_runs", None)
        if isinstance(memory, list):
            for item in memory:
                if isinstance(item, dict):
                    addr = safe_address(item.get("address"))
                    if addr:
                        found.add(addr)
        return found, ""
    if err:
        return found, redact(err)[:240]
    return found, ""


def _funds(row: Any) -> float:
    if isinstance(row, dict):
        raw = row.get("est_usd_held", row.get("funds_usd", 0))
    else:
        raw = getattr(row, "est_usd_held", 0)
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def _text(row: Any, key: str) -> str:
    if isinstance(row, dict):
        return str(row.get(key) or "")
    return str(getattr(row, key, "") or "")


def _entry(row: Any, source: str) -> Optional[dict[str, Any]]:
    addr = safe_address(_text(row, "address"))
    funds = _funds(row)
    if not addr or funds < MIN_FUNDS_USD:
        return None
    try:
        prior = float(_text(row, "drain_probability") or 0)
    except ValueError:
        prior = 0.0
    return {
        "address": addr,
        "protocol": _text(row, "protocol")[:80],
        "category": _text(row, "category")[:60],
        "est_usd_held": round(funds, 2),
        "drain_probability": prior,
        "source": source,
    }


def select_high_prob(
    store: Any,
    *,
    limit: int = DEFAULT_LIMIT,
    tranche_path: Optional[Path] = None,
    master: Any = None,
) -> dict[str, Any]:
    """Up to ``limit`` unscanned contracts at or above $5,000, in prior order."""
    finished, err = finished_addresses(store)
    if err:
        return {
            "status": "error",
            "notes": ["could not read finished scans: %s" % err],
            "selected": [],
            "skipped_finished": 0,
            "from_master": 0,
            "from_tranche": 0,
        }
    if master is None:
        from eth_scanner.feed.master_list import load_master_candidates
        master = load_master_candidates()
    cap = max(0, int(limit))
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    skipped = 0
    from_master = 0
    from_tranche = 0

    def take(row: Any, source: str) -> bool:
        nonlocal skipped, from_master, from_tranche
        item = _entry(row, source)
        if item is None:
            return False
        addr = item["address"]
        if addr in seen:
            return False
        if addr in finished:
            skipped += 1
            seen.add(addr)
            return False
        seen.add(addr)
        selected.append(item)
        if source == "master-list":
            from_master += 1
        else:
            from_tranche += 1
        return len(selected) >= cap

    for row in master or []:
        if take(row, "master-list"):
            break
    if len(selected) < cap:
        for row in load_tranche(tranche_path):
            if take(row, "tranche"):
                break
    return {
        "status": "ok",
        "notes": [],
        "selected": selected,
        "skipped_finished": skipped,
        "from_master": from_master,
        "from_tranche": from_tranche,
    }


class _ScanPhase:
    """Normal scan leaves fork and full-path off. The heated pass turns both on."""

    def __init__(self, full_path: bool):
        self.full_path = full_path
        self.saved: dict[str, Optional[str]] = {}

    def __enter__(self) -> "_ScanPhase":
        self.saved = {key: os.environ.get(key) for key in _PHASE_KEYS}
        if self.full_path:
            os.environ["ETH_SCANNER_FORK_VERIFY"] = "1"
            os.environ["ETH_SCANNER_FORK_VERIFY_REDACT"] = "1"
            os.environ["ETH_SCANNER_FUZZ_MIN_HEAT"] = "0"
            os.environ["ETH_SCANNER_FULL_PATH"] = "1"
        else:
            for key in _PHASE_KEYS:
                os.environ.pop(key, None)
            os.environ["ETH_SCANNER_FUZZ_MIN_HEAT"] = "8"
        return self

    def __exit__(self, *_exc: Any) -> bool:
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return False


def _not_run_fork() -> dict[str, Any]:
    return {"status": "not-run", "drainable": False, "plain": explain_fork("not-run", False)}


def _not_run_fuzz() -> dict[str, Any]:
    return fuzz_from_result(type("Empty", (), {"heat_breakdown": {}})())


def _snapshot_new(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "chain": "ethereum",
        "address": row["address"],
        "name": row.get("protocol") or "",
        "peak": 0,
        "old_verdict": "no",
        "old_heat": 0,
        "funds_usd": row.get("est_usd_held") or 0,
        "source": row.get("source") or "",
        "category": row.get("category") or "",
        "reasons": ["high-prob"],
    }


def _counts(rows: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    heat: dict[str, int] = {}
    verdict: dict[str, int] = {}
    for row in rows:
        heat_key = str(int(row.get("new_heat") or 0))
        verdict_key = str(row.get("new_verdict") or "no")
        heat[heat_key] = heat.get(heat_key, 0) + 1
        verdict[verdict_key] = verdict.get(verdict_key, 0) + 1
    return heat, verdict


def _room(proxy: Any, budget_cu: int) -> bool:
    if proxy.stop_reason:
        return False
    return int(proxy.budget.spent) + PER_CONTRACT_CU <= int(budget_cu)


def run_high_prob_batch(
    store: Any,
    settings: Any,
    *,
    limit: int = DEFAULT_LIMIT,
    budget_cu: int = DEFAULT_BUDGET_CU,
    deadline_s: float = 300 * 60,
    lease_wait_s: float = 20 * 60,
    dry_run: bool = False,
    scan_one: Any = None,
    tranche_path: Optional[Path] = None,
    master: Any = None,
) -> dict[str, Any]:
    """Normal-scan up to ``limit`` new contracts, then fork/fuzz where heat > 0.

    The CU cap covers both phases. The under-$5k queues are not read.
    """
    chosen = select_high_prob(store, limit=limit, tranche_path=tranche_path, master=master)
    notes = [
        "normal scan first; fork and fuzz run only when the new heat is above 0",
        "ordered by heat descending, then funds, for the fork pass",
        "the under-$5k queues were not read",
        "heat stays the fresh evidence sum; a fork or fuzz result is not an automatic yes",
        "a provider stop or the CU cap leaves the in-flight contract without a verdict",
        "%d from the master list, %d from the new tranche, %d already scanned"
        % (chosen.get("from_master", 0), chosen.get("from_tranche", 0), chosen.get("skipped_finished", 0)),
    ]
    notes.extend(chosen.get("notes") or [])
    selected = list(chosen.get("selected") or [])
    plan: dict[str, Any] = {
        "mode": "high-prob",
        "status": chosen.get("status") or "ok",
        "limit": int(limit),
        "min_funds_usd": MIN_FUNDS_USD,
        "budget_cu": int(budget_cu),
        "selected": len(selected),
        "from_master": chosen.get("from_master", 0),
        "from_tranche": chosen.get("from_tranche", 0),
        "skipped_finished": chosen.get("skipped_finished", 0),
        "full_path_queued": 0,
        "full_path_ran": 0,
        "notes": notes,
        "rerun": [],
        "unfinished": [],
        "cu_used": 0,
        "cu_calls": 0,
        "stop_reason": "",
    }
    if chosen.get("status") == "error":
        plan["status"] = "error"
        return plan
    if dry_run or not selected:
        plan["status"] = "dry-run" if dry_run else "done"
        if dry_run:
            plan["selected_rows"] = [_snapshot_new(row) for row in selected]
        if not selected:
            plan["notes"].append("no unscanned contract at or above $5000")
        return plan

    from eth_scanner.feed.runner import acquire_scan_cycle, refresh_scan_cycle, release_scan_cycle
    from eth_scanner.ingest.rpc_client import RpcUnavailable

    upstream = str(getattr(settings, "eth_rpc_url", "") or "").strip()
    if not upstream:
        plan["status"] = "skipped"
        plan["notes"].append("ETH_RPC_URL unset")
        return plan

    try:
        owner = acquire_scan_cycle(store, wait_s=lease_wait_s, poll_s=15.0)
    except TimeoutError:
        plan["status"] = "blocked"
        plan["notes"].append("another scan cycle holds the cursor")
        return plan

    from eth_scanner.desk.signal_rerun import CuProxy, _HoldWrites, _lock_rpc

    proxy = CuProxy(upstream, int(budget_cu))
    local = proxy.start()
    settings.eth_rpc_url = local
    settings.range_min_usd = 0
    settings.range_max_usd = None
    _lock_rpc(local)
    if scan_one is None:
        from eth_scanner.lane_a.worker import run_one as scan_one

    guarded = _HoldWrites(store, proxy)
    started = time.monotonic()
    rerun: list[dict[str, Any]] = []
    unfinished: list[dict[str, Any]] = []
    stop = ""

    def _halt(reason: str) -> None:
        nonlocal stop
        stop = reason

    def _one(row: dict[str, Any], *, full_path: bool, peak: int) -> Optional[dict[str, Any]]:
        addr = row["address"]
        try:
            with _ScanPhase(full_path):
                result = scan_one(addr, settings=settings, store=guarded)
        except RpcUnavailable:
            _halt("rpc unavailable")
            return None
        except Exception as exc:  # noqa: BLE001 — one contract must not end the pass
            if provider_stopped(proxy.stop_reason) or proxy.stop_reason:
                _halt(proxy.stop_reason or "error")
                return None
            return {"error": redact(str(exc))[:200]}
        if proxy.stop_reason:
            _halt(proxy.stop_reason)
            return None
        parts = apply_evidence_heat(result, peak)
        cleared = record_executed_stages(result)
        try:
            store.save_result(addr, result)
        except Exception:  # noqa: BLE001 — the desk row is the one the site reads
            pass
        desk_error = persist_desk(
            store,
            result,
            addr,
            parts,
            peak,
            refresh_seen_at=True,
        )
        after = result_row(result)
        body = {
            "new_verdict": desk_verdict(after),
            "new_heat": parts["total"],
            "funds_usd": getattr(result, "funds_usd", None) if getattr(result, "funds_usd", None) is not None else row.get("funds_usd") or row.get("est_usd_held") or 0,
            "evidence": {key: parts[key] for key in parts if key != "total" and parts[key]},
            "fork": fork_from_result(result) if full_path else _not_run_fork(),
            "fuzz": fuzz_from_result(result) if full_path else _not_run_fuzz(),
            "stages_cleared": cleared,
            "pending_stages": [str(name) for name in ((result.heat_breakdown or {}).get("pending_stages") or [])],
            "score_state": str((result.heat_breakdown or {}).get("score_state") or ""),
            "full_path": full_path,
        }
        if desk_error:
            body["desk_error"] = desk_error
        return body

    try:
        for index, candidate in enumerate(selected):
            if not _room(proxy, budget_cu):
                _halt(proxy.stop_reason or "cu budget")
                unfinished.extend(_snapshot_new(row) for row in selected[index:])
                break
            if time.monotonic() - started > deadline_s:
                _halt("deadline")
                unfinished.extend(_snapshot_new(row) for row in selected[index:])
                break
            refresh_scan_cycle(store, owner, candidate["address"])
            before = _snapshot_new(candidate)
            outcome = _one(candidate, full_path=False, peak=0)
            if outcome is None:
                unfinished.extend(_snapshot_new(row) for row in selected[index:])
                break
            if "new_heat" not in outcome:
                unfinished.append({
                    "address": candidate["address"],
                    "name": candidate.get("protocol") or "",
                    "error": outcome.get("error") or "scan did not finish",
                })
                continue
            before.update(outcome)
            before["changed"] = before["new_verdict"] != before["old_verdict"] or before["new_heat"] != before["old_heat"]
            rerun.append(before)

        heated = [row for row in rerun if int(row.get("new_heat") or 0) > 0 and not row.get("error")]
        heated.sort(key=lambda row: (-int(row["new_heat"]), -float(row.get("funds_usd") or 0), row["address"]))
        plan["full_path_queued"] = len(heated)
        if stop:
            plan["full_path_skipped"] = len(heated)
        else:
            ran = 0
            for index, row in enumerate(heated):
                if not _room(proxy, budget_cu):
                    _halt(proxy.stop_reason or "cu budget")
                    plan["full_path_skipped"] = len(heated) - index
                    unfinished.extend({
                        "address": item["address"],
                        "name": item.get("name") or "",
                        "new_heat": item.get("new_heat"),
                        "phase": "full-path",
                    } for item in heated[index:])
                    break
                if time.monotonic() - started > deadline_s:
                    _halt("deadline")
                    plan["full_path_skipped"] = len(heated) - index
                    unfinished.extend({
                        "address": item["address"],
                        "name": item.get("name") or "",
                        "new_heat": item.get("new_heat"),
                        "phase": "full-path",
                    } for item in heated[index:])
                    break
                stored = candidate_for_address(store, row["address"])
                peak = max(int(stored.get("peak") or 0), int(row["new_heat"]))
                refresh_scan_cycle(store, owner, row["address"])
                outcome = _one(
                    {"address": row["address"], "funds_usd": row.get("funds_usd") or 0, "est_usd_held": row.get("funds_usd") or 0},
                    full_path=True,
                    peak=peak,
                )
                if outcome is None:
                    plan["full_path_skipped"] = len(heated) - index
                    unfinished.extend({
                        "address": item["address"],
                        "name": item.get("name") or "",
                        "new_heat": item.get("new_heat"),
                        "phase": "full-path",
                    } for item in heated[index:])
                    break
                if "new_heat" not in outcome:
                    row["full_path_error"] = outcome.get("error") or "full path did not finish"
                    continue
                row.update(outcome)
                row["changed"] = row["new_verdict"] != row["old_verdict"] or row["new_heat"] != row["old_heat"]
                ran += 1
            plan["full_path_ran"] = ran
        if not stop:
            stop = "done"
    finally:
        release_scan_cycle(store, owner, stop or "high-prob finished")
        proxy.stop()

    heat_counts, verdict_counts = _counts(rerun)
    drainable = [
        row["address"]
        for row in rerun
        if isinstance(row.get("fork"), dict) and row["fork"].get("drainable")
    ]
    plan.update({
        "status": stop or "done",
        "rerun": rerun,
        "rerun_count": len(rerun),
        "scanned": len(rerun),
        "unfinished": unfinished,
        "unfinished_count": len(unfinished),
        "heat_counts": heat_counts,
        "verdict_counts": verdict_counts,
        "drainable": drainable,
        "cu_used": proxy.budget.spent,
        "cu_calls": len(proxy.budget.calls),
        "stop_reason": proxy.stop_reason,
    })
    return plan
