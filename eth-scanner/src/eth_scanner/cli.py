"""CLI: lane-a, lane-b, enqueue, surface, list, receipt, research.

Defensive analysis only. No exploit / PoC / live fund-moving commands.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from eth_scanner.config import Settings, load_settings
from eth_scanner.heuristics.invariant_pass import main as surface_main
from eth_scanner.lane_a import worker as lane_a
from eth_scanner.lane_b import worker as lane_b
from eth_scanner.receipt import default_receipt_dir, pick_source_artifact, write_run_receipt
from eth_scanner.store.supabase import normalize_address, open_store
from eth_scanner.types import FunnelResult, to_plain


def _stage_exec_skip(et: dict[str, Any], *, executed_key: str, skipped_key: str, ran_key: str, status_key: str) -> tuple[bool, bool]:
    """Prefer explicit executed/skipped flags; fall back to ran + status."""
    if executed_key in et or skipped_key in et:
        executed = bool(et.get(executed_key))
        skipped = bool(et.get(skipped_key)) if skipped_key in et else (not executed)
        return executed, skipped
    status = str(et.get(status_key) or "")
    ran = bool(et.get(ran_key))
    executed = ran and status not in {"skipped", "compile-skip", ""}
    return executed, (not executed)


def _aggregate_engine_stats(scan_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up Slither/Mythril/fuzz/halmos/oracle/admin/storage with executed vs skipped."""
    slither_run = 0
    slither_executed = 0
    slither_skipped = 0
    mythril_run = 0
    mythril_executed = 0
    mythril_skipped = 0
    fuzzed = 0
    fuzz_executed = 0
    fuzz_skipped = 0
    fuzz_properties = 0
    fuzz_failures = 0
    halmos_run = 0
    halmos_executed = 0
    halmos_skipped = 0
    halmos_properties = 0
    halmos_properties_executed = 0
    halmos_properties_skipped = 0
    gen_halmos_failures = 0
    oracle_run = 0
    oracle_executed = 0
    oracle_skipped = 0
    oracle_confirmed = 0
    admin_run = 0
    admin_executed = 0
    admin_skipped = 0
    admin_confirmed = 0
    storage_run = 0
    storage_executed = 0
    storage_skipped = 0
    storage_confirmed = 0
    clone_executed = 0
    clone_skipped = 0
    clone_leads = 0
    leads = 0
    confirmed = 0
    heat_gt0 = 0
    timing_rows: list[dict[str, Any]] = []
    for row in scan_results:
        if int(row.get("heat") or 0) > 0:
            heat_gt0 += 1
        hb = dict(row.get("heat_breakdown") or {})
        et = dict(row.get("engine_timing") or hb.get("engine_timing") or {})
        fuzz = dict(hb.get("fuzz") or et.get("fuzz") or {})
        symbolic = dict(hb.get("symbolic") or {})
        status_sl = str(et.get("slither_status") or "")
        status_my = str(et.get("mythril_status") or "")

        sl_ex, _sl_sk = _stage_exec_skip(
            et, executed_key="slither_executed", skipped_key="slither_skipped",
            ran_key="ran_slither", status_key="slither_status",
        )
        if et.get("ran_slither") or status_sl in {"ok", "error", "compile-skip"} or sl_ex:
            slither_run += 1
        if sl_ex:
            slither_executed += 1
        elif et or status_sl:
            slither_skipped += 1

        my_ex, _my_sk = _stage_exec_skip(
            et, executed_key="mythril_executed", skipped_key="mythril_skipped",
            ran_key="ran_mythril", status_key="mythril_status",
        )
        if et.get("ran_mythril") or status_my in {"ok", "error", "compile-skip"} or my_ex:
            mythril_run += 1
        if my_ex:
            mythril_executed += 1
        elif et.get("ran_mythril") is not None or status_my or "mythril_skipped" in et:
            mythril_skipped += 1

        fuzz_ex, _fuzz_sk = _stage_exec_skip(
            et, executed_key="fuzz_executed", skipped_key="fuzz_skipped",
            ran_key="ran_fuzz", status_key="fuzz_status",
        )
        if et.get("ran_fuzz") or fuzz.get("ran") or fuzz_ex:
            fuzzed += 1
        if fuzz_ex:
            fuzz_executed += 1
        elif et.get("ran_fuzz") is not None or et.get("fuzz_status") or fuzz:
            fuzz_skipped += 1
        fuzz_properties += int(et.get("fuzz_properties") or fuzz.get("properties_checked") or 0)
        fuzz_failures += int(et.get("fuzz_failures") or fuzz.get("failure_count") or len(fuzz.get("failures") or []))

        hal_ex, _hal_sk = _stage_exec_skip(
            et, executed_key="halmos_executed", skipped_key="halmos_skipped",
            ran_key="ran_halmos", status_key="halmos_status",
        )
        # Prefer explicit executed flag / symbolic.executed over ran_halmos alone
        # (ran_halmos used to be true even on false compile-skip).
        if "halmos_executed" in et:
            hal_ex = bool(et.get("halmos_executed"))
            hal_sk = bool(et.get("halmos_skipped")) if "halmos_skipped" in et else (not hal_ex)
        elif symbolic.get("executed") is not None:
            hal_ex = bool(symbolic.get("executed"))
            hal_sk = not hal_ex
        if et.get("ran_halmos") or symbolic.get("ran") or hal_ex:
            halmos_run += 1
        if hal_ex:
            halmos_executed += 1
        elif et.get("ran_halmos") is not None or et.get("halmos_status") or symbolic:
            halmos_skipped += 1
        halmos_properties += int(et.get("halmos_properties") or symbolic.get("properties_checked") or 0)
        halmos_properties_executed += int(
            et.get("halmos_properties_executed") or symbolic.get("properties_executed") or 0
        )
        halmos_properties_skipped += int(
            et.get("halmos_properties_skipped") or symbolic.get("properties_skipped") or 0
        )
        gen_halmos_failures += int(
            et.get("halmos_failures") or symbolic.get("failure_count") or len(symbolic.get("failures") or [])
        )

        or_ex, _or_sk = _stage_exec_skip(
            et, executed_key="oracle_executed", skipped_key="oracle_skipped",
            ran_key="ran_oracle", status_key="oracle_status",
        )
        if et.get("ran_oracle") or or_ex:
            oracle_run += 1
        if or_ex:
            oracle_executed += 1
        elif "oracle_executed" in et or "ran_oracle" in et:
            oracle_skipped += 1
        oracle_confirmed += int(et.get("oracle_confirmed") or 0)

        ad_ex, _ad_sk = _stage_exec_skip(
            et, executed_key="admin_executed", skipped_key="admin_skipped",
            ran_key="ran_admin", status_key="admin_status",
        )
        if et.get("ran_admin") or ad_ex:
            admin_run += 1
        if ad_ex:
            admin_executed += 1
        elif "admin_executed" in et or "ran_admin" in et:
            admin_skipped += 1
        admin_confirmed += int(et.get("admin_confirmed") or 0)

        st_ex, _st_sk = _stage_exec_skip(
            et, executed_key="storage_executed", skipped_key="storage_skipped",
            ran_key="ran_storage", status_key="storage_status",
        )
        if et.get("ran_storage") or st_ex:
            storage_run += 1
        if st_ex:
            storage_executed += 1
        elif "storage_executed" in et or "ran_storage" in et:
            storage_skipped += 1
        storage_confirmed += int(et.get("storage_confirmed") or 0)

        if "clone_executed" in et:
            if et.get("clone_executed"):
                clone_executed += 1
            else:
                clone_skipped += 1
        elif et:
            # Clone fingerprint always runs when engines gate passes.
            clone_executed += 1
        clone_leads += int(et.get("clone_leads") or 0)

        n_leads = len(row.get("engine_leads") or [])
        if not n_leads:
            n_leads = int(hb.get("engine_leads") or et.get("leads") or 0)
        leads += n_leads
        findings = list(row.get("confirmed_findings") or [])
        if findings:
            n_conf = sum(1 for c in findings if c.get("confirmed"))
        else:
            n_conf = int(hb.get("engine_confirmed") or et.get("confirmed") or 0)
        confirmed += n_conf
        if et or n_leads or n_conf or fuzz:
            timing_rows.append({
                "address": row.get("address"),
                "slither_ms": et.get("slither_ms"),
                "mythril_ms": et.get("mythril_ms"),
                "fuzz_ms": et.get("fuzz_ms"),
                "halmos_ms": et.get("halmos_ms"),
                "oracle_ms": et.get("oracle_ms"),
                "admin_ms": et.get("admin_ms"),
                "storage_ms": et.get("storage_ms"),
                "total_ms": et.get("total_ms"),
                "slither_status": status_sl or None,
                "mythril_status": status_my or None,
                "fuzz_status": et.get("fuzz_status") or fuzz.get("status"),
                "fuzz_tool": et.get("fuzz_tool") or fuzz.get("tool"),
                "halmos_status": et.get("halmos_status") or symbolic.get("status"),
                "halmos_executed": hal_ex,
                "slither_executed": sl_ex,
                "mythril_executed": my_ex,
                "fuzz_executed": fuzz_ex,
                "leads": n_leads,
                "confirmed": n_conf,
                "funds_usd": row.get("funds_usd"),
                "heat": row.get("heat"),
                "contract_class": row.get("contract_class"),
            })
    return {
        "slither_run": slither_run,
        "slither_executed": slither_executed,
        "slither_skipped": slither_skipped,
        "mythril_run": mythril_run,
        "mythril_executed": mythril_executed,
        "mythril_skipped": mythril_skipped,
        "fuzzed": fuzzed,
        "fuzz_executed": fuzz_executed,
        "fuzz_skipped": fuzz_skipped,
        "fuzz_properties": fuzz_properties,
        "fuzz_failures": fuzz_failures,
        "halmos_run": halmos_run,
        "halmos_executed": halmos_executed,
        "halmos_skipped": halmos_skipped,
        "halmos_properties": halmos_properties,
        "halmos_properties_executed": halmos_properties_executed,
        "halmos_properties_skipped": halmos_properties_skipped,
        "halmos_failures": gen_halmos_failures,
        "oracle_run": oracle_run,
        "oracle_executed": oracle_executed,
        "oracle_skipped": oracle_skipped,
        "oracle_confirmed": oracle_confirmed,
        "admin_run": admin_run,
        "admin_executed": admin_executed,
        "admin_skipped": admin_skipped,
        "admin_confirmed": admin_confirmed,
        "storage_run": storage_run,
        "storage_executed": storage_executed,
        "storage_skipped": storage_skipped,
        "storage_confirmed": storage_confirmed,
        "clone_executed": clone_executed,
        "clone_skipped": clone_skipped,
        "clone_leads": clone_leads,
        "leads": leads,
        "confirmed": confirmed,
        "heat_gt0": heat_gt0,
        "engine_timing_rows": timing_rows,
    }


def _add_receipt_flags(sp: argparse.ArgumentParser) -> None:
    sp.add_argument(
        "--receipt",
        help="write this Markdown receipt file (single address) or a directory of .md files",
    )
    sp.add_argument(
        "--receipt-dir",
        help="directory for Markdown receipts (default: <work>/receipts/)",
    )
    sp.add_argument(
        "--no-receipt",
        action="store_true",
        help="skip writing a Markdown receipt",
    )


def _run_strong_deep_cli(args: Any, settings: Settings, store) -> int:
    from eth_scanner.deep.strong import run_strong_deep
    progress = run_strong_deep(
        settings=settings,
        store=store,
        path=getattr(args, "list_path", None) or None,
        workers=int(getattr(args, "workers", 2) or 2),
        deadline_minutes=float(getattr(args, "deadline_minutes", 40.0) or 40.0),
        reset=bool(getattr(args, "reset", False)),
    )
    runtime = " ".join(
        "%s=%dms" % (name, ms) for name, ms in sorted(progress.engine_runtime_ms.items())
    )
    print(
        "strong_deep status=%s strong=%d cursor=%d->%d scanned=%d "
        "known_safe_skipped=%d findings=%d heat_changed=%d errors=%d duration_s=%s"
        % (
            progress.status, progress.strong, progress.cursor_start, progress.cursor_next,
            progress.scanned, progress.skipped_known_safe, progress.findings_stored,
            progress.heat_changed, progress.errors, progress.duration_s,
        ),
        file=sys.stderr,
    )
    if runtime:
        print("strong_deep engine_runtime %s" % runtime, file=sys.stderr)
    print("strong_deep engines %s" % progress.availability, file=sys.stderr)
    for row in progress.heat_changes:
        print(
            "strong_deep heat_changed %s %s->%s tier=%s reason=%s"
            % (row.get("address"), row.get("heat_before"), row.get("heat_after"), row.get("tier"), row.get("candidate_reason")),
            file=sys.stderr,
        )
    if progress.message:
        print("strong_deep %s" % progress.message, file=sys.stderr)
    if getattr(args, "json", False):
        print(json.dumps(progress.to_dict(), indent=2))
    else:
        print(progress.message or progress.status)
    return 0 if progress.status in {"running", "done", "noop"} else 1


def _run_master_list_cli(args: Any, settings: Settings, store) -> int:
    """Primary feed. Default walks every configured list, then randoms."""
    from eth_scanner.feed.runner import run_master_list, run_scan_cycle

    list_id = str(getattr(args, "list_id", None) or "all")
    if list_id == "all":
        if getattr(args, "list_path", None):
            print("master_list: --list is ignored when --list-id is all", file=sys.stderr)
        progress = run_scan_cycle(
            settings=settings,
            store=store,
            workers=int(getattr(args, "workers", 8) or 8),
            deadline_minutes=float(getattr(args, "deadline_minutes", 40.0) or 40.0),
            reset=bool(getattr(args, "reset", False)),
        )
        print(
            "scan_cycle status=%s phase=%s lists=%d fresh_scanned=%d random_scanned=%d random_enabled=%s duration_s=%s"
            % (
                progress.status,
                progress.phase,
                len(progress.lists),
                progress.fresh_scanned,
                progress.random_scanned,
                progress.random_enabled,
                progress.duration_s,
            ),
            file=sys.stderr,
        )
        if progress.message:
            print("scan_cycle %s" % progress.message, file=sys.stderr)
        for row in progress.lists:
            print(
                "scan_cycle list=%s status=%s size=%s processed=%s cursor=%s->%s"
                % (
                    row.get("list_id"),
                    row.get("status"),
                    row.get("list_size"),
                    row.get("processed"),
                    row.get("cursor_start"),
                    row.get("cursor_next"),
                ),
                file=sys.stderr,
            )
        if getattr(args, "json", False):
            print(json.dumps(progress.to_dict(), indent=2))
        else:
            print(progress.message or progress.status)
        return 0 if progress.status in {"running", "done", "noop", "budget"} else 1

    min_funds = getattr(args, "min_funds_usd", None)
    max_funds = getattr(args, "max_funds_usd", None)
    progress = run_master_list(
        settings=settings,
        store=store,
        path=getattr(args, "list_path", None) or None,
        workers=int(getattr(args, "workers", 8) or 8),
        deadline_minutes=float(getattr(args, "deadline_minutes", 40.0) or 40.0),
        min_funds_usd=float(min_funds) if min_funds is not None else None,
        max_funds_usd=float(max_funds) if max_funds is not None else None,
        list_id=list_id,
        reset=bool(getattr(args, "reset", False)),
    )
    print(
        "master_list status=%s list=%d cursor=%d->%d processed=%d persisted=%d "
        "persist_failed=%d below_floor=%d heat_gt0=%d lane_b=%d errors=%d "
        "passes=%d resumed=%s duration_s=%s"
        % (
            progress.status,
            progress.list_size,
            progress.cursor_start,
            progress.cursor_next,
            progress.processed,
            progress.persisted,
            progress.persist_failed,
            progress.below_floor,
            progress.heat_gt0,
            progress.lane_b,
            progress.errors,
            progress.passes_completed,
            progress.resumed,
            progress.duration_s,
        ),
        file=sys.stderr,
    )
    if progress.message:
        print("master_list %s" % progress.message, file=sys.stderr)
    for sample in progress.samples:
        print(
            "master_list hot address=%s bucket=%s heat=%s funds=%s tier=%s reason=%s"
            % (
                sample.get("address"),
                sample.get("bucket"),
                sample.get("heat"),
                sample.get("funds_usd"),
                sample.get("tier"),
                sample.get("candidate_reason"),
            ),
            file=sys.stderr,
        )
    if getattr(args, "json", False):
        print(json.dumps(progress.to_dict(), indent=2))
    else:
        print(progress.message or progress.status)
    return 0 if progress.status in {"running", "done", "noop", "budget"} else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(
        prog="eth-scanner",
        description="Ethereum-only defensive invariant scanner (Lane A/B). "
                    "Emits buckets, never a human verdict. No PoCs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("lane-a", help="S0–S5 cheap skim + S6 gate")
    a.add_argument("--address", action="append", default=[], help="0x… (repeatable)")
    a.add_argument("--file", help="text file of addresses, one per line")
    a.add_argument("--source", help="local .sol/.vy file or directory (dry-run / no Etherscan)")
    a.add_argument("--tvl", type=float, default=None, help="TVL USD override")
    a.add_argument("--claim", type=int, default=0, help="claim N pending rows from the store")
    a.add_argument("--dry-run", action="store_true", help="force local work/ store")
    _add_receipt_flags(a)

    b = sub.add_parser("lane-b", help="S7 on lane-b-queue + manual-review")
    b.add_argument("--address", action="append", default=[], help="0x… (repeatable)")
    b.add_argument("--source", help="optional local source for heuristic re-scan")
    b.add_argument("--tvl", type=float, default=None)
    b.add_argument("--claim", type=int, default=5)
    b.add_argument("--dry-run", action="store_true")
    _add_receipt_flags(b)

    e = sub.add_parser("enqueue", help="upsert addresses as pending targets")
    e.add_argument("addresses", nargs="+")
    e.add_argument("--tvl", type=float, default=None)
    e.add_argument("--dry-run", action="store_true")

    ls = sub.add_parser("list", help="list targets / results")
    ls.add_argument("--bucket", default=None)
    ls.add_argument("--results", action="store_true")
    ls.add_argument("--dry-run", action="store_true")

    rec = sub.add_parser("receipt", help="rebuild a Markdown receipt from the store")
    rec.add_argument("--address", required=True, help="0x…")
    rec.add_argument("--lane", default="A", choices=("A", "B", "a", "b"))
    rec.add_argument("--receipt", help="write this .md file")
    rec.add_argument("--receipt-dir", help="directory for the .md (default: <work>/receipts/)")
    rec.add_argument("--dry-run", action="store_true")

    sub.add_parser("surface", help="run invariant_pass heuristics (passthrough)")
    sub.add_parser("research", help="Phase 2 research audit stack (defensive; see eth_scanner.research)")

    deep = sub.add_parser(
        "deep",
        help="Phase A deep engines (Slither/Aderyn/Mythril|Halmos) on lane-b-queue",
    )
    deep.add_argument("--address", action="append", default=[], help="0x… (repeatable)")
    deep.add_argument("--source", help="local Solidity file (skips Etherscan)")
    deep.add_argument("--claim", type=int, default=0, help="with --discover: claim N lane-b / manual-review rows")
    deep.add_argument(
        "--discover",
        action="store_true",
        help="claim the discovery queue instead of scanning the master list",
    )
    deep.add_argument("--workers", type=int, default=4, help="master-list mode: parallel Lane A workers")
    deep.add_argument("--deadline-minutes", type=float, default=15.0, help="master-list mode: stop after N minutes")
    deep.add_argument("--reset", action="store_true", help="master-list mode: restart the cursor at rank 1")
    deep.add_argument(
        "--engines",
        default="slither,aderyn,mythril,halmos",
        help="comma list of engines to attempt",
    )
    deep.add_argument("--timeout", type=int, default=90, help="per-engine timeout seconds")
    deep.add_argument("--json", action="store_true", help="print JSON report(s)")
    deep.add_argument("--dry-run", action="store_true")

    fp = sub.add_parser(
        "fork-props",
        help="Phase B read-only fork/eth_call properties (held|violated; no attack sequences)",
    )
    fp.add_argument("--address", required=True, help="0x…")
    fp.add_argument("--class", dest="contract_class", default="vault", help="contract class")
    fp.add_argument("--forge", action="store_true", help="also run defensive Foundry mock suite if forge is installed")
    fp.add_argument("--timeout", type=int, default=60)
    fp.add_argument("--json", action="store_true")
    fp.add_argument("--dry-run", action="store_true")

    fv = sub.add_parser(
        "fork-verify",
        help="Post-heat local-fork conservation check (Foundry invariants; no mainnet broadcast)",
    )
    fv.add_argument("--address", default="", help="0x… (live target; needs ETH_RPC_URL)")
    fv.add_argument("--fixture", choices=("leaky", "safe"), default="", help="plant a local anvil fixture (no RPC)")
    fv.add_argument("--from-store", action="store_true", dest="from_store", help="verify high-heat rows from the scan store")
    fv.add_argument("--min-heat", type=int, default=None, help="heat gate (default ETH_SCANNER_FUZZ_MIN_HEAT=8)")
    fv.add_argument("--limit", type=int, default=1, help="with --from-store: max unique addresses (default 1)")
    fv.add_argument("--timeout", type=int, default=None, help="per-contract seconds (default ETH_SCANNER_FUZZ_TIMEOUT_S=90)")
    fv.add_argument("--heat", type=int, default=None, help="declared heat for a single --address (default = min-heat)")
    fv.add_argument("--source", default="", help="optional Solidity used only to collect function selectors")
    fv.add_argument("--json", action="store_true")
    fv.add_argument("--dry-run", action="store_true", help="do not persist store patches")

    pg = sub.add_parser(
        "protocol-graph",
        help="Phase C protocol context graph + risk factors (read-only)",
    )
    pg.add_argument("--address", required=True, help="0x…")
    pg.add_argument("--source", help="optional local Solidity for static edges")
    pg.add_argument("--class", dest="contract_class", default="unknown")
    pg.add_argument("--funds", type=float, default=None, help="funds USD for weighting")
    pg.add_argument("--json", action="store_true")
    pg.add_argument("--dry-run", action="store_true")

    rq = sub.add_parser(
        "requeue-stale",
        help="Return stale high-heat contracts to pending for a rescan",
    )
    rq.add_argument("--runs", required=True, help="JSON list of finished scan rows")
    rq.add_argument("--dry-run", action="store_true")

    sol = sub.add_parser(
        "solana-discover",
        help="Read Solana TVL and program accounts. Adds no heat and sends nothing.",
    )
    sol.add_argument("--limit", type=int, default=20)
    sol.add_argument("--min-usd", type=float, default=None)
    sol.add_argument("--dry-run", action="store_true")
    sol.add_argument("--json", action="store_true")

    ins = sub.add_parser(
        "solana-inspect",
        help="Read a Solana program's upgrade authority and local source notes. Adds no heat.",
    )
    ins.add_argument("--address", required=True)
    ins.add_argument("--source", default=None, help="local .rs file or crate directory")
    ins.add_argument("--tools", action="store_true", help="run cargo-audit and clippy --offline if already installed")
    ins.add_argument("--json", action="store_true")
    ins.add_argument("--dry-run", action="store_true")

    sim = sub.add_parser(
        "solana-sim",
        help="Plan a local Solana validator. Refuses any non-loopback RPC and sends nothing.",
    )
    sim.add_argument("--address", required=True)
    sim.add_argument("--rpc", default="", help="loopback validator URL only")
    sim.add_argument("--clone", action="append", default=[], help="extra account to clone locally")
    sim.add_argument("--run", action="store_true", help="start the local validator when it is installed")
    sim.add_argument("--json", action="store_true")

    evm = sub.add_parser(
        "evm-chains",
        help="Show EVM chain ids and whether each RPC env is set. Never prints a URL.",
    )
    evm.add_argument("--json", action="store_true")

    evd = sub.add_parser(
        "evm-discover",
        help="Read BNB, Arbitrum, or Base TVL. Adds no heat and does not touch Ethereum.",
    )
    evd.add_argument("--chain", required=True, choices=("bsc", "arbitrum", "base", "bnb", "arb"))
    evd.add_argument("--limit", type=int, default=10)
    evd.add_argument("--min-usd", type=float, default=None)
    evd.add_argument("--dry-run", action="store_true")
    evd.add_argument("--json", action="store_true")

    sem = sub.add_parser(
        "evm-semantics",
        help="Read a chain's block meaning and optional BNB fork-shape flags. Adds no heat.",
    )
    sem.add_argument("--chain", required=True)
    sem.add_argument("--source", default=None, help="local source to scan for PancakeSwap or Venus names")
    sem.add_argument("--json", action="store_true")

    dec = sub.add_parser(
        "decompile-funded",
        help="Decompile an unverified funded contract. Lower confidence, no heat.",
    )
    dec.add_argument("--address", required=True)
    dec.add_argument("--funds", type=float, required=True)
    dec.add_argument("--bytecode", default="")
    dec.add_argument("--verified", action="store_true")
    dec.add_argument("--json", action="store_true")

    hack = sub.add_parser(
        "defihacklabs-index",
        help="Count public DeFiHackLabs incident names. Metadata only, no heat.",
    )
    hack.add_argument("--json", action="store_true")

    ai = sub.add_parser(
        "explain",
        help="Phase E optional LLM triage note (skipped without API key; never adds heat)",
    )
    ai.add_argument("--finding-json", required=True, help="path to a finding JSON object")
    ai.add_argument("--address", default="")
    ai.add_argument("--json", action="store_true")
    ai.add_argument("--dry-run", action="store_true")

    mon = sub.add_parser(
        "monitor",
        help="Scan the curated master list (default) or, with --discover, seed recent creates",
    )
    mon.add_argument("--limit", type=int, default=1000, help="discovery mode only: max creates to enqueue")
    mon.add_argument("--persist", action="store_true", help="write alerts to eth_scan_alerts when remote store")
    mon.add_argument("--no-discover", action="store_true", help="discovery mode only: skip recent-deploy seeding")
    mon.add_argument(
        "--discover",
        action="store_true",
        help="opt into alchemy/RPC create discovery (off by default; master list is the feed)",
    )
    mon.add_argument("--reset", action="store_true", help="master-list mode: restart the cursor at rank 1")
    mon.add_argument("--list", dest="list_path", default=None, help="override master_candidates.json path")
    mon.add_argument("--list-id", default="all", help="all (default), list-1, or list-2")
    mon.add_argument(
        "--lookback-hours",
        type=int,
        default=2,
        help="dense RPC lookback for creates since last run (default 2h)",
    )
    mon.add_argument("--max-blocks", type=int, default=800, help="max blocks to walk during discovery")
    mon.add_argument(
        "--scan",
        type=int,
        default=1000,
        help="max Lane A scans after seeding; drains pending until empty/deadline (default 1000)",
    )
    mon.add_argument(
        "--workers",
        type=int,
        default=8,
        help="parallel Lane A workers (default 8; respects Etherscan/Alchemy pacing)",
    )
    mon.add_argument(
        "--deadline-minutes",
        type=float,
        default=40.0,
        help="stop claiming new scan batches this many minutes after start (default 40)",
    )
    mon.add_argument(
        "--allow-unverified",
        action="store_true",
        help="keep unverified creates even when ETHERSCAN_API_KEYS is set",
    )
    mon.add_argument("--json", action="store_true")
    mon.add_argument("--dry-run", action="store_true")

    ml = sub.add_parser(
        "master-list",
        help="Scan the curated master candidate list in rank order (tier, then USD)",
    )
    ml.add_argument("--workers", type=int, default=8, help="parallel Lane A workers (default 8)")
    ml.add_argument("--deadline-minutes", type=float, default=40.0, help="stop after N minutes (default 40)")
    ml.add_argument("--list-id", default="all", help="all (default), list-1, or list-2")
    ml.add_argument("--min-funds-usd", type=float, default=None, help="override the list's configured minimum")
    ml.add_argument("--max-funds-usd", type=float, default=None, help="override the list's configured maximum")
    ml.add_argument("--reset", action="store_true", help="restart the resume cursor at rank 1")
    ml.add_argument("--list", dest="list_path", default=None, help="override master_candidates.json path")
    ml.add_argument("--json", action="store_true")
    ml.add_argument("--dry-run", action="store_true")

    sd = sub.add_parser(
        "strong-deep",
        help="Deep-scan strong master-list candidates (engines are evidence; heat stays live-only)",
    )
    sd.add_argument("--workers", type=int, default=2, help="parallel candidates (default 2)")
    sd.add_argument("--deadline-minutes", type=float, default=40.0)
    sd.add_argument("--reset", action="store_true", help="restart the strong-deep cursor at rank 1")
    sd.add_argument("--list", dest="list_path", default=None)
    sd.add_argument("--json", action="store_true")
    sd.add_argument("--dry-run", action="store_true")

    disc = sub.add_parser(
        "discover",
        help="Seed queue from recent mainnet contract creations (read-only)",
    )
    disc.add_argument("--lookback-hours", type=int, default=2)
    disc.add_argument("--max-blocks", type=int, default=800)
    disc.add_argument("--max-results", type=int, default=1000)
    disc.add_argument("--enqueue", action="store_true", help="upsert discoveries as pending targets")
    disc.add_argument("--allow-unverified", action="store_true", help="keep creates even when not verified")
    disc.add_argument("--json", action="store_true")
    disc.add_argument("--dry-run", action="store_true")

    fresh = sub.add_parser(
        "fresh-deploys",
        help="Watch the chain head for brand-new contracts and enqueue funded ones (read-only)",
    )
    fresh.add_argument("--lookback-blocks", type=int, default=None, help="first-run lookback (default 50, ~10 min)")
    fresh.add_argument("--max-blocks", type=int, default=None, help="max blocks to walk this run (default 100)")
    fresh.add_argument("--min-funds-usd", type=float, default=None, help="override the $100 intake floor")
    fresh.add_argument("--reset", action="store_true", help="restart the block cursor at head-lookback")
    fresh.add_argument("--scan", type=int, default=0, help="after enqueue, scan up to N pending fresh-deploys")
    fresh.add_argument("--workers", type=int, default=4, help="parallel Lane A workers when --scan is set")
    fresh.add_argument("--deadline-minutes", type=float, default=4.0, help="stop starting new scans after N minutes")
    fresh.add_argument("--json", action="store_true")
    fresh.add_argument("--dry-run", action="store_true")

    bf = sub.add_parser(
        "backfill",
        help="Scan the master list (default) or, with --discover, the 30d create backfill",
    )
    bf.add_argument(
        "--discover",
        action="store_true",
        help="opt into historical create discovery (off by default)",
    )
    bf.add_argument("--id", default="mainnet-30d", help="backfill cursor id")
    bf.add_argument("--lookback-days", type=float, default=30.0)
    bf.add_argument("--chunk-blocks", type=int, default=2000)
    bf.add_argument("--workers", type=int, default=8)
    bf.add_argument("--deadline-minutes", type=float, default=40.0)
    bf.add_argument("--max-full-scans", type=int, default=200, help="discovery mode only: Lane A cap per job")
    bf.add_argument("--list-id", default="all", help="all (default), list-1, or list-2")
    bf.add_argument("--min-funds-usd", type=float, default=None, help="override the list's configured minimum")
    bf.add_argument("--max-funds-usd", type=float, default=None, help="override the list's configured maximum")
    bf.add_argument("--reset", action="store_true", help="restart the master-list cursor, or the block cursor in --discover mode")
    bf.add_argument("--json", action="store_true")
    bf.add_argument("--dry-run", action="store_true")

    blend = sub.add_parser(
        "blend",
        help="Fused Ityfuzz/Halmos/Medusa/Echidna lane (local simulation only)",
    )
    blend.add_argument("--address", default="", help="0x… on-demand target")
    blend.add_argument("--list", dest="list_id", default=None, help="list-1, list-2, or all")
    blend.add_argument("--fixture", default=None, help="leaky, safe, leaky-strategy, evidence-only, incentive")
    blend.add_argument("--catalog", action="store_true", help="print list counts and engine pins")
    blend.add_argument("--select", action="store_true", help="print one page of a named list")
    blend.add_argument("--offset", type=int, default=0)
    blend.add_argument("--limit", type=int, default=40)
    blend.add_argument("--timeout", type=int, default=90)
    blend.add_argument("--json", action="store_true")

    args, rest = p.parse_known_args(argv)
    if args.cmd == "surface":
        return surface_main(rest)
    if args.cmd == "research":
        from eth_scanner.research.cli import main as research_main
        return research_main(rest)
    if args.cmd == "blend":
        return _run_blend_cli(args)

    settings = load_settings()
    if getattr(args, "dry_run", False):
        settings.dry_run = True
    store = open_store(settings)

    if args.cmd == "requeue-stale":
        import json as _json
        from eth_scanner.desk.stale_rescan import apply_stale, plan_stale
        runs = _json.loads(Path(args.runs).read_text(encoding="utf-8"))
        if not isinstance(runs, list):
            print("requeue-stale: --runs must be a JSON list", file=sys.stderr)
            return 2
        planned = plan_stale(runs)
        if args.dry_run:
            print(_json.dumps(planned, indent=2))
            return 0
        applied = apply_stale(store, [row["address"] for row in planned])
        print(_json.dumps({"planned": len(planned), "requeued": applied}, indent=2))
        return 0

    if args.cmd == "solana-discover":
        import json as _json
        from eth_scanner.chains.solana_discover import discover as _solana_discover
        from eth_scanner.chains.solana_discover import enqueue as _solana_enqueue
        from eth_scanner.types import DEFAULT_MIN_FUNDS_USD
        floor = float(args.min_usd) if args.min_usd is not None else DEFAULT_MIN_FUNDS_USD
        report = _solana_discover(limit=int(args.limit or 20), min_usd=floor)
        saved: list[str] = []
        if not args.dry_run:
            saved = _solana_enqueue(store, report)
        out = {
            "chain": report["chain"],
            "heat_contribution": report["heat_contribution"],
            "rpc": report["rpc"],
            "degraded": report["degraded"],
            "candidates": len(report["candidates"]),
            "enqueued": saved,
            "sample": [
                {"name": row["name"], "address": row["address"], "funds_usd": row["funds_usd"]}
                for row in report["candidates"][:10]
            ],
        }
        print(_json.dumps(out, indent=2))
        return 0

    if args.cmd == "solana-inspect":
        import json as _json
        from eth_scanner.chains.solana_static import inspect_program
        report = inspect_program(
            args.address,
            source=args.source,
            run_tools=bool(args.tools),
        )
        print(_json.dumps(report, indent=2))
        return 0

    if args.cmd == "solana-sim":
        import json as _json
        from eth_scanner.chains.solana_sim import plan_sim
        report = plan_sim(
            args.address,
            rpc=args.rpc or "",
            clones=list(args.clone or []),
            execute=bool(args.run),
        )
        print(_json.dumps(report, indent=2))
        return 0

    if args.cmd == "evm-chains":
        import json as _json
        from eth_scanner.chains.evm import describe_all
        print(_json.dumps(describe_all(), indent=2))
        return 0

    if args.cmd == "evm-discover":
        import json as _json
        from eth_scanner.chains.evm_discover import discover as _evm_discover
        from eth_scanner.chains.evm_discover import enqueue as _evm_enqueue
        from eth_scanner.types import DEFAULT_MIN_FUNDS_USD
        floor = float(args.min_usd) if args.min_usd is not None else DEFAULT_MIN_FUNDS_USD
        report = _evm_discover(args.chain, limit=int(args.limit or 10), min_usd=floor)
        saved = {"enqueued": [], "skipped": []}
        if not args.dry_run and not report.get("refused"):
            saved = _evm_enqueue(store, report)
        out = {
            "chain": report.get("chain"),
            "refused": report.get("refused", False),
            "heat_contribution": 0,
            "min_usd": report.get("min_usd"),
            "degraded": report.get("degraded"),
            "daily_scans": report.get("daily_scans"),
            "monthly_cu": report.get("monthly_cu"),
            "ethereum_monthly_cu": report.get("ethereum_monthly_cu"),
            "within_cap": report.get("within_cap"),
            "candidates": len(report.get("candidates") or []),
            "enqueued": saved.get("enqueued") or [],
            "skipped": saved.get("skipped") or [],
            "sample": [
                {
                    "name": row.get("name"),
                    "address": row.get("address"),
                    "funds_usd": row.get("funds_usd"),
                    "has_code": row.get("has_code"),
                }
                for row in (report.get("candidates") or [])[:10]
            ],
        }
        print(_json.dumps(out, indent=2))
        return 0

    if args.cmd == "evm-semantics":
        import json as _json
        from eth_scanner.chains.evm import call_with_backoff
        from eth_scanner.chains.evm_discover import _rpc_call
        from eth_scanner.chains.evm_semantics import interpret_block, scan_bsc_forks
        try:
            header = call_with_backoff(
                args.chain,
                "eth_getBlockByNumber",
                ["latest", False],
                rpc=_rpc_call,
            )
            report = interpret_block(args.chain, header)
        except Exception as exc:  # noqa: BLE001
            report = {
                "chain": args.chain,
                "heat_contribution": 0,
                "degraded": True,
                "l1_source": "unknown",
                "rpc_error": type(exc).__name__,
                "note": "Block header was not read. L1 and L2 numbers stay unknown.",
            }
        if args.source:
            text = Path(args.source).read_text(encoding="utf-8", errors="replace")
            report["fork_flags"] = scan_bsc_forks(text)
        print(_json.dumps(report, indent=2))
        return 0

    if args.cmd == "decompile-funded":
        import json as _json
        from eth_scanner.decompile.heimdall import decompile_unverified_funded
        report = decompile_unverified_funded(
            args.address,
            funds_usd=args.funds,
            verified=bool(args.verified),
            bytecode=args.bytecode or "",
        )
        shown = {k: v for k, v in report.items() if k != "content"}
        shown["content_chars"] = len(report.get("content") or "")
        print(_json.dumps(shown, indent=2))
        return 0

    if args.cmd == "defihacklabs-index":
        import json as _json
        from eth_scanner.benchmark.defihacklabs import index_report
        from eth_scanner.benchmark.eval import load_labeled
        try:
            labeled = list((load_labeled().get("entries") or []))
        except OSError:
            labeled = []
        print(_json.dumps(index_report(labeled), indent=2))
        return 0

    if args.cmd == "strong-deep" or (
        args.cmd == "deep" and not args.discover and not args.address
    ):
        return _run_strong_deep_cli(args, settings, store)

    if args.cmd in {"master-list", "monitor", "backfill"} and not (
        (args.cmd == "monitor" and args.discover)
        or (args.cmd == "backfill" and args.discover)
    ):
        if args.cmd == "monitor" and int(getattr(args, "scan", 0) or 0) > 0:
            print(
                "monitor: master-list feed has no per-run cap (--scan ignored); resume cursor covers the rest",
                file=sys.stderr,
            )
        if args.cmd == "backfill":
            print(
                "backfill: master-list feed (pass --discover for historical create walk)",
                file=sys.stderr,
            )
        return _run_master_list_cli(args, settings, store)

    if args.cmd == "deep":
        from eth_scanner.deep.worker import run_deep_claim, run_deep_one
        engines = [e.strip() for e in str(args.engines or "").split(",") if e.strip()]
        reports: list[dict[str, Any]] = []
        source_text: Optional[str] = None
        if args.source:
            source_text = Path(args.source).read_text(encoding="utf-8", errors="replace")
        if args.claim and args.claim > 0:
            reports.extend(run_deep_claim(
                limit=int(args.claim),
                settings=settings,
                store=store,
                engines=engines,
                timeout_s=int(args.timeout),
            ))
        for raw in args.address:
            reports.append(run_deep_one(
                raw,
                settings=settings,
                store=store,
                source_text=source_text,
                engines=engines,
                timeout_s=int(args.timeout),
            ))
        if not reports:
            print("deep: pass --claim N and/or --address 0x…", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2))
        else:
            for rep in reports:
                print(
                    "%s status=%s findings=%d multi_engine=%s"
                    % (
                        rep.get("address"),
                        rep.get("status"),
                        len(rep.get("findings") or []),
                        (rep.get("agreement") or {}).get("multi_engine_clusters"),
                    )
                )
        return 0

    if args.cmd == "fork-verify":
        from eth_scanner.engines.fork_verify import (
            apply_fork_verify_to_row,
            fuzz_min_heat,
            fuzz_timeout_s,
            list_high_heat_rows,
            persist_fork_verify,
            run_fork_verify,
        )
        min_heat = int(args.min_heat) if args.min_heat is not None else fuzz_min_heat()
        timeout = int(args.timeout) if args.timeout is not None else fuzz_timeout_s()
        rpc = getattr(settings, "eth_rpc_url", "") or ""
        source_text = ""
        if args.source:
            source_text = Path(args.source).read_text(encoding="utf-8", errors="replace")
        payloads: list[dict] = []
        if args.fixture:
            report = run_fork_verify(
                fixture=args.fixture,
                work_dir=settings.work_dir / "fork-verify",
                timeout_s=timeout,
            )
            payloads.append(report.to_dict())
        elif args.from_store:
            from eth_scanner.ingest.rpc_client import is_rpc_usable, rpc_unusable_reason
            if not rpc or not is_rpc_usable(rpc):
                reason = rpc_unusable_reason(rpc) if rpc else "no ETH_RPC_URL"
                payloads.append({
                    "skipped": True,
                    "status": "skipped",
                    "drainable": False,
                    "skip_reason": reason,
                    "notes": ["fork-verify --from-store skipped — %s" % reason],
                })
            else:
                store = open_store(settings)
                rows = list_high_heat_rows(store, min_heat=min_heat, limit=max(1, int(args.limit)))
                if not rows:
                    payloads.append({
                        "skipped": True,
                        "status": "skipped",
                        "skip_reason": "no store rows at heat >= %s" % min_heat,
                    })
                for row in rows:
                    report = run_fork_verify(
                        address=str(row.get("address") or ""),
                        rpc_url=rpc,
                        heat=int(row.get("heat") or 0),
                        source=source_text,
                        work_dir=settings.work_dir / "fork-verify",
                        timeout_s=timeout,
                        force=True,
                    )
                    item = report.to_dict()
                    item["store_heat_in"] = row.get("heat")
                    item["store_bucket_in"] = row.get("bucket")
                    if not args.dry_run and settings.persist_remote:
                        patched = apply_fork_verify_to_row(row, report)
                        persist_fork_verify(store, row, patched)
                        item["persisted"] = True
                        item["store_heat_out"] = patched.get("heat")
                        item["store_bucket_out"] = patched.get("bucket")
                    else:
                        item["persisted"] = False
                    payloads.append(item)
        else:
            if not args.address:
                print("fork-verify: pass --address, --fixture, or --from-store", file=sys.stderr)
                return 2
            declared = int(args.heat) if args.heat is not None else min_heat
            report = run_fork_verify(
                address=args.address,
                rpc_url=rpc,
                heat=declared,
                source=source_text,
                work_dir=settings.work_dir / "fork-verify",
                timeout_s=timeout,
                force=True,
            )
            payloads.append(report.to_dict())
        if args.json:
            print(json.dumps(payloads if len(payloads) != 1 else payloads[0], indent=2))
        else:
            for item in payloads:
                print(
                    "fork-verify status=%s drainable=%s tool=%s heat_in=%s seq=%s"
                    % (
                        item.get("status"),
                        item.get("drainable"),
                        item.get("tool"),
                        item.get("heat_in"),
                        (item.get("sequence") or item.get("skip_reason") or "")[:160],
                    )
                )
        # Fixture true-positive must actually break; otherwise fail CI.
        if args.fixture == "leaky" and not any(p.get("drainable") for p in payloads):
            return 1
        if args.fixture == "safe" and any(p.get("drainable") for p in payloads):
            return 1
        return 0

    if args.cmd == "fork-props":
        from eth_scanner.fork_props.runner import run_fork_properties
        rows = run_fork_properties(
            args.address,
            contract_class=str(args.contract_class or "vault"),
            rpc_url=getattr(settings, "eth_rpc_url", "") or "",
            run_forge=bool(args.forge),
            timeout_s=float(args.timeout),
        )
        payload = [r.to_dict() for r in rows]
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            for r in payload:
                print("%s %s %s — %s" % (r["status"], r["id"], r["severity"], r["evidence"][:120]))
        return 0

    if args.cmd == "protocol-graph":
        from eth_scanner.protocol_graph.builder import build_protocol_graph
        from eth_scanner.protocol_graph.risk import score_graph_risks
        source_text = ""
        if args.source:
            source_text = Path(args.source).read_text(encoding="utf-8", errors="replace")
        graph = build_protocol_graph(
            args.address,
            source=source_text,
            contract_class=str(args.contract_class or "unknown"),
            rpc_url=getattr(settings, "eth_rpc_url", "") or "",
        )
        risks = score_graph_risks(graph, funds_usd=args.funds, source=source_text)
        payload = {"graph": graph.to_dict(), "risks": risks}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("nodes=%d edges=%d factors=%d max_likelihood=%s" % (
                len(graph.nodes), len(graph.edges),
                len(risks.get("factors") or []), risks.get("max_likelihood"),
            ))
            for f in risks.get("factors") or []:
                print("- %s (L=%s): %s" % (f.get("id"), f.get("likelihood"), f.get("detail")))
        return 0

    if args.cmd == "explain":
        from eth_scanner.triage_ai.explain import explain_finding
        finding = json.loads(Path(args.finding_json).read_text(encoding="utf-8"))
        out = explain_finding(finding, context={"address": args.address})
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            print("%s: %s" % (out.get("status"), out.get("explanation")))
        return 0 if out.get("status") in {"ok", "skipped"} else 1

    if args.cmd == "backfill":
        from eth_scanner.backfill.runner import run_backfill_job
        progress = run_backfill_job(
            settings=settings,
            store=store,
            backfill_id=str(args.id),
            lookback_days=float(args.lookback_days),
            chunk_blocks=int(args.chunk_blocks),
            workers=int(args.workers),
            deadline_minutes=float(args.deadline_minutes),
            min_funds_usd=float(args.min_funds_usd) if args.min_funds_usd is not None else float(settings.min_funds_usd),
            max_full_scans=int(args.max_full_scans),
            reset=bool(args.reset),
        )
        # Contracts processed = cumulative full Lane-A scans; remaining ≈
        # funds≥floor not yet fully scanned (lower bound) plus block window left.
        contracts_processed = int(progress.fully_scanned_total or 0)
        contracts_remaining = max(
            0,
            int(progress.funds_ge_floor_total or 0) - contracts_processed,
        )
        print(
            "backfill status=%(status)s cursor=%(cursor_block)d end=%(end_block)d "
            "start=%(start_block)d covered=%(blocks_covered_this_job)d "
            "blocks_remaining=%(blocks_remaining)d "
            "contracts_processed=%(contracts_processed)d "
            "contracts_remaining=%(contracts_remaining)d "
            "discovered_total=%(discovered_total)d funds_ge_floor_total=%(funds_ge_floor_total)d "
            "fully_scanned_total=%(fully_scanned_total)d heat_positive_total=%(heat_positive_total)d "
            "discovered=%(discovered_this_job)d funds_ge_floor=%(funds_ge_floor_this_job)d "
            "scanned=%(fully_scanned_this_job)d heat_gt0=%(heat_positive_this_job)d "
            "duration_s=%(duration_s)s eta_hours=%(eta_hours)s source=%(source)s"
            % {
                **progress.to_dict(),
                "eta_hours": progress.eta_hours,
                "contracts_processed": contracts_processed,
                "contracts_remaining": contracts_remaining,
            },
            file=sys.stderr,
        )
        if args.json:
            print(json.dumps(progress.to_dict(), indent=2))
        else:
            print(progress.message or progress.status)
            for sample in progress.heat_positive_samples[:10]:
                print(
                    "heat>0 %s heat=%s class=%s funds=%s"
                    % (sample.get("address"), sample.get("heat"), sample.get("contract_class"), sample.get("funds_usd"))
                )
        return 0 if progress.status in {"running", "done", "noop"} else 1

    if args.cmd == "fresh-deploys":
        import time as _time
        from eth_scanner.discover.fresh import FRESH_SOURCE, run_fresh_deploy_discovery

        started = _time.monotonic()
        stats = run_fresh_deploy_discovery(
            store=store,
            rpc_url=getattr(settings, "eth_rpc_url", "") or "",
            lookback=getattr(args, "lookback_blocks", None),
            max_blocks=getattr(args, "max_blocks", None),
            min_funds_usd=getattr(args, "min_funds_usd", None),
            reset=bool(getattr(args, "reset", False)),
        )
        scanned: list = []
        scan_n = int(getattr(args, "scan", 0) or 0)
        if scan_n > 0 and stats.status in {"done", "running", "noop"}:
            deadline_min = float(getattr(args, "deadline_minutes", 4.0) or 4.0)
            scanned = lane_a.claim_and_drain(
                max_scans=scan_n,
                workers=max(1, int(getattr(args, "workers", 4) or 4)),
                deadline_monotonic=started + max(30.0, deadline_min * 60.0),
                settings=settings,
                store=store,
                discovery_source=FRESH_SOURCE,
            )
        payload = {
            **stats.to_dict(),
            "scanned": len(scanned),
            "duration_s": round(_time.monotonic() - started, 1),
        }
        print(
            "fresh-deploys status=%(status)s rpc=%(rpc_configured)s blocks=%(from_block)s-%(to_block)s "
            "head=%(head_block)s cursor=%(cursor_start)s->%(cursor_next)s creates=%(creates_found)d "
            "enqueued=%(enqueued)d requeued=%(requeued)d below_floor=%(below_floor)d "
            "already=%(already_present)d scanned=%(scanned)d source=%(source)s duration_s=%(duration_s)s"
            % payload,
            file=sys.stderr,
        )
        if stats.message:
            print("fresh-deploys %s" % stats.message, file=sys.stderr)
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(stats.message or stats.status)
            for addr in (stats.enqueued_addresses or [])[:20]:
                print("enqueued %s" % addr)
            for addr in (stats.below_floor_addresses or [])[:10]:
                print("below-floor %s" % addr)
        if stats.status == "error":
            return 1
        return 0

    if args.cmd == "discover":
        from eth_scanner.monitor.watch import seed_recent_deployments
        from eth_scanner.discover.recent import discover_recent_deployments
        keys = ",".join(getattr(settings, "etherscan_api_keys", None) or []) or (
            os.environ.get("ETHERSCAN_API_KEYS") or ""
        )
        prefer_verified: Optional[bool] = False if args.allow_unverified else None
        if args.enqueue:
            rows, stats = seed_recent_deployments(
                store,
                rpc_url=getattr(settings, "eth_rpc_url", "") or "",
                etherscan_keys=keys,
                lookback_hours=int(args.lookback_hours),
                max_blocks=int(args.max_blocks),
                max_results=int(args.max_results),
                prefer_verified=prefer_verified,
            )
        else:
            rows, stats = discover_recent_deployments(
                rpc_url=getattr(settings, "eth_rpc_url", "") or "",
                etherscan_keys=keys or (os.environ.get("ETHERSCAN_API_KEYS") or ""),
                lookback_hours=int(args.lookback_hours),
                max_blocks=int(args.max_blocks),
                max_results=int(args.max_results),
                prefer_verified=prefer_verified,
            )
        payload = {
            "stats": stats.to_dict(),
            "enqueued": bool(args.enqueue),
            "contracts": [r.to_dict() for r in rows],
        }
        # Always log summary counts (even with --json on stderr).
        print(
            "discovery creates_found=%d verified_kept=%d unverified_skipped=%d "
            "known_safe_skipped=%d prefer_verified=%s keys=%s kept=%d"
            % (
                stats.creates_found,
                stats.verified_kept,
                stats.unverified_skipped,
                stats.known_safe_skipped,
                stats.prefer_verified,
                stats.keys_configured,
                len(rows),
            ),
            file=sys.stderr,
        )
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("discovered=%d enqueue=%s" % (len(rows), bool(args.enqueue)))
            for r in payload["contracts"][:20]:
                print("%s block=%s verified=%s name=%s" % (
                    r["address"], r["deployed_block"], r.get("verified"), r.get("contract_name") or "—",
                ))
        return 0

    if args.cmd == "monitor":
        import time as _time
        from eth_scanner.monitor.watch import scan_watchlist
        prefer_verified = False if args.allow_unverified else None
        started = _time.monotonic()
        alerts, disc_stats, discovered = scan_watchlist(
            store,
            rpc_url=getattr(settings, "eth_rpc_url", "") or "",
            limit=int(args.limit),
            seed_discoveries=not bool(args.no_discover),
            lookback_hours=int(args.lookback_hours),
            max_blocks=int(getattr(args, "max_blocks", 800) or 800),
            prefer_verified=prefer_verified,
        )
        scan_results: list[dict[str, Any]] = []
        workers = max(1, int(getattr(args, "workers", 8) or 8))
        deadline_min = float(getattr(args, "deadline_minutes", 40.0) or 40.0)
        deadline = started + max(60.0, deadline_min * 60.0)
        if int(args.scan or 0) > 0:
            drained = lane_a.claim_and_drain(
                max_scans=int(args.scan),
                workers=workers,
                deadline_monotonic=deadline,
                settings=settings,
                store=store,
            )
            scan_results = [row for _addr, row in drained]
        duration_s = round(_time.monotonic() - started, 1)
        if args.persist:
            persist_fn = getattr(store, "save_alerts", None)
            if callable(persist_fn):
                persist_fn([a.to_dict() for a in alerts])
            else:
                print("monitor: store cannot persist alerts", file=sys.stderr)
        engine_stats = _aggregate_engine_stats(scan_results)
        summary = {
            "creates_found": disc_stats.creates_found,
            "verified_kept": disc_stats.verified_kept,
            "unverified_skipped": disc_stats.unverified_skipped,
            "known_safe_skipped": disc_stats.known_safe_skipped,
            "prefer_verified": disc_stats.prefer_verified,
            "keys_configured": disc_stats.keys_configured,
            "discovered_enqueued": len(discovered),
            "scanned": len(scan_results),
            "alerts": len(alerts),
            "workers": workers,
            "duration_s": duration_s,
            **engine_stats,
        }
        # Human-readable counts always on stderr for Actions logs.
        print(
            "monitor creates_found=%(creates_found)d verified_kept=%(verified_kept)d "
            "unverified_skipped=%(unverified_skipped)d discovered_enqueued=%(discovered_enqueued)d "
            "scanned=%(scanned)d workers=%(workers)d duration_s=%(duration_s)s "
            "prefer_verified=%(prefer_verified)s keys=%(keys_configured)s "
            "slither_run=%(slither_run)d slither_executed=%(slither_executed)d slither_skipped=%(slither_skipped)d "
            "mythril_run=%(mythril_run)d mythril_executed=%(mythril_executed)d mythril_skipped=%(mythril_skipped)d "
            "fuzzed=%(fuzzed)d fuzz_executed=%(fuzz_executed)d fuzz_skipped=%(fuzz_skipped)d "
            "fuzz_properties=%(fuzz_properties)d fuzz_failures=%(fuzz_failures)d "
            "halmos_run=%(halmos_run)d halmos_executed=%(halmos_executed)d halmos_skipped=%(halmos_skipped)d "
            "halmos_properties=%(halmos_properties)d "
            "halmos_properties_executed=%(halmos_properties_executed)d "
            "halmos_properties_skipped=%(halmos_properties_skipped)d "
            "halmos_failures=%(halmos_failures)d "
            "oracle_run=%(oracle_run)d oracle_executed=%(oracle_executed)d oracle_skipped=%(oracle_skipped)d "
            "oracle_confirmed=%(oracle_confirmed)d "
            "admin_run=%(admin_run)d admin_executed=%(admin_executed)d admin_skipped=%(admin_skipped)d "
            "admin_confirmed=%(admin_confirmed)d "
            "storage_run=%(storage_run)d storage_executed=%(storage_executed)d storage_skipped=%(storage_skipped)d "
            "storage_confirmed=%(storage_confirmed)d "
            "clone_executed=%(clone_executed)d clone_skipped=%(clone_skipped)d clone_leads=%(clone_leads)d "
            "leads=%(leads)d confirmed=%(confirmed)d heat_gt0=%(heat_gt0)d"
            % summary,
            file=sys.stderr,
        )
        payload = {
            "summary": summary,
            "discovery_stats": disc_stats.to_dict(),
            "alerts": [a.to_dict() for a in alerts],
            "scans": scan_results,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                "alerts=%d scans=%d creates_found=%d verified_kept=%d unverified_skipped=%d duration_s=%s"
                % (
                    len(alerts),
                    len(scan_results),
                    disc_stats.creates_found,
                    disc_stats.verified_kept,
                    disc_stats.unverified_skipped,
                    duration_s,
                )
            )
            for a in alerts:
                print("%s %s %s" % (a.kind, a.address, a.detail))
            for s in scan_results:
                print(
                    "scan %s bucket=%s heat=%s drop=%s funds=%s"
                    % (s.get("address"), s.get("bucket"), s.get("heat"), s.get("drop_reason"), s.get("funds_usd"))
                )
        return 0

    if args.cmd == "enqueue":
        from eth_scanner.types import Target
        for raw in args.addresses:
            t = Target(address=normalize_address(raw), tvl_usd=args.tvl, status="pending")
            store.upsert_target(t)
            print(t.address)
        print("store=%s" % ("remote" if settings.persist_remote else "dry-run %s" % settings.work_dir), file=sys.stderr)
        return 0

    if args.cmd == "list":
        if args.results:
            rows = store.list_results()
        else:
            rows = store.list_targets(bucket=args.bucket)
        print(json.dumps(rows, indent=2))
        return 0

    if args.cmd == "receipt":
        addr = normalize_address(args.address)
        rows = store.list_results(addr, limit=1)
        if not rows:
            print("receipt: no stored result for %s" % addr, file=sys.stderr)
            return 2
        dest_dir, dest_file = _receipt_dest(args, settings, n_results=1)
        path = write_run_receipt(
            address=addr,
            lane=args.lane.upper(),
            result=rows[0],
            artifact=pick_source_artifact(store.list_artifacts(addr)),
            target=store.get_target(addr),
            dest_dir=dest_dir,
            dest_file=dest_file,
            worker_id=settings.worker_id,
        )
        print(path)
        print("receipt %s" % path, file=sys.stderr)
        return 0

    if args.cmd == "lane-a":
        addrs = list(args.address)
        if args.file:
            addrs.extend(_read_addrs(Path(args.file)))
        source = Path(args.source) if args.source else None
        results = []
        if addrs:
            results = lane_a.run_batch(addrs, settings=settings, store=store, source_path=source, tvl_usd=args.tvl)
        elif args.claim:
            results = lane_a.claim_and_run(args.claim, settings=settings)
        else:
            print("lane-a: pass --address, --file, or --claim N", file=sys.stderr)
            return 2
        paths = _emit_receipts(results, settings, store, args, lane="A")
        _print_results(results, settings, paths)
        return 0

    if args.cmd == "lane-b":
        addrs = list(args.address)
        source_text = Path(args.source).read_text(encoding="utf-8") if args.source else None
        results = []
        if addrs:
            for raw in addrs:
                r = lane_b.run_one(raw, settings=settings, store=store, source_text=source_text, tvl_usd=args.tvl)
                results.append((normalize_address(raw), r))
        else:
            results = lane_b.claim_and_run(args.claim, settings=settings)
        paths = _emit_receipts(results, settings, store, args, lane="B")
        _print_results(results, settings, paths)
        return 0

    p.error("unknown command")
    return 2


def _run_blend_cli(args: Any) -> int:
    """Print a Blend receipt or a list page. No store, no broadcast."""
    from eth_scanner.deep.blend.orchestrator import run_blend
    from eth_scanner.feed.lists import catalog, page_contracts, select_deep

    if args.catalog:
        print(json.dumps(catalog()))
        return 0
    if args.select:
        if not args.list_id:
            print("blend: --select needs --list list-1 or list-2", file=sys.stderr)
            return 2
        print(json.dumps(page_contracts(args.list_id, offset=args.offset, limit=args.limit)))
        return 0
    if args.fixture:
        report = run_blend(fixture=args.fixture, list_id=args.list_id)
    elif args.address:
        rows = []
        if args.list_id:
            rows = select_deep(args.list_id, address=args.address)
        fixture = None
        funds = None
        name = ""
        if rows:
            fixture = rows[0].get("fixture")
            funds = rows[0].get("est_usd_held")
            name = rows[0].get("protocol") or ""
        if fixture:
            report = run_blend(fixture=str(fixture), list_id=args.list_id)
        else:
            report = run_blend(
                address=args.address,
                funds_usd=funds,
                contract_name=name,
                list_id=args.list_id,
                fork_url=(os.environ.get("ETH_RPC_URL") or ""),
                timeout_s=int(args.timeout or 90),
            )
    else:
        print("blend: pass --fixture, --address, --catalog, or --select", file=sys.stderr)
        return 2
    print(json.dumps(report))
    return 0


def _read_addrs(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def _receipt_dest(args: Any, settings: Settings, n_results: int) -> tuple[Optional[Path], Optional[Path]]:
    raw = getattr(args, "receipt", None)
    dest_dir = getattr(args, "receipt_dir", None)
    dest_file: Optional[Path] = None
    if dest_dir:
        return Path(dest_dir), None
    if raw:
        p = Path(raw)
        if n_results > 1 or p.is_dir() or str(raw).endswith(("/", "\\")):
            return p, None
        if p.suffix.lower() == ".md" or n_results == 1:
            return p.parent if str(p.parent) != "" else default_receipt_dir(settings.work_dir), p
        return p, None
    return default_receipt_dir(settings.work_dir), dest_file


def _emit_receipts(results, settings: Settings, store, args: Any, *, lane: str) -> list[Optional[Path]]:
    if getattr(args, "no_receipt", False):
        return [None] * len(results)
    dest_dir, dest_file = _receipt_dest(args, settings, n_results=len(results))
    paths: list[Optional[Path]] = []
    for addr, res in results:
        this_file = dest_file if dest_file is not None and len(results) == 1 else None
        artifact = pick_source_artifact(store.list_artifacts(addr))
        target = store.get_target(addr)
        path = write_run_receipt(
            address=addr,
            lane=lane,
            result=res if isinstance(res, FunnelResult) else res,
            artifact=artifact,
            target=target,
            dest_dir=None if this_file else dest_dir,
            dest_file=this_file,
            worker_id=settings.worker_id,
        )
        paths.append(path)
    return paths


def _print_results(results, settings, paths: Optional[list[Optional[Path]]] = None) -> None:
    payload = []
    paths = paths or [None] * len(results)
    for (addr, res), path in zip(results, paths):
        payload.append({
            "address": addr,
            "bucket": res.bucket,
            "dropped": res.dropped,
            "drop_reason": res.drop_reason,
            "heat": res.heat,
            "src_confidence": res.src_confidence,
            "ir_confidence": res.ir_confidence,
            "value_movers": res.value_movers,
            "contract_class": res.contract_class,
            "scope": res.scope,
            "stage_trace": to_plain(res.stage_trace),
            "notes": res.notes,
            "funds_usd": getattr(res, "funds_usd", None),
            "funds_breakdown": getattr(res, "funds_breakdown", None) or [],
            "funds_status": getattr(res, "funds_status", None),
            "funds_checked_at": getattr(res, "funds_checked_at", None),
            "invariant_results": getattr(res, "invariant_results", None) or [],
            "heat_breakdown": getattr(res, "heat_breakdown", None) or {},
            "known_safe": bool(getattr(res, "known_safe", False)),
            "contract_name": getattr(res, "contract_name", None),
            "receipt_path": str(path) if path else None,
        })
    print(json.dumps(payload, indent=2))
    mode = "supabase" if settings.persist_remote else "dry-run:%s" % settings.work_dir
    print("wrote %d result(s) via %s" % (len(results), mode), file=sys.stderr)
    for path in paths:
        if path:
            print("receipt %s" % path, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
